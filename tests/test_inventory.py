"""Stock points, ordering, and shipments, checked against hand calculations.

Periods are numbered from 0, and period k is reviewed at time k. In each period
a stage receives shipments that are due, fills backorders and then new orders
from stock, and orders up to cover * forecast. Orders placed in period k are
the next stage's incoming orders in period k.
"""

import json
import math

import numpy as np
import polars as pl
import pytest

import flowsim
from flowsim import Model, compare, moving_average, order_up_to
from tests.models import beer_chain, deterministic_queue


def sequence(values):
    """Return a sampler that hands out the given values in order."""
    remaining = iter(values)
    return lambda rng: next(remaining)


def stage(model, name, **options):
    settings = {
        "initial": 0,
        "lead_time": 1,
        "shortage": "backorder",
        "policy": order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
        ),
        "forecast_from": "orders",
    } | options
    return model.stock_point(
        name=name,
        **settings,
    )


def records(result, stock_point):
    """Return one stock point's inventory columns as lists in period order."""
    return (
        result.inventory.filter(pl.col("stock_point") == stock_point)
        .sort("period")
        .to_dict(as_series=False)
    )


def step_model() -> Model:
    """Demand is 10 for periods 0 to 3 and 20 afterward, with a lead time of 2."""
    model = Model(time_unit="weeks")
    demand = model.demand(
        name="Consumers",
        per_period=sequence([10, 10, 10, 10, 20, 20, 20]),
    )
    retailer = stage(
        model=model,
        name="Retailer",
        initial=20,
        lead_time=2,
    )
    model.supply(
        [demand, retailer],
        period=1,
    )
    return model


def test_step_response_matches_hand_calculation():
    result = step_model().run(
        duration=7,
        seed=1,
    )
    # The target is 2 * D_t, and the position before ordering is the prior
    # target minus D_t, so q_t = D_t + 2 (D_t - D_{t-1}). The initial stock of
    # 20 equals the first target, so q_0 = 10.
    assert records(result, "Retailer")["order_quantity"] == [10, 10, 10, 10, 40, 20, 20]
    assert records(result, "Retailer")["target"] == [20, 20, 20, 20, 40, 40, 40]
    # Each order arrives two periods later: 10 in periods 2 to 5 and 40 in 6.
    assert records(result, "Retailer")["received"] == [0, 0, 10, 10, 10, 10, 40]
    # Period 4: 10 arrives for demand of 20, leaving 10 backordered. Period 5:
    # the 10 that arrives clears that backorder, so all 20 new units wait.
    # Period 6: 40 arrives, clears 20 backorders, and fills 20 new units.
    assert records(result, "Retailer")["filled"] == [10, 10, 10, 10, 10, 0, 20]
    assert records(result, "Retailer")["shipped"] == [10, 10, 10, 10, 10, 10, 40]
    assert records(result, "Retailer")["backorders"] == [0, 0, 0, 0, 10, 20, 0]
    assert records(result, "Retailer")["on_hand"] == [10, 0, 0, 0, 0, 0, 0]
    assert records(result, "Retailer")["position"] == [20, 20, 20, 20, 40, 40, 40]
    assert result.shipments.select("ship_time", "arrival_time").rows() == [
        (0, 2),
        (1, 3),
        (2, 4),
        (3, 5),
        (4, 6),
        (5, None),
        (6, None),
    ]
    assert result.shipments.get_column("sender").unique().to_list() == ["Supplier"]
    row = result.stock_points.row(0, named=True)
    # Filled 70 of 100 units demanded in the period they were demanded.
    assert row["fill_rate"] == pytest.approx(0.7)
    assert row["periods"] == 7


