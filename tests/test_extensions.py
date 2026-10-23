"""Independent arrival, shift, buffer, and reliability oracles."""

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import Model, compare
from flowsim.schedules import next_arrival, validate_schedule
from tests.models import service_network, single_station


class FixedHazard:
    def exponential(self, scale):
        assert scale == 1
        return 5


def test_integrated_hazard_crosses_inactive_and_active_periods():
    points = validate_schedule(
        points=[(0, 0), (2, 2), (4, 0), (6, 1)],
        label="Arrival",
    )
    # Four hazard units are spent between 2 and 4, and one between 6 and 7.
    assert (
        next_arrival(
            points=points,
            now=0,
            horizon=10,
            rng=FixedHazard(),
        )
        == 7
    )
    assert (
        next_arrival(
            points=points,
            now=0,
            horizon=7,
            rng=FixedHazard(),
        )
        is None
    )


def test_rate_schedule_has_no_arrivals_during_zero_rate_periods():
    model = Model()
    arrivals = model.source(
        name="Customers",
        rates=[(0, 0), (10, 2), (20, 0)],
    )
    model.route([arrivals, model.exit])
    result = model.run(duration=30)
    times = result.customers.get_column("arrival_time").to_numpy()
    assert len(times) > 0
    assert np.all((times >= 10) & (times < 20))


def test_constant_rate_matches_exponential_interarrival_distribution():
    runs = []
    for options in [
        {"rates": [(0, 0.5)]},
        {"interarrival": lambda rng: rng.exponential(scale=2)},
    ]:
        model = Model()
        source = model.source(
            name="Customers",
            **options,
        )
        model.route([source, model.exit])
        runs.append(model.run(duration=100))
    assert runs[0].customers.height == runs[1].customers.height
    assert np.allclose(
        runs[0].customers.get_column("arrival_time").to_numpy(),
        runs[1].customers.get_column("arrival_time").to_numpy(),
    )


def test_piecewise_poisson_counts_match_the_integrated_rate():
    model = Model()
    source = model.source(
        name="Customers",
        rates=[(0, 0.1), (10, 1), (20, 0.2)],
    )
    model.route([source, model.exit])
    counts = [
        model.run(
            duration=30,
            seed=seed,
        ).customers.height
        for seed in range(100)
    ]
    # E[N] = 10*0.1 + 10*1 + 10*0.2 = 13, SE over 100 days = sqrt(13/100).
    assert abs(np.mean(counts) - 13) < 5 * (13 / 100) ** 0.5


@pytest.mark.parametrize(
    "policy,starts,ends",
    [
        ("finish", [0, 5, 9], [4, 9, 13]),
        ("pause", [0, 7, 11], [7, 11, 15]),
    ],
)
def test_shift_end_rules_preserve_work_and_waits(policy, starts, ends):
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=4,
        staffing=[(0, 1), (2, 0), (5, 1), (100, 0)],
        shift_end=policy,
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=3,
        drain=True,
    )
    assert result.visits.get_column("service_start").to_list() == starts
    assert result.visits.get_column("service_end").to_list() == ends
    assert result.end_time == ends[-1]
    processing = result.activities.filter(pl.col("state") == "processing")
    assert sum(row["end"] - row["start"] for row in processing.to_dicts()) == 12


def test_decimal_service_that_ends_at_a_shift_change_finishes_then():
    # By hand, service runs from 0.1 to 0.1 + 0.2 = 0.3, when the shift ends.
    # In floating point, 0.1 + 0.2 is 0.30000000000000004, one representable
    # time after the shift change at 0.3.
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0.1,
        limit=1,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=0.2,
        staffing=[(0, 1), (0.3, 0), (5, 1)],
        shift_end="pause",
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=6,
        drain=True,
    )
    assert result.visits.get_column("service_end").to_list() == [0.3]
    assert result.activities.get_column("state").to_list() == ["processing"]


