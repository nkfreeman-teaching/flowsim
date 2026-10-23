"""Independent timing and accounting checks for the teaching interface."""

import heapq
import json
import zlib
from dataclasses import fields

import numpy as np
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import Model, results
from tests.models import branching_service, deterministic_queue, service_network


def test_hand_calculated_queue():
    result = deterministic_queue().run(duration=7)
    assert result.visits.get_column("arrival_time").to_list() == [0, 1, 2]
    assert result.visits.get_column("service_start").to_list() == [0, 2, 4]
    assert result.visits.get_column("service_end").to_list() == [2, 4, 6]
    assert result.visits.get_column("wait_time").to_list() == [0, 1, 2]
    station = result.stations.to_dicts()[0]
    assert station["mean_wait"] == 1
    assert station["mean_queue"] == pytest.approx(3 / 7)
    assert station["utilization"] == pytest.approx(6 / 7)
    assert station["max_queue"] == 1
    summary = result.summary.to_dicts()[0]
    assert summary["mean_flow_time"] == 3
    assert summary["mean_wip"] == pytest.approx(9 / 7)
    assert summary["arrivals"] == summary["completed"] == 3
    assert summary["remaining"] == 0


def test_parallel_servers_remove_this_queue():
    result = deterministic_queue(capacity=2).run(duration=7)
    assert result.visits.get_column("service_start").to_list() == [0, 1, 2]
    assert result.visits.get_column("service_end").to_list() == [2, 3, 4]
    station = result.stations.to_dicts()[0]
    assert station["mean_wait"] == station["mean_queue"] == 0
    assert station["utilization"] == pytest.approx(6 / 14)


def test_censoring_retains_waiting_and_in_service_customers():
    result = deterministic_queue().run(duration=3)
    assert result.customers.get_column("status").to_list() == [
        "completed",
        "in_service",
        "waiting",
    ]
    assert result.visits.get_column("service_end").to_list() == [2, None, None]
    assert result.visits.get_column("wait_time").to_list() == [0, 1, None]
    assert result.customers.get_column("flow_time").to_list() == [2, None, None]
    station = result.stations.to_dicts()[0]
    assert station["mean_wait"] == 0.5
    assert station["waiting_at_end"] == station["occupied_at_end"] == 1
    assert station["mean_queue"] == pytest.approx(2 / 3)
    assert station["utilization"] == 1
    assert result.summary.to_dicts()[0]["mean_wip"] == pytest.approx(5 / 3)


def test_run_limit_excludes_events_exactly_at_the_limit():
    result = deterministic_queue().run(duration=2)
    assert result.customers.height == 2
    assert result.visits.get_column("service_end").null_count() == 2
    assert result.summary.to_dicts()[0]["completed"] == 0
    assert result.stations.to_dicts()[0]["mean_queue"] == 0.5


def test_warmup_clips_intervals_crossing_the_boundary():
    result = deterministic_queue().run(
        duration=5.5,
        warmup=1.5,
    )
    station = result.stations.to_dicts()[0]
    assert station["arrivals"] == 1
    assert station["service_starts"] == station["service_completions"] == 2
    assert station["wait_observations"] == 1
    assert station["mean_wait"] == 2
    assert station["mean_queue"] == pytest.approx(2.5 / 4)
    assert station["utilization"] == 1
    assert station["occupied_at_end"] == 1
    summary = result.summary.to_dicts()[0]
    assert summary["measurement_arrivals"] == 1
    assert summary["measurement_completions"] == 2
    assert summary["cohort_completions"] == 0
    assert summary["mean_flow_time"] is None
    assert summary["mean_wip"] == pytest.approx(6.5 / 4)


def test_pre_warmup_customer_still_counts_at_end():
    result = deterministic_queue().run(
        duration=1.5,
        warmup=1.1,
    )
    station = result.stations.to_dicts()[0]
    assert station["arrivals"] == 0
    assert station["waiting_at_end"] == 1
    assert station["occupied_at_end"] == 1
    assert station["mean_wait"] is None
    assert station["mean_queue"] == 1
    assert station["utilization"] == 1