def test_stock_point_metrics_use_periods_after_warmup():
    result = step_model().run(
        duration=7,
        seed=1,
        warmup=4,
    )
    row = result.stock_points.row(0, named=True)
    # Periods 4 to 6 have demand 20, 20, 20 and orders 40, 20, 20.
    assert row["periods"] == 3
    assert row["mean_demand"] == 20
    assert row["mean_order"] == pytest.approx(80 / 3)
    # Order variance is ((40 - 80/3)^2 + 2 (20 - 80/3)^2) / 2 = 400/3.
    assert row["order_variance"] == pytest.approx(400 / 3)
    # Constant demand has zero variance, so the ratio is missing, not infinite.
    assert row["demand_variance"] == 0
    assert row["bullwhip_ratio"] is None
    # Filled 10 + 0 + 20 of 60 units, with backorders 10, 20, 0.
    assert row["fill_rate"] == pytest.approx(0.5)
    assert row["mean_backorders"] == pytest.approx(10)
    assert row["mean_on_hand"] == 0
    assert row["lost_units"] == 0


@pytest.mark.parametrize(
    ("shortage", "expected"),
    [
        (
            "backorder",
            {
                "on_hand": [15, 5, 0, 0],
                "backorders": [0, 0, 5, 0],
                "filled": [10, 10, 5, 10],
                "shipped": [10, 10, 5, 15],
                "lost": [0, 0, 0, 0],
                "order_quantity": [15, 10, 10, 10],
            },
        ),
        (
            "lost",
            {
                "on_hand": [15, 5, 0, 5],
                "backorders": [0, 0, 0, 0],
                "filled": [10, 10, 5, 10],
                "shipped": [10, 10, 5, 10],
                "lost": [0, 0, 5, 0],
                "order_quantity": [15, 10, 5, 10],
            },
        ),
    ],
)
def test_shortage_accounting_when_initial_stock_runs_out(shortage, expected):
    # Demand is 10, the lead time is 3, and the target is 30. Period 0 leaves
    # 15 on hand and orders 15, which arrives in period 3. Period 1 leaves 5
    # and orders 10. Period 2 fills 5 of 10. A backorder keeps the position at
    # 0 + 25 - 5 = 20, so it orders 10, and a lost sale leaves it at 25, so it
    # orders 5. In period 3, the 15 that arrives clears any backorder first.
    model = Model(time_unit="days")
    demand = model.demand(
        name="Consumers",
        per_period=10,
    )
    store = stage(
        model=model,
        name="Store",
        initial=25,
        lead_time=3,
        shortage=shortage,
    )
    model.supply(
        [demand, store],
        period=1,
    )
    result = model.run(
        duration=4,
        seed=1,
    )
    for name, values in expected.items():
        assert records(result, "Store")[name] == values, name
    row = result.stock_points.row(0, named=True)
    assert row["fill_rate"] == pytest.approx(35 / 40)
    assert row["lost_units"] == (5 if shortage == "lost" else 0)


def two_stage_model(wholesaler_shortage: str) -> Model:
    model = Model(time_unit="weeks")
    demand = model.demand(
        name="Consumers",
        per_period=10,
    )
    retailer = stage(
        model=model,
        name="Retailer",
        initial=10,
        lead_time=1,
    )
    wholesaler = stage(
        model=model,
        name="Wholesaler",
        initial=0,
        lead_time=2,
        shortage=wholesaler_shortage,
    )
    model.supply(
        [demand, retailer, wholesaler],
        period=1,
    )
    return model


