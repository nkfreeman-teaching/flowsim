"""Hand-derived closing rules and independently calculated paired contrasts."""

import json
import tomllib
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import Comparison, Experiment, Model, compare
from tests.models import deterministic_queue, service_network


def test_drain_finishes_the_arrival_cohort_and_preserves_opening_metrics():
    model = deterministic_queue()
    stopped = model.run(duration=3)
    drained = model.run(
        duration=3,
        drain=True,
    )
    assert drained.visits.get_column("service_end").to_list() == [2, 4, 6]
    assert drained.visits.get_column("wait_time").to_list() == [0, 1, 2]
    assert drained.customers.get_column("flow_time").to_list() == [2, 3, 4]
    summary = drained.summary.to_dicts()[0]
    assert summary["arrivals"] == summary["completed"] == 3
    assert summary["remaining"] == 0
    assert summary["completed_at_close"] == 1
    assert summary["remaining_at_close"] == summary["after_close_completions"] == 2
    assert summary["end_time"] == 6
    assert summary["overtime"] == 3
    assert summary["mean_total_wait"] == 1
    assert summary["mean_flow_time"] == 3
    # Closing at 3 excludes the later completions and clips all presence at 3.
    assert summary["throughput"] == pytest.approx(1 / 3)
    assert summary["mean_wip"] == pytest.approx(5 / 3)
    for metric in ["throughput", "mean_wip", "measurement_completions"]:
        assert summary[metric] == stopped.summary.to_dicts()[0][metric]
    station = drained.stations.to_dicts()[0]
    assert station["waiting_at_close"] == station["occupied_at_close"] == 1
    assert station["waiting_at_end"] == station["occupied_at_end"] == 0
    for metric in ["mean_queue", "max_queue", "utilization"]:
        assert station[metric] == stopped.stations.to_dicts()[0][metric]


def test_completions_exactly_at_closing_are_processed_only_when_draining():
    result = deterministic_queue().run(
        duration=2,
        drain=True,
    )
    assert result.customers.height == 2
    assert result.customers.get_column("exit_time").to_list() == [2, 4]
    summary = result.summary.to_dicts()[0]
    assert summary["completed_at_close"] == summary["measurement_completions"] == 0
    assert summary["remaining_at_close"] == summary["after_close_completions"] == 2
    station = result.stations.to_dicts()[0]
    assert station["waiting_at_close"] == station["occupied_at_close"] == 1
    assert station["mean_queue"] == 0.5
    assert station["utilization"] == 1


def test_drained_downstream_visits_after_closing_have_complete_waits():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    first = model.station(
        name="First",
        capacity=1,
        service_time=3,
    )
    second = model.station(
        name="Second",
        capacity=1,
        service_time=4,
    )
    model.route([arrivals, first, second, model.exit])
    result = model.run(
        duration=2.5,
        drain=True,
    )
    second_visits = result.visits.filter(pl.col("station") == "Second")
    assert second_visits.get_column("arrival_time").to_list() == [3, 6, 9]
    assert second_visits.get_column("service_start").to_list() == [3, 7, 11]
    assert second_visits.get_column("service_end").to_list() == [7, 11, 15]
    assert second_visits.get_column("wait_time").to_list() == [0, 1, 2]
    metrics = result.stations.filter(pl.col("station") == "Second").to_dicts()[0]
    assert metrics["arrivals"] == metrics["service_starts"] == 0
    assert metrics["wait_arrivals"] == metrics["wait_observations"] == 3
    assert metrics["mean_wait"] == 1
    assert metrics["mean_queue"] == metrics["utilization"] == 0
    assert result.summary.to_dicts()[0]["overtime"] == 12.5


def test_drain_does_not_advance_to_a_future_source_timeout():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1000,
        first_arrival=0,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([source, station, model.exit])
    result = model.run(
        duration=3,
        drain=True,
    )
    assert result.customers.height == 1
    assert result.end_time == 3
    assert result.summary.to_dicts()[0]["overtime"] == 0


def test_empty_arrival_day_has_no_overtime_and_missing_average():
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=10,
    )
    model.route([source, model.exit])
    result = model.run(
        duration=3,
        drain=True,
    )
    assert result.end_time == 3
    assert result.customers.height == 0
    assert result.summary.to_dicts()[0]["mean_flow_time"] is None
    assert result.summary.to_dicts()[0]["mean_wip"] == 0