@pytest.mark.parametrize("capacity", [1, 2, 3])
def test_fcfs_timing_and_integrals_against_independent_heap(capacity):
    result = service_network(service_capacity=capacity).run(
        duration=480,
        warmup=37.5,
        seed=123,
    )
    for metrics in result.stations.to_dicts():
        station = metrics["station"]
        visits = result.visits.filter(pl.col("station") == station).to_dicts()
        free_times = [0.0] * metrics["capacity"]
        queue_area, busy_area = 0.0, 0.0
        for visit in visits:
            # An independent FCFS recursion assigns the earliest free server.
            start = max(visit["arrival_time"], heapq.heappop(free_times))
            end = start + visit["service_time"]
            heapq.heappush(free_times, end)
            if start < result.duration:
                assert visit["service_start"] == pytest.approx(start)
            else:
                assert visit["service_start"] is None
            if end < result.duration:
                assert visit["service_end"] == pytest.approx(end)
            else:
                assert visit["service_end"] is None
            queue_area += max(
                0,
                min(start, result.duration) - max(visit["arrival_time"], result.warmup),
            )
            busy_area += max(
                0,
                min(end, result.duration) - max(start, result.warmup),
            )
        window = result.duration - result.warmup
        assert metrics["mean_queue"] == pytest.approx(queue_area / window)
        assert metrics["utilization"] == pytest.approx(
            busy_area / (metrics["capacity"] * window)
        )
    for customer in result.customers.to_dicts():
        visits = result.visits.filter(
            pl.col("customer_id") == customer["customer_id"]
        ).to_dicts()
        for prior, following in zip(visits[:-1], visits[1:]):
            assert following["arrival_time"] == prior["service_end"]


def test_fresh_runs_are_reproducible_and_do_not_change_old_results():
    model = service_network()
    first = model.run(
        duration=480,
        seed=123,
    )
    second = model.run(
        duration=480,
        seed=123,
    )
    different = model.run(
        duration=480,
        seed=124,
    )
    for field in ["customers", "visits", "states", "stations", "summary"]:
        assert_frame_equal(getattr(first, field), getattr(second, field))
    assert not first.customers.equals(different.customers)


def test_seeded_output_tripwire():
    """Fail when a change moves the seeded output of a fixed model.

    This is an intentional tripwire with hand-copied literals. A refactor that
    should leave results alone must pass it unchanged. A change that is meant to
    move seeded results updates these literals in the same commit and says so.
    The relative tolerance allows only last-digit differences between platform
    math libraries.
    """
    result = service_network().run(
        duration=480,
        seed=42,
    )
    summary = result.summary.to_dicts()[0]
    assert result.customers.height == 167
    assert result.customers.get_column("arrival_time").head(3).to_list() == (
        pytest.approx(
            [1.295810755926124, 2.73955226490688, 5.5055600126933],
            rel=1e-12,
        )
    )
    assert summary["mean_total_wait"] == pytest.approx(
        6.9488085585975075,
        rel=1e-12,
    )
    assert summary["mean_flow_time"] == pytest.approx(
        13.12212491496525,
        rel=1e-12,
    )


def test_capacity_changes_preserve_arrival_stream():
    first = service_network(service_capacity=1).run(
        duration=480,
        seed=42,
    )
    second = service_network(service_capacity=3).run(
        duration=480,
        seed=42,
    )
    assert_frame_equal(
        first.customers.select("arrival_time"),
        second.customers.select("arrival_time"),
    )


