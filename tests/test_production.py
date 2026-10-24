"""A top stage that produces at stations, checked by hand.

The factory reviews at times 0, 1, 2, and so on. Each order splits into jobs of
batch_size units, and a station's service time is its time per unit times the
job's quantity. A finished job enters stock at the first review at or after it
leaves the last station. Times per unit are powers of two, so every time below
is exact in floating point.
"""

import polars as pl
import pytest

from flowsim import Model, moving_average, order_up_to


def factory_model(
    *,
    demand: float,
    initial: float,
    cover: float,
    batch_size: float,
    per_unit: list[float],
    buffer: int | None = None,
) -> Model:
    """Constant demand at one factory that produces on a line of single servers."""
    model = Model(time_unit="weeks")
    consumers = model.demand(
        name="Consumers",
        per_period=demand,
    )
    factory = model.stock_point(
        name="Factory",
        initial=initial,
        lead_time=None,
        batch_size=batch_size,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=cover,
        ),
        forecast_from="orders",
    )
    stations = [
        model.station(
            name=f"Step {index + 1}",
            capacity=1,
            service_time=time,
            buffer=buffer if index == 0 else None,
            external_overflow=None if buffer is None or index else "wait",
        )
        for index, time in enumerate(per_unit)
    ]
    model.route([factory, *stations, factory])
    model.supply(
        [consumers, factory],
        period=1,
    )
    return model


def inventory(result) -> dict[str, list]:
    return result.inventory.sort("period").to_dict(as_series=False)


def test_orders_split_into_jobs_that_return_at_the_next_review():
    # Demand is 50, the target is cover 2 times the last demand, i.e., 100, and
    # the initial stock of 100 meets it. Each period orders 50, which splits
    # into jobs of 16, 16, 16, and 2 that take 0.5, 0.5, 0.5, and 0.0625 at 1/32
    # per unit. Period 0's jobs run 0-0.5, 0.5-1, 1-1.5, and 1.5-1.5625, and
    # period 1's jobs queue behind them from 1.5625.
    result = factory_model(
        demand=50,
        initial=100,
        cover=2,
        batch_size=16,
        per_unit=[1 / 32],
    ).run(duration=4)
    jobs = result.customers.sort("customer_id")
    assert jobs.get_column("quantity").to_list() == [16, 16, 16, 2] * 4
    releases = [period for period in range(4) for _ in range(4)]
    assert jobs.get_column("arrival_time").to_list() == releases
    assert jobs.get_column("exit_time").to_list()[:8] == [
        0.5,
        1,
        1.5,
        1.5625,
        2.0625,
        2.5625,
        3.0625,
        3.125,
    ]
    assert result.visits.get_column("service_time").to_list()[:4] == [
        0.5,
        0.5,
        0.5,
        0.0625,
    ]
    # Period 1 receives the jobs that finished at 0.5 and at exactly 1, since
    # completions run before reviews at equal times. Period 2 receives 16 + 2,
    # and period 3 receives the jobs that finished at 2.0625 and 2.5625.
    records = inventory(result)
    assert records["received"] == [0, 32, 18, 32]
    assert records["order_quantity"] == [50] * 4
    # Period 3 has 32 on hand for demand of 50, so 18 wait.
    assert records["filled"] == [50, 50, 50, 32]
    assert records["backorders"] == [0, 0, 0, 18]
    assert records["on_hand"] == [50, 32, 0, 0]
    # Ordered but not yet received: 50, 50 + 50 - 32, 68 + 50 - 18, 100 + 50 - 32.
    assert records["on_order"] == [50, 68, 100, 118]
    # The factory never ships to a supplier or receives from one.
    assert result.shipments.height == 0
    settings = result.supply["stock_points"]["Factory"]
    assert settings["lead_time"] == "production"
    assert settings["batch_size"] == 16
    assert settings["cover"] == 2
    # A job's flow time is its production lead time. Period 2's first job runs
    # from 3.125 to 3.625, so nine jobs finish before the run ends at 4, with
    # flow times 0.5, 1, 1.5, 1.5625, 1.0625, 1.5625, 2.0625, 2.125, and 1.625.
    summary = result.summary.row(0, named=True)
    assert summary["arrivals"] == 16
    assert summary["completed"] == 9
    assert summary["remaining"] == 7
    assert summary["mean_flow_time"] == pytest.approx(13 / 9)


