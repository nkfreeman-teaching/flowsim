"""Check that the teaching examples run and keep their stated rules."""

import math

import numpy as np
import polars as pl
import pytest

from examples import extensions, models, operations, supply_chain
from examples.service_day import (
    ON_TIME_SHARE,
    OVERTIME_LIMIT,
    STAFFING,
    WAIT_TARGET,
    staffing_exercise,
)


@pytest.mark.parametrize(
    "build",
    [
        models.deterministic_queue,
        models.service_network,
        models.branching_service,
        extensions.peak_service,
        extensions.buffered_line,
        extensions.repairing_machine,
        extensions.combined_line,
        operations.machining_line,
        operations.cross_dock,
    ],
)
def test_example_models_run(build):
    result = build().run(
        duration=60,
        seed=1,
        drain=True,
    )
    assert result.summary.get_column("remaining").item() == 0


def test_worked_exercise_preserves_customer_accounting_and_target_rule():
    comparison, decision = staffing_exercise(replications=3)
    # Each row's server count is the Service capacity of the model it names.
    assert decision.select(
        "servers",
        "scenario",
    ).rows() == list(STAFFING.items())
    # Meeting the share of 3 days takes ceil(0.9 * 3) = 3 on-time days.
    required = math.ceil(ON_TIME_SHARE * 3)
    assert required == 3
    for row in decision.to_dicts():
        experiment = comparison.experiments[row["scenario"]]
        assert experiment.runs[0].capacities["Service"] == row["servers"]
        runs = experiment.summary
        qualifying = runs.filter(pl.col("overtime") <= OVERTIME_LIMIT).height
        assert row["days_finished_on_time"] == qualifying
        assert row["meets_targets"] == (
            row["mean_wait_minutes"] <= WAIT_TARGET and qualifying >= required
        )
        assert runs.get_column("remaining").to_list() == [0, 0, 0]
        assert np.all(
            runs.get_column("arrivals").to_numpy()
            == runs.get_column("completed").to_numpy()
        )


def test_machining_line_keeps_its_buffers_and_failure_rules():
    result = operations.machining_line(buffers=(1, 2, 3, 0)).run(
        duration=operations.SHIFT,
        seed=3,
    )
    most_waiting = dict(
        result.states.group_by("station").agg(pl.col("waiting").max()).rows()
    )
    # The Saw has no waiting room, so unsawn blanks wait outside as raw stock.
    assert most_waiting == {"Saw": 0, "CNC": 1, "Wash": 2, "Assembly": 3, "Pack": 0}
    assert result.states.filter(pl.col("outside") > 0).get_column(
        "station"
    ).unique().to_list() == ["Saw"]
    assert set(result.failures.get_column("station")) == {"CNC"}
    steady = operations.machining_line(failures=False).run(
        duration=operations.SHIFT,
        seed=3,
    )
    assert steady.failures.height == 0
    # Blanks arrive every 2 minutes from 0, so 240 arrive in 480 minutes.
    assert steady.summary.get_column("arrivals").item() == 240


def test_cross_dock_holds_trucks_at_the_gate_when_the_yard_is_full():
    result = operations.cross_dock(
        doors=2,
        yard=1,
    ).run(
        duration=operations.DOCK_DAY,
        seed=5,
        drain=True,
    )
    most_waiting = dict(
        result.states.group_by("station").agg(pl.col("waiting").max()).rows()
    )
    assert most_waiting["Gate"] == 0
    assert most_waiting["Unload"] == 1
    gate = result.stations.filter(pl.col("station") == "Gate").to_dicts()[0]
    assert gate["blocking_fraction"] > 0
    assert result.summary.get_column("mean_outside_wait").item() > 0
    assert result.summary.get_column("remaining").item() == 0
    # Every truck leaves through outbound loading or put-away.
    finals = (
        result.visits.group_by("customer_id")
        .agg(pl.col("station").last())
        .get_column("station")
        .unique()
        .sort()
        .to_list()
    )
    assert finals == ["Outbound load", "Put-away"]


def test_beer_game_example_keeps_its_stages_and_rules():
    result = supply_chain.beer_game().run(
        duration=supply_chain.WEEKS,
        seed=2,
        warmup=supply_chain.WARMUP,
    )
    assert result.supply["chain"] == ["Consumers", *supply_chain.STAGES]
    assert result.stock_points.get_column("periods").to_list() == [84] * 4
    # Each stage starts with two weeks of mean demand, 200 cases.
    first = result.inventory.filter(pl.col("period") == 0)
    assert first.get_column("on_hand").to_list()[0] == pytest.approx(
        200 - first.get_column("demand").to_list()[0]
    )
    shipments = result.shipments.drop_nulls("arrival_time")
    lead_times = (
        shipments.get_column("arrival_time") - shipments.get_column("ship_time")
    ).unique()
    assert lead_times.to_list() == [2.0]


def test_bullwhip_study_compounds_without_sharing():
    comparison = supply_chain.bullwhip_study(replications=3)
    table = supply_chain.amplification(comparison)
    rows = {row["scenario"]: row for row in table.to_dicts()}
    private = [rows["Forecast from orders"][stage] for stage in supply_chain.STAGES]
    shared = [rows["Share consumer demand"][stage] for stage in supply_chain.STAGES]
    assert private == sorted(private)
    # The retailer sees consumer demand either way, so only upstream changes.
    assert shared[0] == pytest.approx(private[0])
    assert shared[-1] < private[-1]


def test_capacity_study_changes_fill_rates_but_not_orders():
    comparison = supply_chain.capacity_study(replications=3)
    factory = comparison.stock_points.filter(pl.col("stock_point") == "Factory")
    ratios = {
        scenario: rows.sort("replication").get_column("bullwhip_ratio").to_list()
        for (scenario,), rows in factory.group_by("scenario")
    }
    # The inventory position counts units on order, so receipts never change
    # it, and every scenario with a two-week cover places the same orders, up
    # to the order in which floating-point stock and orders are added.
    base = ratios["Two-week lead time"]
    assert ratios["Brew 120 per week"] == pytest.approx(base, rel=1e-12)
    assert ratios["Brew 200 per week"] == pytest.approx(base, rel=1e-12)
    assert ratios["Brew 150, cover 3"] != pytest.approx(base, rel=1e-3)
    fill = comparison.intervals(
        metric="fill_rate",
        stock_point="Factory",
    )
    means = dict(fill.select("scenario", "mean").rows())
    assert means["Brew 120 per week"] < means["Brew 150 per week"]
    assert means["Brew 150 per week"] < means["Brew 200 per week"]
    jobs = comparison.experiments["Brew 150 per week"].runs[0].customers
    assert jobs.get_column("quantity").max() == supply_chain.BATCH