def test_node_streams_depend_only_on_the_seed_and_the_node_name():
    # Each node's duration stream is seeded by SeedSequence(entropy=seed,
    # spawn_key=(crc32(name), 0)), so NumPy alone gives the expected draws, and
    # an unrelated source and station leave them unchanged.
    def stream(name: str) -> np.random.Generator:
        return np.random.default_rng(
            np.random.SeedSequence(
                entropy=7,
                spawn_key=(zlib.crc32(name.encode()), 0),
            )
        )

    arrivals = np.cumsum(stream("Customers").exponential(scale=5, size=40))
    arrivals = arrivals[arrivals < 100]
    services = stream("Service").exponential(scale=4, size=len(arrivals))

    def build(unrelated: bool) -> Model:
        model = Model()
        if unrelated:
            other = model.source(
                name="Other",
                interarrival=3,
            )
            aaa = model.station(
                name="Aaa",
                capacity=1,
                service_time=1,
            )
            model.route([other, aaa, model.exit])
        customers = model.source(
            name="Customers",
            interarrival=lambda rng: rng.exponential(scale=5),
        )
        service = model.station(
            name="Service",
            capacity=1,
            service_time=lambda rng: rng.exponential(scale=4),
        )
        model.route([customers, service, model.exit])
        return model

    for unrelated in [False, True]:
        result = build(unrelated).run(
            duration=100,
            seed=7,
        )
        customers = result.customers.filter(pl.col("source") == "Customers")
        visits = result.visits.filter(pl.col("station") == "Service")
        assert len(arrivals) > 10
        assert customers.get_column("arrival_time").to_list() == pytest.approx(
            arrivals.tolist(),
            rel=1e-12,
        )
        assert visits.get_column("service_time").to_list() == services.tolist()


def test_node_names_with_one_stream_key_raise():
    # "buckeroo" and "plumless" have the same CRC-32, 1306201125.
    model = Model()
    arrivals = model.source(
        name="plumless",
        interarrival=1,
    )
    service = model.station(
        name="buckeroo",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, service, model.exit])
    with pytest.raises(ValueError, match="'plumless' and 'buckeroo' share"):
        model.run(duration=5)


def test_stations_are_listed_in_definition_order():
    # The model defines Triage, Routine, Specialist, which is not alphabetical.
    result = branching_service().run(
        duration=60,
        seed=123,
    )
    order = ["Triage", "Routine", "Specialist"]
    assert result.stations.get_column("station").to_list() == order
    assert result.states.get_column("station").unique(
        maintain_order=True
    ).to_list() == (order)
    assert list(result.capacities) == order


def test_branch_routes_each_customer_to_one_service():
    result = branching_service().run(
        duration=2000,
        seed=123,
    )
    triage = result.visits.filter(pl.col("station") == "Triage")
    routed = result.visits.filter(pl.col("station").is_in(["Routine", "Specialist"]))
    finished_triage = triage.filter(pl.col("service_end").is_not_null())
    assert routed.height == finished_triage.height
    assert routed.get_column("customer_id").n_unique() == routed.height
    assert set(routed.get_column("customer_id")) == set(
        finished_triage.get_column("customer_id")
    )
    routine_share = routed.filter(pl.col("station") == "Routine").height / routed.height
    assert 0.60 < routine_share < 0.80


def test_two_sources_share_one_fifo_queue():
    model = Model()
    first = model.source(
        name="First",
        interarrival=3,
        first_arrival=0,
        limit=2,
    )
    second = model.source(
        name="Second",
        interarrival=3,
        first_arrival=0.5,
        limit=2,
    )
    station = model.station(
        name="Shared",
        capacity=1,
        service_time=2,
    )
    model.route([first, station, model.exit])
    model.route([second, station, model.exit])
    result = model.run(duration=9)
    assert result.visits.get_column("arrival_time").to_list() == [0, 0.5, 3, 3.5]
    assert result.visits.get_column("service_start").to_list() == [0, 2, 4, 6]
    assert result.visits.get_column("wait_time").to_list() == [0, 1.5, 1, 2.5]


def test_zero_service_has_no_time_occupancy():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    station = model.station(
        name="Instant",
        capacity=1,
        service_time=0,
    )
    model.route([arrivals, station, model.exit])
    result = model.run(duration=3)
    assert result.customers.get_column("flow_time").to_list() == [0, 0, 0]
    assert result.stations.to_dicts()[0]["utilization"] == 0