@pytest.mark.parametrize("warmup", [0, 1.5])
def test_draining_preserves_warmup_state_integrals(warmup):
    model = deterministic_queue()
    stopped = model.run(
        duration=3,
        warmup=warmup,
    )
    drained = model.run(
        duration=3,
        warmup=warmup,
        drain=True,
    )
    assert_frame_equal(
        stopped.stations.select("mean_queue", "utilization"),
        drained.stations.select("mean_queue", "utilization"),
    )
    assert_frame_equal(
        stopped.summary.select("mean_wip", "throughput"),
        drained.summary.select("mean_wip", "throughput"),
    )
    if warmup == 1.5:
        assert drained.summary.to_dicts()[0]["mean_flow_time"] == 4
        assert drained.stations.to_dicts()[0]["mean_wait"] == 2


def test_drain_option_must_be_boolean():
    with pytest.raises(ValueError, match="True or False"):
        deterministic_queue().run(
            duration=3,
            drain="yes",
        )


def test_drain_metadata_and_state_trace_extend_through_service(tmp_path):
    result = deterministic_queue().run(
        duration=3,
        drain=True,
    )
    result.export(tmp_path)
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["duration"] == 3
    assert metadata["end_time"] == 6
    assert metadata["drain"] is True
    assert result.states.get_column("time").max() == 6
    assert result.stations.to_dicts()[0]["service_completions"] == 1
    assert len(result.queue_plot().layout.shapes) == 1


def test_deterministic_scenario_differences_have_exact_zero_width():
    result = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    interval = result.differences().to_dicts()[0]
    assert interval["mean"] == interval["lower"] == interval["upper"] == -1
    assert interval["observed_runs"] == 3
    overtime = result.differences(metric="overtime").to_dicts()[0]
    assert overtime["mean"] == -2
    throughput = result.differences(metric="throughput").to_dicts()[0]
    assert throughput["mean"] == 0
    station = result.differences(
        metric="mean_wait",
        station="Service",
    ).to_dicts()[0]
    assert station["mean"] == -1


def test_paired_interval_uses_replication_differences_not_two_standard_errors():
    result = compare(
        scenarios={
            "One server": service_network(service_capacity=1),
            "Two servers": service_network(service_capacity=2),
        },
        duration=240,
        replications=5,
        seed=123,
        drain=True,
    )
    one = result.experiments["One server"].runs
    two = result.experiments["Two servers"].runs
    differences = []
    for first, second in zip(one, two):
        assert first.seed == second.seed
        assert_frame_equal(
            first.customers.select("arrival_time"),
            second.customers.select("arrival_time"),
        )
        differences.append(
            second.summary.to_dicts()[0]["mean_total_wait"]
            - first.summary.to_dicts()[0]["mean_total_wait"]
        )
    # Independent arithmetic using the tabulated 97.5% t(4) value.
    mean = sum(differences) / 5
    variance = sum((value - mean) ** 2 for value in differences) / 4
    half_width = 2.776445105 * (variance / 5) ** 0.5
    interval = result.differences().to_dicts()[0]
    assert interval["mean"] == pytest.approx(mean)
    assert interval["lower"] == pytest.approx(mean - half_width)
    assert interval["upper"] == pytest.approx(mean + half_width)
    assert interval["observed_runs"] == 5


def test_missing_outcomes_exclude_matched_pairs_and_report_the_count():
    result = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=5,
        drain=True,
    )
    # Known run-level estimates check pair alignment independently of simulation.
    for name, values in [
        ("One server", [1, None, 3, 4, 5]),
        ("Two servers", [2, 20, None, 8, 10]),
    ]:
        for run, value in zip(result.experiments[name].runs, values):
            run.summary = run.summary.with_columns(
                pl.Series(
                    name="mean_total_wait",
                    values=[value],
                    dtype=pl.Float64,
                )
            )
    intervals = result.intervals()
    assert intervals.get_column("observed_runs").to_list() == [4, 4]
    differences = result.differences().to_dicts()[0]
    assert differences["observed_runs"] == 3
    assert differences["mean"] == pytest.approx((1 + 4 + 5) / 3)