def test_upstream_stage_fills_downstream_orders_in_the_same_period():
    result = two_stage_model("backorder").run(
        duration=5,
        seed=1,
    )
    # The wholesaler's incoming orders are the retailer's orders, period by period.
    assert (
        records(result, "Wholesaler")["demand"]
        == records(result, "Retailer")["order_quantity"]
    )
    # Period 0: the wholesaler has nothing, so it backorders 10, and its target
    # 2 * 10 = 20 less its position of -10 gives an order of 30, due in period 2.
    # Period 1: backorders reach 20, the position is 0 + 30 - 20 = 10, and it
    # orders 10. Period 2: 30 arrives, 20 backorders and 10 new units ship.
    assert records(result, "Wholesaler")["order_quantity"] == [30, 10, 10, 10, 10]
    assert records(result, "Wholesaler")["backorders"] == [10, 20, 0, 0, 0]
    assert records(result, "Wholesaler")["shipped"] == [0, 0, 30, 10, 10]
    # The retailer receives with its own one-period lead time. It backorders
    # consumers in periods 1 and 2, then the 30 in period 3 clears both.
    assert records(result, "Retailer")["received"] == [0, 0, 0, 30, 10]
    assert records(result, "Retailer")["backorders"] == [0, 10, 20, 0, 0]
    shipments = result.shipments.filter(pl.col("receiver") == "Retailer")
    assert shipments.select(
        "quantity",
        "ship_time",
        "arrival_time",
    ).rows() == [
        (30, 2, 3),
        (10, 3, 4),
        (10, 4, None),
    ]
    supplier = result.shipments.filter(pl.col("sender") == "Supplier")
    assert supplier.get_column("arrival_time").to_list()[:2] == [2, 3]


def test_lost_upstream_order_leaves_the_downstream_pipeline():
    result = two_stage_model("lost").run(
        duration=3,
        seed=1,
    )
    # Period 0: the wholesaler loses the retailer's order of 10, so the
    # retailer will never receive it. Period 1: the retailer backorders 10 and
    # sees a position of 0 + 0 - 10, so it orders 20 rather than 10, and the
    # wholesaler loses that too. Period 2: the position is 0 + 0 - 20, so the
    # retailer orders 30, and the wholesaler fills 20 of it from its first
    # receipt. Recorded pipelines precede each period's upstream loss.
    assert records(result, "Wholesaler")["lost"] == [10, 20, 10]
    assert records(result, "Wholesaler")["filled"] == [0, 0, 20]
    assert records(result, "Retailer")["order_quantity"] == [10, 20, 30]
    assert records(result, "Retailer")["on_order"] == [10, 20, 30]


def test_sampled_lead_times_keep_sending_order_and_round_up_to_reviews():
    model = Model(time_unit="weeks")
    demand = model.demand(
        name="Consumers",
        per_period=10,
    )
    retailer = stage(
        model=model,
        name="Retailer",
        initial=20,
        lead_time=sequence([2.5, 1.0, 1.0, 1.0]),
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=2,
        ),
    )
    model.supply(
        [demand, retailer],
        period=1,
    )
    result = model.run(
        duration=4,
        seed=1,
    )
    # A lead time of 2.5 from period 0 is received at the review in period 3.
    # The next two shipments would arrive in periods 2 and 3, but they cannot
    # pass the first one, so all three arrive in period 3.
    assert result.shipments.select(
        "lead_time",
        "ship_time",
        "arrival_time",
    ).rows() == [
        (2.5, 0, 3),
        (1.0, 1, 3),
        (1.0, 2, 3),
        (1.0, 3, None),
    ]
    assert records(result, "Retailer")["received"] == [0, 0, 0, 30]
    assert records(result, "Retailer")["target"] == [20, 20, 20, 20]


def test_safety_stock_uses_the_spread_of_the_forecast_window():
    model = Model(time_unit="weeks")
    demand = model.demand(
        name="Consumers",
        per_period=sequence([10, 14, 6]),
    )
    retailer = stage(
        model=model,
        name="Retailer",
        initial=100,
        lead_time=4,
        policy=order_up_to(
            forecast=moving_average(window=2),
            safety_factor=1,
        ),
    )
    model.supply(
        [demand, retailer],
        period=1,
    )
    result = model.run(
        duration=3,
        seed=1,
    )
    # Cover is 4 periods. Period 0 has one observation, so no spread. Period 1
    # averages 10 and 14, with sample standard deviation sqrt(8), so the target
    # is 4 * 12 + sqrt(4) * sqrt(8). Period 2 averages 14 and 6, with deviation
    # sqrt(32), so the target is 4 * 10 + 2 * sqrt(32).
    assert records(result, "Retailer")["forecast"] == [10, 12, 10]
    assert records(result, "Retailer")["target"] == pytest.approx(
        [40, 48 + 2 * math.sqrt(8), 40 + 2 * math.sqrt(32)]
    )