def test_batch_size_sets_whether_units_overlap_across_stations():
    # One order of 4 units at time 0 on two stations at 1/32 per unit. As one
    # job, the order takes Step 1 from 0 to 4/32 and Step 2 from 4/32 to 8/32.
    # As four jobs, Step 2 takes each unit as soon as Step 1 finishes it, so
    # the units leave at 2/32, 3/32, 4/32, and 5/32.
    def first_order_exits(batch_size: float) -> list[float]:
        result = factory_model(
            demand=4,
            initial=4,
            cover=1,
            batch_size=batch_size,
            per_unit=[1 / 32, 1 / 32],
        ).run(duration=2)
        assert inventory(result)["received"] == [0, 4]
        return (
            result.customers.filter(pl.col("arrival_time") == 0)
            .get_column("exit_time")
            .to_list()
        )

    assert first_order_exits(4) == [8 / 32]
    assert first_order_exits(100) == [8 / 32]
    assert first_order_exits(1) == [2 / 32, 3 / 32, 4 / 32, 5 / 32]


def test_an_order_of_whole_batches_adds_no_sliver_job():
    # 2.1 / 0.7 is 3.0000000000000004 in floating point, but the order is 3
    # batches, so it makes 3 jobs rather than a 4th of almost nothing.
    result = factory_model(
        demand=2.1,
        initial=2.1,
        cover=1,
        batch_size=0.7,
        per_unit=[1 / 32],
    ).run(duration=1)
    quantities = result.customers.get_column("quantity").to_list()
    assert len(quantities) == 3
    assert quantities == pytest.approx([0.7] * 3)


def test_a_finite_first_buffer_holds_released_jobs_outside():
    # With no waiting space at Step 1, released jobs wait outside, i.e., in a
    # release queue, and enter one at a time. The service order is unchanged.
    plain = factory_model(
        demand=50,
        initial=100,
        cover=2,
        batch_size=16,
        per_unit=[1 / 32],
    ).run(duration=4)
    held = factory_model(
        demand=50,
        initial=100,
        cover=2,
        batch_size=16,
        per_unit=[1 / 32],
        buffer=0,
    ).run(duration=4)
    assert held.customers.get_column("exit_time").to_list() == (
        plain.customers.get_column("exit_time").to_list()
    )
    assert inventory(held)["received"] == inventory(plain)["received"]
    # Job 2 enters Step 1 when job 1 leaves at 0.5, and job 4 when job 3 leaves
    # at 1.5. Period 3's jobs are all still outside at the end.
    waits = held.customers.get_column("outside_wait").to_list()
    assert waits[:4] == [0, 0.5, 1, 1.5]
    statuses = held.customers.get_column("status").to_list()
    assert statuses[-4:] == ["outside"] * 4
    assert held.stations.row(0, named=True)["outside_at_close"] > 0


def test_more_capacity_shortens_production_lead_times():
    def build(capacity: int) -> Model:
        model = Model(time_unit="weeks")
        consumers = model.demand(
            name="Consumers",
            per_period=lambda rng: max(0.0, rng.normal(100, 20)),
        )
        factory = model.stock_point(
            name="Factory",
            initial=300,
            lead_time=None,
            batch_size=25,
            shortage="backorder",
            policy=order_up_to(
                forecast=moving_average(window=5),
                safety_factor=1,
                cover=3,
            ),
            forecast_from="orders",
        )
        press = model.station(
            name="Press",
            capacity=capacity,
            service_time=lambda rng: rng.exponential(0.009),
        )
        model.route([factory, press, factory])
        model.supply(
            [consumers, factory],
            period=1,
        )
        return model

    one = build(1).experiment(
        duration=60,
        replications=5,
        warmup=10,
        seed=3,
    )
    two = build(2).experiment(
        duration=60,
        replications=5,
        warmup=10,
        seed=3,
    )
    # At 0.009 per unit, one press needs about 0.9 of each week for demand of
    # 100, so jobs queue. A second press halves the load.
    slow = one.intervals("mean_flow_time").row(0, named=True)["mean"]
    fast = two.intervals("mean_flow_time").row(0, named=True)["mean"]
    assert fast < slow
    fill = one.intervals(
        metric="fill_rate",
        stock_point="Factory",
    )
    assert fill.get_column("stock_point").to_list() == ["Factory"]


def build_error(build) -> str:
    with pytest.raises(ValueError) as error:
        build()
    return str(error.value)


