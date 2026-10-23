"""Check that the teaching examples run and keep their stated rules."""

import math

import numpy as np
import polars as pl
import pytest

from examples import extensions, models, operations
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