def test_staffing_initially_zero_waits_until_a_server_is_scheduled():
    result = single_station(
        staffing=[(0, 0), (5, 1)],
        shift_end="finish",
    ).run(
        duration=3,
        drain=True,
    )
    assert result.visits.get_column("service_start").to_list() == [5, 8, 11]
    assert result.end_time == 14
    metrics = result.stations.to_dicts()[0]
    assert metrics["mean_scheduled_servers"] == 0
    assert metrics["staffed_utilization"] is None
    assert metrics["mean_queue"] == 2


def test_no_future_staffing_raises_instead_of_an_infinite_drain():
    model = single_station(
        staffing=[(0, 1), (1, 0)],
        shift_end="finish",
    )
    with pytest.raises(RuntimeError, match="no future staffing"):
        model.run(
            duration=4,
            drain=True,
        )


def test_paused_server_must_return_even_when_another_server_remains_active():
    model = Model()
    one = model.source(
        name="One",
        interarrival=10,
        first_arrival=0,
        limit=1,
    )
    two = model.source(
        name="Two",
        interarrival=10,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Service",
        capacity=2,
        service_time=4,
        staffing=[(0, 2), (1, 1)],
        shift_end="pause",
        time_to_failure=100,
        repair_time=1,
        failure_clock="available",
    )
    model.route([one, station, model.exit])
    model.route([two, station, model.exit])
    with pytest.raises(RuntimeError, match="Server 2.*no future staffing"):
        model.run(
            duration=2,
            drain=True,
        )


def test_finite_waiting_room_rejects_without_counting_rejections_as_completed():
    result = single_station(
        buffer=0,
        external_overflow="reject",
    ).run(
        duration=4,
        drain=True,
    )
    assert result.customers.get_column("status").to_list() == [
        "completed",
        "rejected",
        "rejected",
    ]
    totals = result.summary.to_dicts()[0]
    assert totals["arrivals"] == 3
    assert totals["admitted"] == totals["completed"] == 1
    assert totals["rejected"] == 2
    assert totals["remaining"] == 0
    assert totals["cohort_completions"] == 1
    assert totals["mean_flow_time"] == 3
    assert totals["mean_wip"] == 0.75
    assert result.stations.to_dicts()[0]["max_queue"] == 0


def test_external_waiting_is_separate_from_inside_queue_and_wip():
    result = single_station(
        buffer=0,
        external_overflow="wait",
    ).run(
        duration=4,
        drain=True,
    )
    assert result.customers.get_column("admission_time").to_list() == [0, 3, 6]
    assert result.customers.get_column("outside_wait").to_list() == [0, 2, 4]
    assert result.customers.get_column("flow_time").to_list() == [3, 5, 7]
    assert result.summary.to_dicts()[0]["mean_wip"] == 1
    assert result.stations.to_dicts()[0]["mean_queue"] == 0
    assert result.stations.to_dicts()[0]["mean_outside_queue"] == 1


def test_shift_start_precedes_an_arrival_at_the_same_time():
    # The server starts at 5 and the only customer arrives at 5. With no
    # waiting room, the customer is served only if the shift change runs first.
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=5,
        limit=1,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
        staffing=[(0, 0), (5, 1)],
        shift_end="finish",
        buffer=0,
        external_overflow="reject",
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=6,
        drain=True,
    )
    assert result.customers.get_column("status").to_list() == ["completed"]
    assert result.visits.get_column("service_start").to_list() == [5]
    assert result.visits.get_column("service_end").to_list() == [6]


def test_repair_end_precedes_an_arrival_at_the_same_time():
    # The server fails at 1 and is repaired at 1 + 2 = 3, when the only
    # customer arrives. Service runs from 3 to 3.5, before the next failure at
    # 3 + 1 = 4.
    model = Model()
    source = model.source(
        name="Parts",
        interarrival=1,
        first_arrival=3,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=0.5,
        buffer=0,
        external_overflow="reject",
        time_to_failure=1,
        repair_time=2,
        failure_clock="available",
    )
    model.route([source, station, model.exit])
    result = model.run(duration=4)
    assert result.failures.row(0, named=True)["failure_time"] == 1
    assert result.failures.row(0, named=True)["repair_end"] == 3
    assert result.customers.get_column("status").to_list() == ["completed"]
    assert result.visits.get_column("service_start").to_list() == [3]
    assert result.visits.get_column("service_end").to_list() == [3.5]