def test_comparison_rejects_missing_duplicate_and_unpaired_replications():
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    second = result.experiments["Two"]
    # A hand-edited run table without exactly one row would otherwise
    # misalign the paired replications.
    run = second.runs[1]
    original = run.summary
    run.summary = original.clear()
    with pytest.raises(ValueError, match="missing or duplicate"):
        result.differences()
    run.summary = pl.concat([original, original])
    with pytest.raises(ValueError, match="missing or duplicate"):
        result.intervals()
    run.summary = original
    second.runs[0].seed += 1
    with pytest.raises(ValueError, match="identical replication seeds"):
        result.differences()


def test_comparison_rejects_incomparable_units_and_unknown_fields():
    with pytest.raises(ValueError, match="at least two"):
        compare(
            scenarios={"One": deterministic_queue()},
            duration=3,
        )
    other = deterministic_queue()
    other.time_unit = "hours"
    with pytest.raises(ValueError, match="same time unit"):
        compare(
            scenarios={"One": deterministic_queue(), "Other": other},
            duration=3,
        )
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=2,
    )
    with pytest.raises(ValueError, match="Unknown baseline"):
        result.differences(baseline="Missing")
    with pytest.raises(ValueError, match="system metric"):
        result.intervals(metric="bad")
    with pytest.raises(
        ValueError, match="Scenario 'One': Station 'Missing' is missing"
    ):
        result.intervals(
            metric="mean_wait",
            station="Missing",
        )
    with pytest.raises(ValueError, match="below one"):
        result.intervals(confidence=1)


def test_comparison_exports_run_counts_and_replication_definitions(tmp_path):
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    result.export(tmp_path)
    assert pl.read_csv(tmp_path / "runs.csv").height == 6
    assert pl.read_csv(tmp_path / "intervals.csv").height == 2
    assert pl.read_csv(tmp_path / "differences.csv").height == 1
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["drain"] is True
    assert len(metadata["replication_seeds"]) == 3
    assert metadata["baseline"] == "One"
    assert "Scenario comparison" in result.viewer()


def test_comparison_page_fills_its_template_once():
    # One server gives waits 0, 1, and 2 (mean 1), and two servers give 0, 0,
    # and 0, so every replication has the same mean and a zero-width interval.
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "__UNITS__ & co": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    page = result.viewer(confidence=0.9)
    assert "Intervals show 90% Student t uncertainty" in page
    assert "<th>Mean (minutes)</th>" in page
    assert (
        "<tbody><tr><td>One</td><td>1.000</td><td>1.000</td><td>1.000</td><td>3</td></tr>"
        "<tr><td>__UNITS__ &amp; co</td><td>0.000</td><td>0.000</td><td>0.000</td>"
        "<td>3</td></tr></tbody>"
    ) in page
    assert "<h2>Difference from One</h2>" in page
    for placeholder in ["__TEXT__", "__TITLE__", "__MEANS__", "__CHANGES__"]:
        assert placeholder not in page
    # The page template ships with the package, as viewer.html does.
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text()
    )
    assert (
        "comparison.html" in pyproject["tool"]["setuptools"]["package-data"]["flowsim"]
    )


def test_drain_continues_when_staffing_returns_exactly_at_closing():
    # Arrivals at 0 and 10 wait for the first server at 20, the closing time.
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=10,
        first_arrival=0,
        limit=2,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=5,
        staffing=[(0, 0), (20, 1)],
        shift_end="finish",
    )
    model.route([arrivals, station, model.exit])
    result = model.run(
        duration=20,
        drain=True,
    )
    assert result.customers.get_column("exit_time").to_list() == [25, 30]


def test_drain_accepts_work_that_finishes_as_the_last_shift_ends():
    # Service from 0 to 3 finishes at the same instant the only shift ends.
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=100,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=3,
        staffing=[(0, 1), (3, 0)],
        shift_end="pause",
    )
    model.route([arrivals, station, model.exit])
    result = model.run(
        duration=1,
        drain=True,
    )
    assert result.customers.get_column("exit_time").to_list() == [3]


