"""Hand-derived closing rules and independently calculated paired contrasts."""

import json
import tomllib
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import Comparison, Experiment, Model, compare
from tests.models import (
    beer_chain,
    deterministic_queue,
    embedded_json,
    service_network,
)


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
    assert result.settings.end_time == 3
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
    assert result.settings.end_time == 3
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
    assert len(result.plot_queue().layout.shapes) == 1


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
        assert first.settings.seed == second.settings.seed
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


@pytest.fixture(scope="module")
def drained_comparison() -> Comparison:
    """One and two servers on deterministic_queue, drained after closing at 3.

    Only tests that read it share it. A test that edits a run builds its own.
    """
    return compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )


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
    first = second.runs[0]
    first.settings = replace(
        first.settings,
        seed=first.settings.seed + 1,
    )
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


def test_comparison_exports_run_counts_and_replication_definitions(
    drained_comparison,
    tmp_path,
):
    result = drained_comparison
    result.export(tmp_path)
    assert pl.read_csv(tmp_path / "runs.csv").height == 6
    assert pl.read_csv(tmp_path / "intervals.csv").height == 2
    assert pl.read_csv(tmp_path / "differences.csv").height == 1
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["drain"] is True
    assert len(metadata["replication_seeds"]) == 3
    assert metadata["baseline"] == "One"
    assert "Scenario comparison" in result.viewer().html


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
    page = result.viewer(confidence=0.9).html
    data = embedded_json(page, "dashboard-data")
    assert data["confidence_text"] == "90%"
    # A placeholder-like scenario name reaches the page unchanged.
    assert data["scenarios"] == ["One", "__UNITS__ & co"]
    entry = next(item for item in data["metrics"] if item["name"] == "mean_total_wait")
    assert entry["units"] == "minutes"
    (view,) = entry["views"]
    assert [
        (row["scenario"], row["mean"], row["lower"], row["upper"], row["observed_runs"])
        for row in view["intervals"]
    ] == [("One", 1.0, 1.0, 1.0, 3), ("__UNITS__ & co", 0.0, 0.0, 0.0, 3)]
    assert data["initial"]["baseline"] == "One"
    for placeholder in [
        "STYLE",
        "PLOTLY_JS",
        "TEMPLATE_JSON",
        "SERVICE_RUN",
        "SUPPLY_RUN",
        "HEADING",
        "DASHBOARD_JSON",
        "RUN_DATA",
    ]:
        assert f"__{placeholder}__" not in page
    # The page templates ship with the package.
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text()
    )
    shipped = pyproject["tool"]["setuptools"]["package-data"]["flowsim"]
    package = Path(__file__).parents[1] / "flowsim"
    assert sorted([*(path.name for path in package.glob("*.html")), "page.css"]) == (
        sorted(name for name in shipped if name.endswith((".html", ".css")))
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


def test_experiment_and_comparison_intervals_share_defaults(drained_comparison):
    # One server gives waits 0, 1, and 2 in every replication, and two servers
    # give 0, 0, and 0. Both default to the system's mean_total_wait, and a
    # station metric without station= covers every station.
    trial = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    assert trial.intervals().select(
        "metric",
        "station",
        "mean",
    ).rows() == [("mean_total_wait", None, 1.0)]
    station = trial.intervals("mean_wait")
    assert station.select(
        "metric",
        "station",
        "mean",
    ).rows() == [("mean_wait", "Service", 1.0)]
    result = drained_comparison
    system = result.intervals()
    assert system.select(
        "scenario",
        "metric",
        "station",
        "mean",
    ).rows() == [
        ("One", "mean_total_wait", None, 1.0),
        ("Two", "mean_total_wait", None, 0.0),
    ]
    assert result.intervals(metric="mean_wait").select(
        "scenario",
        "station",
        "mean",
    ).rows() == [("One", "Service", 1.0), ("Two", "Service", 0.0)]


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
    page = result.viewer(baseline="Two").html
    assert embedded_json(page, "dashboard-data")["initial"]["baseline"] == "Two"
    # Tables built for export follow edits to the underlying runs.
    for run in result.experiments["One"].runs:
        run.summary = run.summary.with_columns(pl.lit(99.0).alias("mean_total_wait"))
    assert set(
        result.summary.filter(pl.col("scenario") == "One")["mean_total_wait"]
    ) == {99.0}


def test_comparison_viewer_and_plot_name_the_chosen_station():
    result = compare(
        scenarios={
            "One server": service_network(service_capacity=1),
            "Two servers": service_network(service_capacity=2),
        },
        duration=60,
        replications=3,
        seed=1,
        drain=True,
    )
    for chosen, other in [("Check-in", "Service"), ("Service", "Check-in")]:
        document = result.viewer(
            metric="mean_wait",
            station=chosen,
        ).html
        data = embedded_json(document, "dashboard-data")
        assert data["initial"]["location"] == chosen
        entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
        assert [view["title"] for view in entry["views"]] == [
            "Mean station waiting time at Check-in",
            "Mean station waiting time at Service",
        ]
        plot = result.plot(
            metric="mean_wait",
            station=chosen,
        )
        assert chosen in plot.layout.xaxis.title.text
        assert other not in plot.layout.xaxis.title.text
        assert chosen in plot.data[0].hovertemplate


def test_comparison_viewer_prints_a_fractional_confidence_level(drained_comparison):
    result = drained_comparison
    # The page reads its confidence label from its data, so check that text
    # rather than any "95%" elsewhere in the page.
    for level, text in [(0.975, "97.5%"), (0.95, "95%"), (0.9, "90%")]:
        page = result.viewer(confidence=level).html
        assert embedded_json(page, "dashboard-data")["confidence_text"] == text


def test_export_removes_stale_flowsim_files_and_keeps_other_files(tmp_path):
    (tmp_path / "notes.txt").write_text("keep")
    (tmp_path / "sub").mkdir()
    beer_chain().run(duration=10).export(tmp_path)
    assert (tmp_path / "inventory.csv").exists()
    service_network().run(duration=30).export(tmp_path)
    for name in ["inventory.csv", "shipments.csv", "stock_points.csv"]:
        assert not (tmp_path / name).exists()
    assert (tmp_path / "customers.csv").exists()
    assert (tmp_path / "notes.txt").read_text() == "keep"
    assert (tmp_path / "sub").is_dir()


def test_export_refuses_folder_with_files_flowsim_did_not_write(tmp_path):
    (tmp_path / "customers.csv").write_text("mine")
    (tmp_path / "notes.txt").write_text("keep")
    with pytest.raises(ValueError, match="customers.csv"):
        deterministic_queue().run(duration=7).export(tmp_path)
    assert (tmp_path / "customers.csv").read_text() == "mine"
    assert (tmp_path / "notes.txt").read_text() == "keep"


def test_an_interrupted_export_can_be_retried(tmp_path, monkeypatch):
    # Metadata is written before the tables, so a failure while writing the
    # tables leaves a folder that a retry recognizes as FlowSim's.
    result = deterministic_queue().run(duration=7)
    original = pl.DataFrame.write_csv
    calls = []

    def fail(self, *args, **kwargs):
        # The first table is written, then the disk fills.
        calls.append(None)
        if len(calls) > 1:
            raise OSError("disk full")
        original(self, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "write_csv", fail)
    with pytest.raises(OSError, match="disk full"):
        result.export(tmp_path)
    monkeypatch.setattr(pl.DataFrame, "write_csv", original)
    result.export(tmp_path)
    assert (tmp_path / "customers.csv").is_file()
    assert not list(tmp_path.glob("*.partial"))


def test_results_export_removes_stale_comparison_files(tmp_path):
    result = compare(
        scenarios={
            "One": deterministic_queue(),
            "Two": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=2,
        drain=True,
    )
    result.export(tmp_path)
    for name in ["runs.csv", "intervals.csv", "differences.csv"]:
        assert (tmp_path / name).exists()
    deterministic_queue().run(duration=3).export(tmp_path)
    for name in ["runs.csv", "intervals.csv", "differences.csv"]:
        assert not (tmp_path / name).exists()
    assert (tmp_path / "summary.csv").exists()


def test_experiment_pools_separately_built_named_distribution_models():
    from flowsim import exponential

    def make() -> Model:
        model = Model()
        arrivals = model.source(
            name="Arrivals",
            interarrival=exponential(mean=3),
        )
        desk = model.station(
            name="Desk",
            capacity=1,
            service_time=exponential(mean=2),
        )
        model.route([arrivals, desk, model.exit])
        return model

    experiment = Experiment([make().run(60, seed=1), make().run(60, seed=2)])
    assert len(experiment.runs) == 2


def test_comparison_validates_scenario_names_and_matching_seeds():
    one = deterministic_queue().experiment(
        duration=7,
        replications=2,
        seed=1,
    )
    two = deterministic_queue(capacity=2).experiment(
        duration=7,
        replications=2,
        seed=2,
    )
    with pytest.raises(ValueError, match="nonempty strings"):
        Comparison({"": one, "Two": two})
    with pytest.raises(ValueError, match="identical replication seeds"):
        Comparison({"One": one, "Two": two})


def test_single_observed_run_interval_has_mean_and_missing_bounds():
    from flowsim.reporting import interval_estimate

    estimate = interval_estimate([4.25], confidence=0.95)
    assert estimate["observed_runs"] == 1
    assert estimate["mean"] == 4.25
    assert estimate["lower"] is None
    assert estimate["upper"] is None


def test_explain_rejects_non_string_and_shifted_rejects_bad_spec_keys():
    from flowsim import explain, shifted

    with pytest.raises(ValueError, match="must be a string"):
        explain(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="shifted"):
        shifted({"name": "exponential", "bad": 1}, by=1)