@pytest.mark.parametrize(
    "walk_in_gap,finish_order,second_walk_in_wait,press_blocked",
    [
        # The press part asks for Finish at 1, before the walk-in at 2.
        (2, ["Walk-ins", "Line", "Walk-ins"], 6 - 2, 3 - 1),
        # The walk-in at 0.5 asks before the press part at 1.
        (0.5, ["Walk-ins", "Walk-ins", "Line"], 3 - 0.5, 6 - 1),
    ],
)
def test_outside_arrivals_and_blocked_transfers_share_one_admission_line(
    walk_in_gap,
    finish_order,
    second_walk_in_wait,
    press_blocked,
):
    # A walk-in occupies Finish from 0 to 3, and Press finishes a part at 1.
    # Finish has no waiting room, so the part and the second walk-in wait in
    # one line and enter Finish at 3 and 6 in the order they asked.
    model = Model()
    line = model.source(
        name="Line",
        interarrival=1,
        first_arrival=0,
        limit=1,
    )
    walk_ins = model.source(
        name="Walk-ins",
        interarrival=walk_in_gap,
        first_arrival=0,
        limit=2,
    )
    press = model.station(
        name="Press",
        capacity=1,
        service_time=1,
    )
    finish = model.station(
        name="Finish",
        capacity=1,
        service_time=3,
        buffer=0,
        external_overflow="wait",
    )
    model.route([line, press, finish, model.exit])
    model.route([walk_ins, finish, model.exit])
    result = model.run(
        duration=4,
        drain=True,
    )
    finish_visits = result.visits.filter(pl.col("station") == "Finish").sort(
        "service_start"
    )
    assert finish_visits.get_column("source").to_list() == finish_order
    assert finish_visits.get_column("service_start").to_list() == [0, 3, 6]
    walk_in_waits = (
        result.customers.filter(pl.col("source") == "Walk-ins")
        .sort("arrival_time")
        .get_column("outside_wait")
        .to_list()
    )
    assert walk_in_waits == [0, second_walk_in_wait]
    press_visit = result.visits.filter(pl.col("station") == "Press")
    assert press_visit.get_column("blocked_time").to_list() == [press_blocked]
    assert result.summary.to_dicts()[0]["completed"] == 3


def test_blocking_holds_upstream_machine_until_downstream_admission():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    upstream = model.station(
        name="Upstream",
        capacity=1,
        service_time=1,
    )
    downstream = model.station(
        name="Downstream",
        capacity=1,
        service_time=3,
        buffer=0,
        external_overflow="reject",
    )
    model.route([source, upstream, downstream, model.exit])
    result = model.run(
        duration=8,
        drain=True,
    )
    visits = result.visits.filter(pl.col("station") == "Upstream")
    assert visits.get_column("service_start").to_list() == [0, 1, 4]
    assert visits.get_column("service_end").to_list() == [1, 2, 5]
    assert visits.get_column("departure_time").to_list() == [1, 4, 7]
    assert visits.get_column("blocked_time").to_list() == [0, 2, 2]
    assert result.customers.get_column("flow_time").to_list() == [4, 6, 8]
    metrics = result.stations.filter(pl.col("station") == "Upstream").to_dicts()[0]
    assert metrics["processing_utilization"] == 3 / 8
    assert metrics["blocking_fraction"] == 4 / 8
    assert metrics["utilization"] == 7 / 8
    assert metrics["mean_queue"] == 2 / 8
    assert result.summary.to_dicts()[0]["mean_wip"] == 2