def test_empty_run_retains_numeric_schemas():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=10,
    )
    service = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, service, model.exit])
    result = model.run(duration=5)
    assert result.customers.height == result.visits.height == 0
    assert result.customers.schema["flow_time"] == pl.Float64
    assert result.visits.schema["wait_time"] == pl.Float64
    assert result.summary.to_dicts()[0]["mean_wip"] == 0
    assert result.stations.to_dicts()[0]["mean_wait"] is None
    assert result.stations.to_dicts()[0]["utilization"] == 0
    assert "No customer with that ID" in result.viewer()


@pytest.mark.parametrize("value", [0, -1, np.nan, np.inf, True, "2", np.array([1])])
def test_invalid_interarrival_samples_fail_with_station_context(value):
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=lambda rng: value,
    )
    service = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([source, service, model.exit])
    with pytest.raises(ValueError, match="Interarrival time at 'Customers'"):
        model.run(duration=5)


@pytest.mark.parametrize("value", [-1, np.inf, np.nan, True, np.array([1])])
def test_invalid_service_samples_fail_with_station_context(value):
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
    )
    service = model.station(
        name="Service",
        capacity=1,
        service_time=lambda rng: value,
    )
    model.route([source, service, model.exit])
    with pytest.raises(ValueError, match="Service time at 'Service'"):
        model.run(duration=5)


def test_graph_validation_and_route_edit_are_atomic():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
    )
    a = model.station(
        name="A",
        capacity=1,
        service_time=1,
    )
    b = model.station(
        name="B",
        capacity=1,
        service_time=1,
    )
    model.route([source, a])
    with pytest.raises(ValueError, match="unreachable|route to the exit"):
        model.run(duration=5)
    with pytest.raises(ValueError, match="acyclic"):
        model.route([a, b, a])
    assert model._graph.out_degree(a.name) == 0
    assert model._graph.out_degree(b.name) == 0
    with pytest.raises(ValueError, match="sum to one"):
        model.branch(a, {b: 0.5, model.exit: 0.4})
    assert model._graph.out_degree(a.name) == 0
    model.route([a, b, model.exit])
    other = Model()
    with pytest.raises(ValueError, match="created by this model"):
        model.route([b, other.exit])


@pytest.mark.parametrize("capacity", [0, -1, 1.5, True])
def test_invalid_capacities(capacity):
    with pytest.raises(ValueError, match="capacity"):
        Model().station(
            name="Service",
            capacity=capacity,
            service_time=1,
        )


def test_invalid_duration_warmup_and_replications():
    model = deterministic_queue()
    with pytest.raises(ValueError, match="Run duration"):
        model.run(duration=0)
    with pytest.raises(ValueError, match="shorter"):
        model.run(
            duration=3,
            warmup=3,
        )
    with pytest.raises(ValueError, match="Replications"):
        model.experiment(
            duration=7,
            replications=1,
        )


def test_export_round_trip_preserves_missing_values(tmp_path):
    result = deterministic_queue().run(duration=3)
    result.export(tmp_path)
    customers = pl.read_csv(
        source=tmp_path / "customers.csv",
        schema_overrides=result.customers.schema,
    )
    visits = pl.read_csv(
        source=tmp_path / "visits.csv",
        schema_overrides=result.visits.schema,
    )
    assert_frame_equal(customers, result.customers)
    assert_frame_equal(visits, result.visits)
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["duration"] == 3
    assert metadata["time_unit"] == "minutes"
    assert metadata["state_window"] == "[warmup, duration)"