def test_safety_stock_waits_for_a_full_forecast_window():
    model = Model(time_unit="weeks")
    demand = model.demand(
        name="Consumers",
        per_period=sequence([10, 14, 6]),
    )
    retailer = stage(
        model=model,
        name="Retailer",
        initial=100,
        lead_time=1,
        policy=order_up_to(
            forecast=moving_average(window=3),
            safety_factor=2,
        ),
    )
    model.supply(
        [demand, retailer],
        period=1,
    )
    result = model.run(
        duration=3,
        seed=1,
    )
    # Periods 0 and 1 hold one and two of the three observations, so they
    # carry no safety stock. Period 2 averages 10, 14, and 6, with sample
    # standard deviation 4, so the target is 1 * 10 + 2 * sqrt(1) * 4.
    assert records(result, "Retailer")["target"] == pytest.approx([10, 12, 18])


def test_moving_average_orders_follow_the_closed_form_recursion():
    result = beer_chain().run(
        duration=60,
        seed=5,
    )
    demand = np.asarray(records(result, "Retailer")["demand"])
    orders = np.asarray(records(result, "Retailer")["order_quantity"])
    # With window p = 5 and cover L = 2, the target is (L/p) times the sum of
    # the last 5 demands, so q_t = D_t + (L/p) (D_t - D_{t-5}) once a full
    # window exists for both this period and the last (t >= 5).
    expected = demand[5:] + 0.4 * (demand[5:] - demand[:-5])
    np.testing.assert_allclose(
        actual=orders[5:],
        desired=expected,
        rtol=1e-12,
    )


def test_retailer_bullwhip_ratio_matches_the_closed_form():
    # For independent demand, a 5-period moving average, cover 2, and no safety
    # stock, Var(q) / Var(D) = 1 + 2L/p + 2L^2/p^2 = 1 + 0.8 + 0.32 = 2.12
    # (Chen, Drezner, Ryan, and Simchi-Levi 1999, equation 14.8).
    expected = 1 + 2 * 2 / 5 + 2 * 2**2 / 5**2
    assert expected == pytest.approx(2.12)
    trials = beer_chain().experiment(
        duration=1000,
        replications=20,
        seed=11,
        warmup=20,
    )
    interval = trials.intervals(
        metric="bullwhip_ratio",
        stock_point="Retailer",
    ).row(0, named=True)
    assert interval["lower"] < expected < interval["upper"]
    # A target of three periods would give 2.92, which this width rules out.
    assert interval["upper"] - interval["lower"] < 0.25
    # The closed form allows negative orders, which the retailer never needs
    # here. Upstream stages do truncate, so the closed form is not used there.
    for run in trials.runs:
        assert min(records(run, "Retailer")["order_quantity"]) > 0


def test_end_demand_forecasts_match_the_retailer_and_damp_the_bullwhip():
    shared = beer_chain("end_demand").run(
        duration=104,
        seed=3,
        warmup=20,
    )
    # Every stage averages the same consumer demand over the same window.
    for name in ["Wholesaler", "Distributor", "Factory"]:
        assert records(shared, name)["forecast"] == pytest.approx(
            records(shared, "Retailer")["forecast"],
            rel=1e-12,
        )
    private = beer_chain("orders").run(
        duration=104,
        seed=3,
        warmup=20,
    )
    # Consumer demand depends only on the seed and the demand's name.
    assert (
        records(shared, "Retailer")["demand"] == records(private, "Retailer")["demand"]
    )
    ratios = {
        name: dict(run.stock_points.select("stock_point", "bullwhip_ratio").rows())
        for name, run in [("shared", shared), ("private", private)]
    }
    assert ratios["shared"]["Factory"] < ratios["private"]["Factory"]
    # Without sharing, the bullwhip compounds up the chain.
    private_ratios = list(ratios["private"].values())
    assert private_ratios == sorted(private_ratios)