def test_resume_after_repairs_has_an_independent_clock_calculation():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=5,
        time_to_failure=2,
        repair_time=3,
        failure_clock="busy",
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=3,
        drain=True,
    )
    # Five processing minutes require two three-minute repairs: 5 + 2*3 = 11.
    assert result.customers.get_column("exit_time").to_list() == [11]
    assert result.failures.get_column("failure_time").to_list() == [2, 7]
    assert result.failures.get_column("repair_end").to_list() == [5, 10]
    metrics = result.stations.to_dicts()[0]
    assert metrics["processing_utilization"] == pytest.approx(2 / 3)
    assert metrics["downtime_fraction"] == pytest.approx(1 / 3)
    assert metrics["utilization"] == 1


@pytest.mark.parametrize("clock,start,end", [("available", 5, 6), ("busy", 4, 5)])
def test_failure_clocks_differ_during_idle_time(clock, start, end):
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=10,
        first_arrival=4,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=1,
        time_to_failure=2,
        repair_time=3,
        failure_clock=clock,
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=5,
        drain=True,
    )
    assert result.visits.get_column("service_start").to_list() == [start]
    assert result.end_time == end


@pytest.mark.parametrize("staffing", [None, [(0, 0), (1, 1)]])
def test_failure_cycle_too_small_for_the_clock_raises(staffing):
    # Without a schedule the machine starts at 0, and each cycle moves the clock
    # by 1e-100, which would take about 3e100 cycles to reach 3. With a
    # schedule it starts at 1, where 1 + 1e-100 rounds to 1, so each cycle would
    # land on the same time forever.
    model = Model()
    source = model.source(
        name="Parts",
        interarrival=1,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=2,
        staffing=staffing,
        shift_end=None if staffing is None else "pause",
        time_to_failure=1e-100,
        repair_time=0,
        failure_clock="available",
    )
    model.route([source, station, model.exit])
    with pytest.raises(
        ValueError,
        match=(
            r"Time to failure 1e-100 and repair time 0\.0 at 'Machine', server 1, "
            r"are too small for the simulation clock to advance in a run of "
            r"duration 3"
        ),
    ):
        model.run(duration=3)


def test_tiny_lifetime_with_a_positive_repair_still_runs():
    # The first failure is at 0 + 1e-100. Each repair of 1 then moves the clock,
    # so later failures land at 1 + 1e-100 = 1 and 2 + 1e-100 = 2, and the
    # repair that would end at 3 is unfinished when the run stops.
    model = Model()
    source = model.source(
        name="Parts",
        interarrival=1,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=2,
        time_to_failure=1e-100,
        repair_time=1,
        failure_clock="available",
    )
    model.route([source, station, model.exit])
    failures = model.run(duration=3).failures
    assert failures.get_column("failure_time").to_list() == [1e-100, 1.0, 2.0]
    assert failures.get_column("repair_end").to_list() == [1.0, 2.0, None]


def test_failed_off_shift_server_can_finish_its_existing_job_after_repair():
    result = single_station(
        staffing=[(0, 1), (1, 0)],
        shift_end="finish",
        time_to_failure=2,
        repair_time=3,
        failure_clock="busy",
    ).run(duration=0.5, drain=True)
    assert result.customers.height == 1
    assert result.customers.get_column("exit_time").to_list() == [6]


def test_enabling_an_unbounded_buffer_preserves_basic_continuous_timing():
    basic = service_network()
    advanced = Model()
    source = advanced.source(
        name="Customers",
        interarrival=lambda rng: rng.exponential(scale=3),
    )
    check_in = advanced.station(
        name="Check-in",
        capacity=1,
        service_time=lambda rng: rng.uniform(1, 2),
    )
    service = advanced.station(
        name="Service",
        capacity=2,
        service_time=lambda rng: rng.exponential(scale=4),
        buffer=10000,
        external_overflow="wait",
    )
    advanced.route([source, check_in, service, advanced.exit])
    first = basic.run(duration=480)
    second = advanced.run(duration=480)
    columns = [
        "customer_id",
        "station",
        "arrival_time",
        "service_start",
        "service_end",
        "service_time",
    ]
    assert_frame_equal(
        first.visits.select(columns),
        second.visits.select(columns),
    )