def test_replication_intervals_use_run_means():
    trial = service_network().experiment(
        duration=240,
        replications=5,
        seed=42,
    )
    repeated = service_network().experiment(
        duration=240,
        replications=5,
        seed=42,
    )
    assert len({run.seed for run in trial.runs}) == 5
    assert_frame_equal(trial.stations, repeated.stations)
    interval = trial.intervals().filter(pl.col("station") == "Service").to_dicts()[0]
    means = (
        trial.stations.filter(pl.col("station") == "Service")
        .get_column("mean_wait")
        .to_numpy()
    )
    assert interval["mean"] == pytest.approx(means.mean())
    # t(4) at 97.5% is 2.776445105. This is independent of the producing code.
    half_width = 2.776445105 * np.std(means, ddof=1) / np.sqrt(5)
    assert interval["lower"] == pytest.approx(means.mean() - half_width)
    assert interval["upper"] == pytest.approx(means.mean() + half_width)
    assert interval["observed_runs"] == 5


def test_replications_report_missing_estimates():
    trial = deterministic_queue().experiment(
        duration=0.1,
        replications=3,
        warmup=0.05,
    )
    interval = trial.intervals().to_dicts()[0]
    assert interval["observed_runs"] == 0
    assert interval["mean"] is interval["lower"] is interval["upper"] is None


def test_station_intervals_without_stations_keep_their_columns():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
    )
    model.route([source, model.exit])
    intervals = model.experiment(
        duration=5,
        replications=2,
    ).intervals("mean_wait")
    assert intervals.height == 0
    assert intervals.schema == {
        "station": pl.String,
        "metric": pl.String,
        "runs": pl.Int64,
        "observed_runs": pl.Int64,
        "mean": pl.Float64,
        "lower": pl.Float64,
        "upper": pl.Float64,
        "confidence": pl.Float64,
    }


def test_viewer_escapes_model_text_and_plots_are_not_notebook_objects():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
    )
    name = "</script><script>window.bad=true</script>"
    service = model.station(
        name=name,
        capacity=1,
        service_time=1,
    )
    model.route([source, service, model.exit])
    result = model.run(duration=3)
    viewer = result.viewer()
    assert name not in viewer
    assert "\\u003c/script>" in viewer
    assert len(result.queue_plot().data) == 2
    assert len(result.customer_plot(1).data) == 5
    with pytest.raises(ValueError, match="does not exist"):
        result.customer_plot(99)


def test_completions_precede_arrivals_at_equal_times():
    # Arrivals at 0, 2, 4, 6, 8 each need 2 minutes. Each server release at
    # 2, 4, 6, 8 happens before the arrival at the same instant, so a station
    # with no waiting room serves everyone.
    model = Model()
    arrivals = model.source(
        name="Parts",
        interarrival=2,
        first_arrival=0,
        limit=5,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=2,
        buffer=0,
        external_overflow="reject",
    )
    model.route([arrivals, station, model.exit])
    customers = model.run(duration=100).customers
    assert customers.get_column("status").to_list() == ["completed"] * 5
    assert customers.get_column("exit_time").to_list() == [2, 4, 6, 8, 10]


def test_transfers_join_a_shared_queue_before_simultaneous_arrivals():
    # Direct arrivals at 0, 1, 2, 3 and a transfer from upstream at 3 share one
    # server with 2-minute service. The transfer joins first at time 3.
    model = Model()
    direct = model.source(
        name="Direct",
        interarrival=1,
        first_arrival=0,
        limit=4,
    )
    routed = model.source(
        name="Routed",
        interarrival=100,
        first_arrival=0,
        limit=1,
    )
    upstream = model.station(
        name="Upstream",
        capacity=1,
        service_time=3,
    )
    shared = model.station(
        name="Shared",
        capacity=1,
        service_time=2,
    )
    model.route([direct, shared])
    model.route([routed, upstream, shared, model.exit])
    visits = (
        model.run(duration=100)
        .visits.filter(pl.col("station") == "Shared")
        .sort("service_start")
    )
    assert visits.get_column("source").to_list() == [
        "Direct",
        "Direct",
        "Direct",
        "Routed",
        "Direct",
    ]
    assert visits.get_column("service_start").to_list() == [0, 2, 4, 6, 8]