def test_adding_a_stage_leaves_consumer_demand_unchanged():
    def chain(names):
        model = Model(time_unit="weeks")
        demand = model.demand(
            name="Consumers",
            per_period=lambda rng: rng.normal(100, 10),
        )
        stages = [
            stage(
                model=model,
                name=name,
                initial=100,
            )
            for name in names
        ]
        model.supply(
            [demand, *stages],
            period=1,
        )
        return model.run(
            duration=20,
            seed=8,
        )

    short = chain(["Retailer"])
    long = chain(["Retailer", "Wholesaler"])
    assert records(short, "Retailer")["demand"] == records(long, "Retailer")["demand"]


def test_comparisons_estimate_stock_point_metrics_with_their_own_column(tmp_path):
    comparison = compare(
        scenarios={
            "Orders": beer_chain("orders"),
            "Shared demand": beer_chain("end_demand"),
        },
        duration=60,
        replications=3,
        warmup=10,
    )
    differences = comparison.differences(
        metric="bullwhip_ratio",
        stock_point="Factory",
    )
    assert differences.columns == [
        "scenario",
        "baseline",
        "metric",
        "stock_point",
        "runs",
        "observed_runs",
        "mean",
        "lower",
        "upper",
        "confidence",
    ]
    # Each difference is the matched replications' ratios subtracted.
    ratios = comparison.stock_points.filter(pl.col("stock_point") == "Factory")
    by_scenario = {
        name: ratios.filter(pl.col("scenario") == name)
        .sort("replication")
        .get_column("bullwhip_ratio")
        .to_numpy()
        for name in ["Orders", "Shared demand"]
    }
    assert differences.get_column("mean").item() == pytest.approx(
        (by_scenario["Shared demand"] - by_scenario["Orders"]).mean()
    )
    intervals = comparison.experiments["Orders"].intervals(metric="fill_rate")
    assert intervals.get_column("stock_point").to_list() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]
    with pytest.raises(ValueError, match="stock-point metric, so name a stock point"):
        comparison.intervals(metric="bullwhip_ratio")
    with pytest.raises(ValueError, match="Choose a stock-point metric"):
        comparison.intervals(
            metric="mean_wait",
            stock_point="Factory",
        )
    comparison.export(
        directory=tmp_path,
        metric="bullwhip_ratio",
        stock_point="Factory",
    )
    assert pl.read_csv(tmp_path / "stock_points.csv").height == 2 * 3 * 4
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["stock_point"] == "Factory"
    html = comparison.viewer(
        metric="bullwhip_ratio",
        stock_point="Factory",
    )
    assert "Order variance / demand variance at Factory" in html


def test_supply_run_exports_its_tables_and_settings(tmp_path):
    result = step_model().run(
        duration=7,
        seed=1,
    )
    result.export(tmp_path)
    for name in ["inventory", "shipments", "stock_points"]:
        exported = pl.read_csv(
            source=tmp_path / f"{name}.csv",
            schema_overrides=getattr(result, name).schema,
        )
        assert exported.equals(getattr(result, name)), name
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["supply"]["chain"] == ["Consumers", "Retailer"]
    assert metadata["supply"]["stock_points"]["Retailer"]["cover"] == 2
    html = result.viewer(tmp_path / "viewer.html")
    assert "FlowSim supply chain" in html
    assert (tmp_path / "viewer.html").exists()


def test_service_network_export_writes_no_inventory_tables(tmp_path):
    deterministic_queue().run(duration=7).export(tmp_path)
    assert not (tmp_path / "inventory.csv").exists()
    assert "supply" not in json.loads((tmp_path / "metadata.json").read_text())


def build_error(build):
    with pytest.raises(ValueError) as error:
        build()
    return str(error.value)