def test_advanced_comparison_reports_rejections_separately():
    result = compare(
        scenarios={
            "No waiting room": single_station(
                buffer=0,
                external_overflow="reject",
            ),
            "Waiting room": single_station(
                buffer=3,
                external_overflow="reject",
            ),
        },
        duration=4,
        replications=3,
        drain=True,
    )
    assert result.intervals(metric="rejected").get_column("mean").to_list() == [2, 0]
    assert result.differences(metric="rejected").get_column("mean").to_list() == [-2]


@pytest.mark.parametrize("policy", ["finish", "pause"])
@pytest.mark.parametrize("clock", ["available", "busy"])
def test_combined_model_conserves_work_customer_time_and_capacity(policy, clock):
    from tests.models import combined_line

    model = combined_line(
        shift_end=policy,
        failure_clock=clock,
    )
    result = model.run(
        duration=180,
        warmup=15,
        drain=True,
    )
    totals = result.summary.to_dicts()[0]
    assert totals["arrivals"] == totals["completed"] + totals["rejected"]
    assert totals["remaining"] == 0
    for customer in result.customers.filter(pl.col("status") == "completed").to_dicts():
        identifier = customer["customer_id"]
        visits = result.visits.filter(pl.col("customer_id") == identifier)
        activities = result.activities.filter(pl.col("customer_id") == identifier)
        processing = sum(
            row["end"] - row["start"]
            for row in activities.to_dicts()
            if row["state"] == "processing"
        )
        paused = sum(
            row["end"] - row["start"]
            for row in activities.to_dicts()
            if row["state"] == "paused"
        )
        assert processing == pytest.approx(visits.get_column("service_time").sum())
        reconstructed = (
            processing + paused + customer["total_wait"] + customer["total_blocked"]
        )
        assert customer["flow_time"] == pytest.approx(reconstructed)
    for station in result.stations.to_dicts():
        name = station["station"]
        states = result.states.filter(pl.col("station") == name).to_dicts()
        for state in states:
            assert (
                state["busy"]
                == state["processing"] + state["paused"] + state["blocked"]
            )
            assert state["busy"] <= station["capacity"]
            assert state["processing"] <= state["available"]
            assert state["waiting"] <= model._nodes[name].buffer
        records = result.activities.filter(pl.col("station") == name).to_dicts()
        processing_area = sum(
            max(0, min(row["end"], 180) - max(row["start"], 15))
            for row in records
            if row["state"] == "processing"
        )
        assert station["processing_utilization"] == pytest.approx(
            processing_area / (station["capacity"] * 165)
        )


def test_servers_have_independent_reproducible_failure_streams():
    from tests.models import repairing_machine

    first = repairing_machine().run(duration=240)
    repeated = repairing_machine().run(duration=240)
    assert_frame_equal(first.failures, repeated.failures)
    one = (
        first.failures.filter(pl.col("server_id") == 1)
        .get_column("failure_time")
        .to_list()
    )
    two = (
        first.failures.filter(pl.col("server_id") == 2)
        .get_column("failure_time")
        .to_list()
    )
    assert one and two and one[0] != two[0]


@pytest.mark.parametrize(
    "points",
    [
        [],
        [(1, 1)],
        [(0, -1)],
        [(0, 1), (0, 2)],
        [(0, 1), (5, 1), (4, 2)],
    ],
)
def test_invalid_rate_schedules(points):
    with pytest.raises(ValueError):
        Model().source(
            name="Customers",
            rates=points,
        )


@pytest.mark.parametrize(
    "options",
    [
        {"staffing": [(0, 1)]},
        {"staffing": [(0, 2)], "shift_end": "finish"},
        {"buffer": 0},
        {"buffer": -1, "external_overflow": "wait"},
        {"time_to_failure": 1},
        {"time_to_failure": 1, "repair_time": 1},
        {"time_to_failure": 0, "repair_time": 1, "failure_clock": "busy"},
    ],
)
def test_advanced_rules_are_explicit_and_validated(options):
    with pytest.raises(ValueError):
        single_station(**options)