def test_every_station_records_server_identity():
    # Two servers: customer 1 uses server 1 from 0 to 2, customer 2 uses
    # server 2 from 1 to 3, and customer 3 takes server 1 when it frees at 2.
    visits = deterministic_queue(capacity=2).run(duration=7).visits
    assert visits.get_column("server_id").to_list() == [1, 2, 1]


@pytest.mark.parametrize("first_arrival", [0, 1])
def test_interarrival_too_small_for_the_clock_raises(first_arrival):
    # From 1, 1 + 1e-100 rounds to 1. From 0, arrivals creep forward by 1e-100
    # and would need about 2e100 of them to reach the duration of 2.
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1e-100,
        first_arrival=first_arrival,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, station, model.exit])
    with pytest.raises(
        ValueError,
        match=(
            r"Interarrival time 1e-100 at 'Customers' is too small for the "
            r"simulation clock to advance in a run of duration 2"
        ),
    ):
        model.run(duration=2)


def test_activities_omit_phases_with_no_duration():
    activities = deterministic_queue().run(duration=7).activities
    assert activities.get_column("state").to_list() == ["processing"] * 3
    assert (activities.get_column("end") > activities.get_column("start")).all()


def test_disabled_source_never_samples():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=lambda rng: 0,
        limit=0,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, station, model.exit])
    assert model.run(duration=5).customers.height == 0


@pytest.mark.parametrize(
    ("record", "schema"),
    [
        (results._Customer, results.CUSTOMER_SCHEMA),
        (results._Visit, results.VISIT_SCHEMA),
        (results._State, results.STATE_SCHEMA),
        (results._Activity, results.ACTIVITY_SCHEMA),
        (results._Failure, results.FAILURE_SCHEMA),
    ],
)
def test_record_fields_equal_schema_columns(record, schema):
    assert [field.name for field in fields(record)] == list(schema)


def test_records_reject_misspelled_fields():
    customer = results._Customer(
        customer_id=1,
        source="Customers",
        arrival_time=0.0,
    )
    with pytest.raises(AttributeError):
        customer.exit_tme = 2.0


def test_record_tables_read_columns_by_name():
    # By hand, each value belongs in the column of the same name, even though
    # wait_time comes after server_id and blocked_time in the schema.
    visit = results._Visit(
        customer_id=4,
        source="Customers",
        station="Service",
        arrival_time=1.0,
        service_start=3.0,
        service_end=5.5,
        departure_time=6.0,
        server_id=2,
        blocked_time=0.5,
        wait_time=2.0,
        service_time=2.5,
    )
    row = results._frame([visit], results.VISIT_SCHEMA).row(0, named=True)
    assert row == {
        "customer_id": 4,
        "source": "Customers",
        "station": "Service",
        "arrival_time": 1.0,
        "service_start": 3.0,
        "service_end": 5.5,
        "departure_time": 6.0,
        "server_id": 2,
        "blocked_time": 0.5,
        "wait_time": 2.0,
        "service_time": 2.5,
    }


def test_statuses_and_phases_use_their_enumerations():
    # By hand: arrivals at 0, 1, 2, and 3. Customer 1 uses Prep from 0 to 1 and
    # starts Finish at 1. Customer 2 uses Prep from 1 to 2, then stays blocked
    # because Finish is busy until 4 and has no buffer. Customers 3 and 4 wait.
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=4,
    )
    prep = model.station(
        name="Prep",
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
    model.route([arrivals, prep, finish, model.exit])
    result = model.run(duration=3.5)
    assert result.customers.get_column("status").to_list() == [
        results.Status.IN_SERVICE,
        results.Status.BLOCKED,
        results.Status.WAITING,
        results.Status.WAITING,
    ]
    assert result.activities.rows() == [
        (1, "Prep", 1, results.Phase.PROCESSING, 0.0, 1.0),
        (1, "Finish", 1, results.Phase.PROCESSING, 1.0, None),
        (2, "Prep", 1, results.Phase.PROCESSING, 1.0, 2.0),
        (2, "Prep", 1, results.Phase.BLOCKED, 2.0, None),
    ]