def test_supply_definitions_reject_unstated_or_inconsistent_behavior():
    def model_with(**options):
        model = Model()
        demand = model.demand(
            name="Consumers",
            per_period=10,
        )
        store = stage(
            model=model,
            name="Store",
            **options,
        )
        return model, demand, store

    model, demand, store = model_with(lead_time=1.5)
    assert "whole number of review periods" in build_error(
        lambda: model.supply([demand, store], period=1)
    )
    assert "needs an explicit cover" in build_error(
        lambda: model_with(lead_time=lambda rng: 2.0)
    )
    assert "Give cover only for a sampled lead time" in build_error(
        lambda: model_with(
            policy=order_up_to(
                forecast=moving_average(window=1),
                safety_factor=0,
                cover=2,
            )
        )
    )
    assert "window of at least 2" in build_error(
        lambda: order_up_to(
            forecast=moving_average(window=1),
            safety_factor=1,
        )
    )
    assert "shortage must be" in build_error(lambda: model_with(shortage="wait"))
    assert "forecast_from must be" in build_error(
        lambda: model_with(forecast_from="forecast")
    )
    assert "policy must come from" in build_error(lambda: model_with(policy=None))


def test_supply_chains_stay_separate_from_service_networks():
    model = Model()
    demand = model.demand(
        name="Consumers",
        per_period=10,
    )
    store = stage(
        model=model,
        name="Store",
    )
    assert "not in a supply chain" in build_error(lambda: model.run(duration=3))
    assert "starts with demand" in build_error(
        lambda: model.supply([store, demand], period=1)
    )
    model.supply(
        [demand, store],
        period=1,
    )
    assert "either a service network or a supply chain" in build_error(
        lambda: model.source(
            name="Customers",
            interarrival=1,
        )
    )
    assert "already has a supply chain" in build_error(
        lambda: model.supply([demand, store], period=1)
    )
    assert "drain serves customers" in build_error(
        lambda: model.run(
            duration=3,
            drain=True,
        )
    )
    reserved = Model()
    reserved_demand = reserved.demand(
        name="Consumers",
        per_period=10,
    )
    supplier = stage(
        model=reserved,
        name="Supplier",
    )
    assert "reserved" in build_error(
        lambda: reserved.supply([reserved_demand, supplier], period=1)
    )
    network = deterministic_queue()
    network_demand = network.demand(
        name="Consumers",
        per_period=10,
    )
    network_store = stage(
        model=network,
        name="Store",
    )
    assert "either a service network or a supply chain" in build_error(
        lambda: network.supply([network_demand, network_store], period=1)
    )


def test_negative_sampled_demand_stops_the_run():
    model = Model()
    demand = model.demand(
        name="Consumers",
        per_period=sequence([10, -1]),
    )
    store = stage(
        model=model,
        name="Store",
    )
    model.supply(
        [demand, store],
        period=1,
    )
    assert "Demand at 'Consumers'" in build_error(lambda: model.run(duration=3))


def test_policies_are_part_of_the_public_package():
    assert flowsim.order_up_to is order_up_to
    assert flowsim.moving_average is moving_average


def test_constant_lead_time_cover_counts_whole_periods():
    model = Model(time_unit="days")
    demand = model.demand(
        name="Consumers",
        per_period=10,
    )
    store = stage(
        model=model,
        name="Store",
        initial=30,
        lead_time=0.3,
    )
    model.supply(
        [demand, store],
        period=0.1,
    )
    result = model.run(
        duration=0.5,
        seed=1,
    )
    # 0.3 / 0.1 is 2.9999999999999996 in floating point, but the lead time is
    # three review periods, so the target is exactly 3 * 10 and each order
    # arrives three reviews after it is sent.
    assert records(result, "Store")["target"] == [30] * 5
    assert result.shipments.get_column("arrival_time").to_list()[:2] == [
        pytest.approx(0.3),
        pytest.approx(0.4),
    ]