def production_parts(**options):
    """Return a model, its demand, a retailer, and a factory that produces."""
    model = Model()
    consumers = model.demand(
        name="Consumers",
        per_period=10,
    )
    settings = {
        "initial": 0,
        "lead_time": None,
        "batch_size": 5,
        "shortage": "backorder",
        "policy": order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
            cover=1,
        ),
        "forecast_from": "orders",
    } | options
    retailer = model.stock_point(
        name="Retailer",
        initial=0,
        lead_time=1,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
        ),
        forecast_from="orders",
    )
    factory = model.stock_point(
        name="Factory",
        **settings,
    )
    return model, consumers, retailer, factory


def test_production_arguments_are_validated():
    assert "needs an explicit cover" in build_error(
        lambda: production_parts(
            policy=order_up_to(
                forecast=moving_average(window=1),
                safety_factor=0,
            )
        )
    )
    assert "Batch size must be a finite number" in build_error(
        lambda: production_parts(batch_size=None)
    )
    assert "Batch size must be finite and greater than zero" in build_error(
        lambda: production_parts(batch_size=0)
    )
    assert "batch_size requires lead_time=None" in build_error(
        lambda: production_parts(
            lead_time=1,
            policy=order_up_to(
                forecast=moving_average(window=1),
                safety_factor=0,
            ),
        )
    )
    model, consumers, retailer, factory = production_parts()
    assert "Only the top stage can produce" in build_error(
        lambda: model.supply([consumers, factory, retailer], period=1)
    )


def test_production_routes_are_checked_at_run_start():
    def run_error(arrange) -> str:
        model, consumers, retailer, factory = production_parts()
        model.supply(
            [consumers, retailer, factory],
            period=1,
        )
        arrange(
            model=model,
            retailer=retailer,
            factory=factory,
        )
        return build_error(lambda: model.run(duration=3))

    def station(model, name="Press", **options):
        return model.station(
            name=name,
            capacity=1,
            service_time=0.01,
            **options,
        )

    assert "needs a route to its first station" in run_error(
        lambda model, retailer, factory: None
    )

    def to_exit(model, retailer, factory):
        press = station(model)
        model.route([factory, press, model.exit])

    assert "'Press' routes to the exit" in run_error(to_exit)

    def stranded(model, retailer, factory):
        press = station(model)
        station(model, name="Spare")
        model.route([factory, press, factory])

    assert "'Spare' is unreachable from 'Factory'" in run_error(stranded)

    def patient(model, retailer, factory):
        press = station(
            model=model,
            patience=1,
            abandon_from="waiting",
        )
        model.route([factory, press, factory])

    assert "production jobs never abandon" in run_error(patient)

    def rejecting(model, retailer, factory):
        press = station(
            model=model,
            buffer=1,
            external_overflow="reject",
        )
        model.route([factory, press, factory])

    assert "cannot be rejected" in run_error(rejecting)

    def typed(model, retailer, factory):
        press = model.station(
            name="Press",
            capacity=1,
            service_time={"A": 0.01},
        )
        model.route([factory, press, factory])

    assert (
        "'Press' sets service times by customer type, and customers from "
        "'Factory' have no type"
    ) in run_error(typed)

    def from_retailer(model, retailer, factory):
        press = station(model)
        model.route([factory, press, factory])
        other = station(model, name="Other")
        model.route([retailer, other, retailer])

    assert "'Retailer' has a route" in run_error(from_retailer)


def test_stations_need_a_producing_top_stage():
    model = Model()
    consumers = model.demand(
        name="Consumers",
        per_period=10,
    )
    store = model.stock_point(
        name="Store",
        initial=0,
        lead_time=1,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=1),
            safety_factor=0,
        ),
        forecast_from="orders",
    )
    model.station(
        name="Press",
        capacity=1,
        service_time=1,
    )
    model.supply(
        [consumers, store],
        period=1,
    )
    assert "'Store' needs lead_time=None" in build_error(lambda: model.run(duration=3))


def test_production_route_edges_are_checked_when_added():
    model, consumers, retailer, factory = production_parts()
    press = model.station(
        name="Press",
        capacity=1,
        service_time=1,
    )
    assert "releases production jobs to a station" in build_error(
        lambda: model.route([factory, model.exit])
    )
    assert "has no routes" in build_error(lambda: model.route([consumers, press]))
    arrivals = model.source(
        name="Arrivals",
        interarrival=1,
    )
    assert "Only a station can return finished jobs" in build_error(
        lambda: model.route([arrivals, factory])
    )
    # A route may start and end at its stock point, but not revisit a station.
    assert "acyclic routes only" in build_error(
        lambda: model.route([factory, press, press, factory])
    )
    model.route([factory, press, factory])
    assert model.routing["Press"][None] == (("Factory", 1.0),)