def test_experiments_reject_repeated_or_mismatched_runs():
    run = service_network().run(
        duration=60,
        seed=1,
    )
    with pytest.raises(ValueError, match="distinct seeds"):
        Experiment([run, run, run])
    longer = service_network().run(
        duration=90,
        seed=2,
    )
    with pytest.raises(ValueError, match="same duration"):
        Experiment([run, longer])
    # Models that differ only in capacity are different models.
    with pytest.raises(ValueError, match="same model"):
        Experiment(
            [
                deterministic_queue().run(
                    duration=3,
                    seed=1,
                ),
                deterministic_queue(capacity=2).run(
                    duration=3,
                    seed=2,
                ),
            ]
        )
    one = deterministic_queue().experiment(
        duration=3,
        replications=2,
    )
    other = deterministic_queue().experiment(
        duration=4,
        replications=2,
    )
    with pytest.raises(ValueError, match="same duration"):
        Comparison({"One": one, "Other": other})


def test_experiments_reject_runs_of_different_models():
    def queue(service_time: float) -> Model:
        model = Model()
        arrivals = model.source(
            name="Customers",
            interarrival=1,
            first_arrival=0,
            limit=3,
        )
        station = model.station(
            name="Service",
            capacity=1,
            service_time=service_time,
        )
        model.route([arrivals, station, model.exit])
        return model

    fast = queue(1).run(
        duration=3,
        seed=1,
        drain=True,
    )
    slow = queue(9).run(
        duration=3,
        seed=2,
        drain=True,
    )
    # Arrivals at 0, 1, and 2 wait 0, 0, and 0 with one-minute service and 0, 8,
    # and 16 with nine-minute service. Pooling would report (0 + 8) / 2 = 4.
    assert fast.summary.get_column("mean_total_wait").to_list() == [0]
    assert slow.summary.get_column("mean_total_wait").to_list() == [8]
    with pytest.raises(ValueError, match="same model"):
        Experiment([fast, slow])
    # Separately built models with equal numeric settings still pool.
    twin = queue(1).run(
        duration=3,
        seed=2,
        drain=True,
    )
    pooled = Experiment([fast, twin]).intervals("mean_total_wait")
    assert pooled.get_column("mean").to_list() == [0]
    # Equal-looking lambdas from separate builds are different objects.
    with pytest.raises(ValueError, match="same model"):
        Experiment(
            [
                service_network().run(
                    duration=60,
                    seed=1,
                ),
                service_network().run(
                    duration=60,
                    seed=2,
                ),
            ]
        )
    model = service_network()
    Experiment(
        [
            model.run(
                duration=60,
                seed=1,
            ),
            model.run(
                duration=60,
                seed=2,
            ),
        ]
    )


def test_experiment_intervals_cover_system_and_named_station_metrics():
    trial = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    system = trial.intervals("mean_total_wait").to_dicts()
    # Waits are 0, 1, and 2 in every replication, so the mean is 1 exactly.
    assert system == [
        {
            "station": None,
            "metric": "mean_total_wait",
            "runs": 3,
            "observed_runs": 3,
            "mean": 1.0,
            "lower": 1.0,
            "upper": 1.0,
            "confidence": 0.95,
        }
    ]
    station = trial.intervals(
        metric="utilization",
        station="Service",
        confidence=0.9,
    )
    assert station.get_column("mean").to_list() == [pytest.approx(6 / 7)]
    with pytest.raises(ValueError, match="system metric"):
        trial.intervals("mean_total_wait", station="Service")


def test_comparison_outputs_accept_a_baseline_and_read_current_tables(tmp_path):
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    result.export(tmp_path, baseline="Two")
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["baseline"] == "Two"
    differences = pl.read_csv(tmp_path / "differences.csv")
    assert differences.get_column("scenario").to_list() == ["One"]
    assert differences.get_column("mean").to_list() == [1]
    assert "Difference from Two" in result.viewer(baseline="Two")
    # Tables built for export follow edits to the underlying runs.
    for run in result.experiments["One"].runs:
        run.summary = run.summary.with_columns(pl.lit(99.0).alias("mean_total_wait"))
    assert set(
        result.summary.filter(pl.col("scenario") == "One")["mean_total_wait"]
    ) == {99.0}
