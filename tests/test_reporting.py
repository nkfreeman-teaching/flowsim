"""Shared reporting, plots, viewers, exports, run reports, and settings."""

import inspect
import json
import re
import webbrowser
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from flowsim import (
    Comparison,
    Experiment,
    Model,
    builder,
    compare,
    plots,
    reporting,
)
from flowsim.catalog import STATION_METRICS, STOCK_POINT_METRICS, SYSTEM_METRICS
from flowsim.records import STATION_SCHEMA
from flowsim.results import Settings
from flowsim.viewer import Viewer
from tests.models import (
    beer_chain,
    deterministic_queue,
    one_stage_chain,
    queue_comparison,
    service_network,
)


@pytest.fixture(scope="module")
def experiment():
    return service_network(service_capacity=1).experiment(
        duration=60,
        replications=3,
        seed=1,
    )


@pytest.fixture(scope="module")
def comparison():
    return compare(
        scenarios={
            "One": service_network(service_capacity=1),
            "Two": service_network(service_capacity=2),
        },
        duration=60,
        replications=3,
        seed=1,
    )


def test_experiment_and_comparison_share_reporting_signatures():
    for name in ["intervals", "plot", "viewer", "export"]:
        shared = inspect.signature(getattr(Experiment, name)).parameters
        compared = inspect.signature(getattr(Comparison, name)).parameters
        for parameter in ["metric", "station", "stock_point", "confidence"]:
            assert shared[parameter].default == compared[parameter].default, name
            assert shared[parameter].kind == compared[parameter].kind, name
        assert shared["metric"].default == "mean_total_wait"
        assert "baseline" not in shared


@pytest.mark.parametrize(
    ("metric", "station"),
    [
        ("mean_total_wait", None),
        ("mean_wait", None),
        ("mean_wait", "Service"),
        ("utilization", "Check-in"),
    ],
)
def test_experiment_rows_equal_the_comparison_rows_of_the_same_scenario(
    experiment,
    comparison,
    metric,
    station,
):
    # Both run the one-server model from seed 1, so the runs are identical.
    alone = experiment.intervals(
        metric,
        station=station,
    )
    within = (
        comparison.intervals(
            metric,
            station=station,
        )
        .filter(pl.col("scenario") == "One")
        .drop("scenario")
    )
    assert_frame_equal(alone, within)
    expected = ["Check-in", "Service"] if station is None else [station]
    if metric == "mean_total_wait":
        expected = [None]
    assert alone.get_column("station").to_list() == expected
    assert set(alone.get_column("metric")) == {metric}


def test_comparison_station_metric_covers_every_station_in_each_scenario(comparison):
    intervals = comparison.intervals("mean_wait")
    assert intervals.select("scenario", "station").rows() == [
        ("One", "Check-in"),
        ("One", "Service"),
        ("Two", "Check-in"),
        ("Two", "Service"),
    ]
    differences = comparison.differences("mean_wait")
    assert differences.select("scenario", "baseline", "station").rows() == [
        ("Two", "One", "Check-in"),
        ("Two", "One", "Service"),
    ]
    # Each difference is the matched runs' station means subtracted.
    stations = comparison.stations.filter(pl.col("station") == "Service")
    one, two = (
        stations.filter(pl.col("scenario") == name)
        .sort("replication")
        .get_column("mean_wait")
        .to_numpy()
        for name in ["One", "Two"]
    )
    assert differences.get_column("mean").to_list()[1] == pytest.approx(
        (two - one).mean()
    )


def test_experiment_plot_draws_one_point_per_location(experiment):
    stations = experiment.plot("mean_wait")
    assert [list(trace.y) for trace in stations.data] == [["Check-in"], ["Service"]]
    assert [trace.meta for trace in stations.data] == ["Check-in", "Service"]
    assert stations.layout.yaxis.title.text == "Station"
    system = experiment.plot()
    assert len(system.data) == 1
    assert list(system.data[0].y) == ["System"]
    assert system.layout.xaxis.title.text == "Mean total waiting time (minutes)"
    single = experiment.plot(
        "utilization",
        station="Service",
    )
    assert "at Service" in single.layout.xaxis.title.text
    assert single.layout.xaxis.tickformat == ".0%"


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # 0 to 2 spans 2, padded by 0.1 at each end; the gap is skipped.
        ({None: [0.0, 2.0, None]}, [-0.1, 2.1]),
        # All zero spans 0 to 1, padded by 0.05.
        ({"A": [0.0, 0.0], "B": [0.0]}, [-0.05, 1.05]),
        # 0.5 to 0.8 still reaches 0, so it spans 0.8, padded by 0.04.
        ({None: [0.5, 0.8]}, [-0.04, 0.84]),
    ],
)
def test_replication_figure_pads_its_y_range_below_zero(values, expected):
    scenarios = list(values)
    figure = plots.plotly_figure(
        reporting.replication_figure(
            values=values,
            scenarios=scenarios,
            metric="mean_wait",
            place=None,
            time_unit="minutes",
        )
    )
    axis = figure.layout.yaxis
    assert list(axis.range) == pytest.approx(expected)
    # Autoscale returns to the same padded range.
    assert [
        axis.autorangeoptions.minallowed,
        axis.autorangeoptions.maxallowed,
    ] == pytest.approx(expected)


@pytest.mark.parametrize(
    ("metric", "place", "title"),
    [
        ("mean_wait", "Check", "Mean station waiting time at Check<br>(minutes)"),
        # Model text is escaped on each line, and the break is kept.
        ("mean_wait", "A<B", "Mean station waiting time at A&lt;B<br>(minutes)"),
        # A fraction has no units, so its title keeps one line.
        ("utilization", "Finishing", "Occupied / installed capacity at Finishing"),
    ],
)
def test_replication_figure_puts_units_on_a_second_line(metric, place, title):
    figure = plots.plotly_figure(
        reporting.replication_figure(
            values={None: [0.5, 0.8]},
            scenarios=[None],
            metric=metric,
            place=place,
            time_unit="minutes",
        )
    )
    assert figure.layout.yaxis.title.text == title


@pytest.mark.parametrize(("runs", "dtick"), [(3, 1), (10, 1), (11, None)])
def test_replication_figure_labels_whole_replications_up_to_ten(runs, dtick):
    figure = plots.plotly_figure(
        reporting.replication_figure(
            values={"A": [1.0] * runs, "B": [2.0] * (runs - 1)},
            scenarios=["A", "B"],
            metric="mean_wait",
            place=None,
            time_unit="minutes",
        )
    )
    assert figure.layout.xaxis.dtick == dtick


def test_replication_figure_without_values_keeps_plotly_autorange():
    figure = plots.plotly_figure(
        reporting.replication_figure(
            values={None: [None, None]},
            scenarios=[None],
            metric="mean_wait",
            place=None,
            time_unit="minutes",
        )
    )
    assert figure.layout.yaxis.range is None
    assert figure.layout.yaxis.autorangeoptions.minallowed is None


def test_style_keeps_earlier_layout_and_replaces_what_it_sets():
    def menu_figure():
        data = {
            "data": [
                {"type": "scatter", "x": [1], "y": [1], "meta": "Cut"},
                {"type": "scatter", "x": [1], "y": [2], "meta": "Pack"},
            ],
            "layout": {},
        }
        plots.station_menu(data, ["Cut", "Pack"])
        figure = go.Figure(data)
        figure.update_layout(
            height=300,
            showlegend=False,
            xaxis={"tickformat": ".0%", "title": {"text": "Old", "font": {"size": 20}}},
        )
        return figure

    figure = plots.style(menu_figure(), x_label="Wait", y_label="Count")
    layout = figure.layout
    buttons = layout.updatemenus[0].buttons
    assert [button.label for button in buttons] == ["Cut", "Pack"]
    assert [button.args[0]["visible"] for button in buttons] == [
        [True, False],
        [False, True],
    ]
    assert layout.showlegend is False
    assert layout.xaxis.tickformat == ".0%"
    # A title string replaces the whole title, as update_layout does.
    assert layout.xaxis.title.text == "Wait"
    assert layout.xaxis.title.font.size is None
    assert layout.yaxis.title.text == "Count"
    assert layout.height == 500
    assert layout.margin.l == 85
    assert layout.template == pio.templates["plotly_white"]


def test_comparison_plot_names_scenario_and_station_when_several(comparison):
    figure = comparison.plot("mean_wait")
    assert [trace.name for trace in figure.data] == ["Check-in", "Service"]
    assert list(figure.data[1].y) == ["One<br>Service", "Two<br>Service"]
    assert figure.data[0].showlegend


def test_experiment_export_writes_pooled_tables_and_metadata(tmp_path):
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
        seed=5,
    )
    # The folder stands for an earlier FlowSim export.
    (tmp_path / "metadata.json").write_text('{"flowsim_version": "1.0.0"}')
    (tmp_path / "differences.csv").write_text("stale")
    (tmp_path / "customers.csv").write_text("stale")
    (tmp_path / "notes.txt").write_text("keep")
    experiment.export(
        tmp_path,
        metric="mean_wait",
        confidence=0.9,
    )
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == [
        "intervals.csv",
        "metadata.json",
        "notes.txt",
        "runs.csv",
        "stations.csv",
    ]
    runs = pl.read_csv(tmp_path / "runs.csv")
    assert runs.get_column("replication").to_list() == [1, 2, 3]
    assert runs.get_column("completed").to_list() == [3, 3, 3]
    assert pl.read_csv(tmp_path / "stations.csv").height == 3
    intervals = pl.read_csv(tmp_path / "intervals.csv")
    assert intervals.select("metric", "station", "mean").rows() == [
        ("mean_wait", "Service", 1.0)
    ]
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["metric"] == "mean_wait"
    assert metadata["station"] is None
    assert metadata["confidence"] == 0.9
    assert metadata["duration"] == 7
    assert metadata["time_unit"] == "minutes"
    assert metadata["replication_seeds"] == [
        run.settings.seed for run in experiment.runs
    ]


def test_exports_accept_a_numpy_confidence_level(tmp_path):
    # np.float32 is a real number that intervals accept, but json cannot write
    # it, so the metadata stores the validated Python float.
    level = np.float32(0.9)
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
        seed=5,
    )
    comparison = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=7,
        replications=3,
        seed=5,
    )
    for name, study in [("experiment", experiment), ("comparison", comparison)]:
        folder = tmp_path / name
        study.export(
            folder,
            metric="mean_wait",
            confidence=level,
        )
        metadata = json.loads((folder / "metadata.json").read_text())
        assert metadata["confidence"] == float(level)
        intervals = pl.read_csv(folder / "intervals.csv")
        assert intervals.get_column("confidence").unique().to_list() == [float(level)]


def test_experiment_export_writes_stock_points_for_a_supply_chain(tmp_path):
    experiment = beer_chain().experiment(
        duration=12,
        replications=2,
    )
    experiment.export(
        tmp_path,
        metric="fill_rate",
    )
    assert pl.read_csv(tmp_path / "stock_points.csv").height == 2 * 4
    assert pl.read_csv(tmp_path / "intervals.csv").get_column(
        "stock_point"
    ).to_list() == ["Retailer", "Wholesaler", "Distributor", "Factory"]
    # A later service-network export removes the supply-chain table.
    deterministic_queue().experiment(
        duration=7,
        replications=2,
    ).export(tmp_path)
    assert not (tmp_path / "stock_points.csv").exists()


def test_inapplicable_metrics_name_the_right_call():
    network = deterministic_queue().experiment(
        duration=7,
        replications=2,
    )
    with pytest.raises(ValueError, match="no stock points.*metric='mean_total_wait'"):
        network.intervals("fill_rate")
    with pytest.raises(ValueError, match="no stock points"):
        network.plot("bullwhip_ratio")
    chain = beer_chain().experiment(
        duration=12,
        replications=2,
    )
    # The default metric needs customers, which a chain without production lacks.
    with pytest.raises(ValueError, match="no production stations.*metric='fill_rate'"):
        chain.intervals()
    with pytest.raises(ValueError, match="no production stations"):
        chain.intervals("utilization")
    with pytest.raises(ValueError, match="takes no station="):
        network.intervals(
            "mean_total_wait",
            station="Service",
        )
    with pytest.raises(ValueError, match="takes no stock_point="):
        network.intervals(
            "mean_wait",
            stock_point="Retailer",
        )
    with pytest.raises(ValueError, match="Close matches: Factory"):
        chain.intervals(
            "fill_rate",
            stock_point="Factor",
        )
    both = compare(
        scenarios={
            "Chain": beer_chain(),
            "Other chain": beer_chain("end_demand"),
        },
        duration=12,
        replications=2,
    )
    with pytest.raises(ValueError, match="no production stations"):
        both.intervals()
    with pytest.raises(ValueError, match="no production stations"):
        both.export("unused")


@pytest.fixture(scope="module")
def service_run():
    return service_network().run(
        duration=30,
        seed=1,
    )


@pytest.fixture(scope="module")
def chain_run():
    return beer_chain().run(
        duration=12,
        seed=2,
    )


@pytest.mark.parametrize(
    ("method", "per_station"),
    [("plot_queue", 2), ("plot_wait", 1), ("plot_resources", 6)],
)
def test_station_plots_draw_one_named_station(service_run, method, per_station):
    every = getattr(service_run, method)()
    assert {trace.meta for trace in every.data} == {"Check-in", "Service"}
    assert len(every.layout.updatemenus[0].buttons) == 2
    chosen = getattr(service_run, method)(station="Service")
    assert [trace.meta for trace in chosen.data] == ["Service"] * per_station
    assert all(trace.visible for trace in chosen.data)
    assert not chosen.layout.updatemenus
    with pytest.raises(ValueError, match="Close matches: Service"):
        getattr(service_run, method)(station="Servce")


def test_stacked_resource_plot_stacks_each_stations_layers(service_run):
    from flowsim.plots import server_layers

    figure = service_run.plot_resources(stacked=True)
    names = ["Processing", "Blocked", "Paused", "Down", "Idle", "Scheduled"]
    assert [trace.name for trace in figure.data] == names * 2
    assert [trace.meta for trace in figure.data] == ["Check-in"] * 6 + ["Service"] * 6
    # Each station's five layers share a stack, and the scheduled line does not.
    assert [trace.stackgroup for trace in figure.data] == (
        ["station 0"] * 5 + [None] + ["station 1"] * 5 + [None]
    )
    assert [trace.visible for trace in figure.data] == [True] * 6 + [False] * 6
    layers = server_layers(service_run, "Service")
    for trace, column in zip(
        figure.data[6:11],
        ["processing", "blocked", "paused", "down", "idle"],
        strict=True,
    ):
        assert list(trace.y) == layers.get_column(column).to_list()
    states = service_run.states.filter(pl.col("station") == "Service")
    assert list(figure.data[11].y) == states.get_column("scheduled").to_list()
    assert list(figure.data[11].x) == states.get_column("time").to_list()
    chosen = service_run.plot_resources("Service", stacked=True)
    assert [trace.name for trace in chosen.data] == names


def test_utilization_plot_can_show_one_station(service_run):
    every = service_run.plot_utilization()
    assert list(every.data[0].y) == ["Check-in", "Service"]
    chosen = service_run.plot_utilization(station="Service")
    assert list(chosen.data[0].y) == ["Service"]
    expected = service_run.stations.filter(pl.col("station") == "Service")
    assert list(chosen.data[0].x) == expected.get_column("utilization").to_list()


def test_inventory_plot_draws_one_named_stock_point(chain_run):
    every = chain_run.plot_inventory()
    assert len(every.data) == 4 * 4
    chosen = chain_run.plot_inventory(stock_point="Factory")
    assert [trace.meta for trace in chosen.data] == ["Factory"] * 4
    assert all(trace.visible for trace in chosen.data)
    with pytest.raises(ValueError, match="Close matches: Factory"):
        chain_run.plot_inventory(stock_point="Factroy")


@pytest.mark.parametrize("method", ["plot_inventory", "plot_orders"])
def test_stock_point_plots_on_a_service_network_name_the_station_plots(
    service_run,
    method,
):
    with pytest.raises(ValueError, match=r"no stock points\. plot_queue\(\)"):
        getattr(service_run, method)()


@pytest.mark.parametrize(
    "method",
    ["plot_queue", "plot_wait", "plot_utilization", "plot_resources"],
)
def test_station_plots_on_a_supply_chain_name_the_stock_point_plots(
    chain_run,
    method,
):
    with pytest.raises(ValueError, match=r"no stations\. plot_inventory\(\)"):
        getattr(chain_run, method)()


def test_viewer_holds_the_document_and_saves_it(tmp_path):
    result = deterministic_queue().run(duration=7)
    viewer = result.viewer()
    assert isinstance(viewer, Viewer)
    assert viewer.html.startswith("<!doctype html>")
    saved = viewer.save(tmp_path / "new" / "page.html")
    assert saved == tmp_path / "new" / "page.html"
    assert saved.read_text(encoding="utf-8") == viewer.html
    # A path saves the page and still returns the Viewer.
    direct = result.viewer(tmp_path / "direct.html")
    assert isinstance(direct, Viewer)
    assert (tmp_path / "direct.html").read_text(encoding="utf-8") == direct.html


def test_viewer_displays_in_an_isolated_frame_and_prints_briefly():
    viewer = deterministic_queue().run(duration=7).viewer()
    frame = viewer._repr_html_()
    assert frame.startswith("<iframe srcdoc='")
    assert 'sandbox="allow-scripts allow-downloads"' in frame
    assert "allow-same-origin" not in frame
    # The document is escaped inside srcdoc, so no tag reaches the notebook.
    assert "<script" not in frame
    srcdoc = re.match(r"<iframe srcdoc='([^']*)'", frame).group(1)
    assert "&lt;script" in srcdoc
    text = repr(viewer)
    assert len(text) < 200
    assert "<script" not in text
    assert re.search(r"results page, \d+\.\d MB", text)
    assert ".save(path)" in text and ".open()" in text
    comparison = queue_comparison(replications=2)
    assert "comparison dashboard" in repr(comparison.viewer())
    assert "experiment dashboard" in repr(comparison.experiments["One"].viewer())


@pytest.fixture
def opened(tmp_path, monkeypatch) -> list[str]:
    """Collect the addresses passed to webbrowser.open, working in tmp_path."""
    addresses = []
    monkeypatch.setattr(
        target=webbrowser,
        name="open",
        value=addresses.append,
    )
    monkeypatch.chdir(tmp_path)
    return addresses


def test_unsaved_pages_open_from_one_file_per_kind_in_output(tmp_path, opened, capsys):
    one = deterministic_queue().run(duration=7)
    comparison = queue_comparison(replications=2)
    pages = {
        "results": one.viewer(),
        "supply-chain": beer_chain().run(duration=8).viewer(),
        "experiment": comparison.experiments["One"].viewer(),
        "comparison": comparison.viewer(),
        "builder": builder(),
    }
    for name, viewer in pages.items():
        path = viewer.open()
        assert path == tmp_path / "output" / f"flowsim-{name}.html"
        assert path.read_text(encoding="utf-8") == viewer.html
        assert opened[-1] == path.resolve().as_uri()
        assert capsys.readouterr().out == f"Opening {path.resolve()}\n"
    # These five files are the only ones the Python calls wrote.
    assert sorted(path.name for path in tmp_path.rglob("*") if path.is_file()) == (
        sorted(f"flowsim-{name}.html" for name in pages)
    )
    saved = one.viewer().save(tmp_path / "saved" / "page.html")
    assert saved == tmp_path / "saved" / "page.html"


def test_a_second_unsaved_page_of_a_kind_replaces_the_first_file(tmp_path, opened):
    first = deterministic_queue().run(duration=7).viewer()
    first.open()
    longer = deterministic_queue().run(duration=9).viewer()
    assert longer.html != first.html
    assert longer.open() == tmp_path / "output" / "flowsim-results.html"
    assert Path("output/flowsim-results.html").read_text(encoding="utf-8") == (
        longer.html
    )
    # Replacing the file leaves no other file behind.
    assert [path.name for path in tmp_path.rglob("*") if path.is_file()] == [
        "flowsim-results.html"
    ]


def test_an_unsaved_page_path_names_its_file_after_the_directory_changes(
    tmp_path,
    opened,
    monkeypatch,
):
    viewer = queue_comparison(replications=2).viewer()
    # The page opens here first, so the second open must not reuse that path.
    assert viewer.open() == tmp_path / "output" / "flowsim-comparison.html"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    returned = viewer.open()
    monkeypatch.chdir(tmp_path)
    assert returned == elsewhere / "output" / "flowsim-comparison.html"
    assert returned.read_text(encoding="utf-8") == viewer.html


def test_saved_page_opens_from_its_saved_path(opened, capsys):
    viewer = deterministic_queue().run(duration=7).viewer("pages/run.html")
    assert viewer.open() == Path("pages/run.html")
    assert opened == [Path("pages/run.html").resolve().as_uri()]
    assert capsys.readouterr().out == f"Opening {Path('pages/run.html').resolve()}\n"
    assert not Path("output").exists()


def test_saved_page_reopens_at_its_file_after_a_directory_change(
    tmp_path, opened, monkeypatch
):
    viewer = deterministic_queue().run(duration=7).viewer("pages/run.html")
    saved = tmp_path / "pages" / "run.html"
    saved.unlink()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert viewer.open() == Path("pages/run.html")
    assert opened == [saved.as_uri()]
    assert saved.read_text(encoding="utf-8") == viewer.html
    assert list(elsewhere.iterdir()) == []


def test_headline_columns_come_first_in_tables_and_exports(service_run, tmp_path):
    assert service_run.stations.columns[:6] == [
        "station",
        "mean_wait",
        "mean_queue",
        "utilization",
        "p95_wait",
        "max_queue",
    ]
    assert service_run.summary.columns[:6] == [
        "arrivals",
        "completed",
        "mean_total_wait",
        "mean_flow_time",
        "throughput",
        "overtime",
    ]
    # The schema constant agrees with the table, and no column is lost.
    assert list(STATION_SCHEMA) == service_run.stations.columns
    assert len(set(service_run.stations.columns)) == 29
    service_run.export(tmp_path)
    for table in ["stations", "summary"]:
        exported = pl.read_csv(tmp_path / f"{table}.csv")
        assert exported.columns == getattr(service_run, table).columns


def test_report_lists_each_applicable_metric_with_hand_checked_values():
    # Customers arrive at 0, 1, and 2 and each needs 2 minutes on one server, so
    # all three exit by 6, before closing at 7. One customer waits from 1 to 2
    # and another from 2 to 4, so at most one waits at a time. The server is
    # busy over [0, 6), i.e., 6 of 7 minutes.
    report = deterministic_queue().run(duration=7).report()
    assert report.columns == ["scope", "location", "metric", "label", "value", "units"]
    assert report.group_by("scope", maintain_order=True).len().rows() == [
        ("system", len(SYSTEM_METRICS)),
        ("station", len(STATION_METRICS)),
    ]
    assert report.get_column("metric").to_list() == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    values = {
        (row["location"], row["metric"]): row for row in report.iter_rows(named=True)
    }
    assert values[None, "completed"]["value"] == 3
    assert values[None, "completed"]["units"] == "count"
    assert values["Service", "max_queue"]["value"] == 1
    assert values["Service", "utilization"]["value"] == pytest.approx(6 / 7)
    assert values[None, "mean_total_wait"]["units"] == "minutes"
    assert values[None, "mean_total_wait"]["label"] == "Mean total waiting time"


def test_report_omits_scopes_the_model_lacks(chain_run):
    chain = chain_run.report()
    # Without stations, only the run-level overtime and end_time remain of the
    # system metrics, and no station rows appear.
    assert set(chain.get_column("scope")) == {"stock_point", "system"}
    stages = chain.filter(pl.col("scope") == "stock_point")
    assert stages.get_column("location").unique(maintain_order=True).to_list() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]
    assert chain.height == 4 * len(STOCK_POINT_METRICS) + 2
    model = Model()
    source = model.source(
        name="Customers",
        interarrival=1,
    )
    model.route([source, model.exit])
    plain = model.run(duration=5).report()
    assert set(plain.get_column("scope")) == {"system"}


def public_names(value) -> set[str]:
    return {name for name in dir(value) if not name.startswith("_")}


def test_run_settings_are_frozen_and_plumbing_is_private():
    # Arrivals at 0, 1, and 2 need 2 minutes each, so draining past closing at
    # 3 ends the run when the third customer leaves at 6.
    result = deterministic_queue().run(
        duration=3,
        seed=8,
        drain=True,
    )
    settings = result.settings
    assert isinstance(settings, Settings)
    assert (
        settings.duration,
        settings.warmup,
        settings.drain,
        settings.seed,
        settings.time_unit,
        settings.end_time,
    ) == (3, 0, True, 8, "minutes", 6)
    assert dict(settings.capacities) == {"Service": 1}
    with pytest.raises(FrozenInstanceError):
        settings.duration = 4
    with pytest.raises(TypeError):
        settings.capacities["Service"] = 2
    assert public_names(result) == {
        "customers",
        "visits",
        "states",
        "activities",
        "failures",
        "inventory",
        "shipments",
        "stations",
        "summary",
        "stock_points",
        "settings",
        "supply",
        "stock_point_names",
        "records_kept",
        "plot_queue",
        "plot_wait",
        "plot_utilization",
        "plot_resources",
        "plot_gantt",
        "plot_wip",
        "plot_customer",
        "plot_inventory",
        "plot_orders",
        "viewer",
        "export",
        "report",
        "by_type",
    }


def test_experiment_and_comparison_settings_omit_values_that_differ(comparison):
    experiment = comparison.experiments["One"]
    shared = experiment.settings
    assert (shared.duration, shared.time_unit, shared.seed, shared.end_time) == (
        60,
        "minutes",
        None,
        None,
    )
    assert dict(shared.capacities) == {"Check-in": 1, "Service": 1}
    assert comparison.settings.capacities is None
    assert comparison.settings.duration == 60
    shared_names = {
        "settings",
        "intervals",
        "table",
        "estimate",
        "plot",
        "viewer",
        "export",
    }
    assert public_names(experiment) == shared_names | {
        "runs",
        "summary",
        "stations",
        "stock_points",
        "stock_point_names",
        "plot_warmup",
    }
    assert public_names(comparison) == shared_names | {
        "experiments",
        "baseline",
        "summary",
        "stations",
        "stock_points",
        "differences",
    }


def test_a_comparison_reports_customer_metrics_where_any_scenario_has_them():
    comparison = compare(
        scenarios={
            "Buy": one_stage_chain(produce=False),
            "Make": one_stage_chain(produce=True),
        },
        duration=6,
        replications=2,
    )
    # The buying scenario has no jobs, so its flow time is never observed.
    flow = comparison.intervals("mean_flow_time")
    assert flow.select("scenario", "observed_runs").rows() == [("Buy", 0), ("Make", 2)]
    # Only the making scenario has a station to report.
    press = comparison.intervals("utilization")
    assert press.select("scenario", "station").rows() == [("Make", "Press")]
    assert comparison.differences("utilization").height == 0
    with pytest.raises(ValueError, match="Scenario 'Buy': This supply chain has no"):
        comparison.intervals(
            "utilization",
            station="Press",
        )
    with pytest.raises(ValueError, match="no production stations"):
        comparison.experiments["Buy"].intervals("mean_flow_time")


def test_a_run_without_stations_still_has_a_viewer_but_no_station_plots():
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
    )
    model.route([arrivals, model.exit])
    result = model.run(duration=5)
    assert "FlowSim" in result.viewer().html
    with pytest.raises(ValueError, match="no stations"):
        result.plot_queue()


def test_run_level_metrics_apply_to_a_supply_chain_without_stations():
    # A supply chain cannot drain, so every run stops at closing, i.e.,
    # end_time is the duration and overtime is zero.
    experiment = beer_chain().experiment(
        duration=20,
        replications=3,
    )
    assert experiment.intervals("end_time")["mean"].to_list() == [20.0]
    assert experiment.intervals("overtime")["mean"].to_list() == [0.0]
    with pytest.raises(ValueError, match="no production stations"):
        experiment.intervals("mean_total_wait")
    system = beer_chain().run(duration=20).report().filter(pl.col("scope") == "system")
    assert system["metric"].to_list() == ["overtime", "end_time"]


def test_dropped_records_keep_every_measure_and_explain_the_loss(tmp_path):
    kept = service_network().experiment(
        duration=120,
        replications=3,
        seed=5,
    )
    dropped = service_network().experiment(
        duration=120,
        replications=3,
        seed=5,
        keep_records=False,
    )
    # The same seeds give the same runs, so every measure must match exactly.
    for table in ["summary", "stations", "stock_points"]:
        assert_frame_equal(getattr(kept, table), getattr(dropped, table))
    assert_frame_equal(kept.intervals(), dropped.intervals())
    assert_frame_equal(kept.runs[0].report(), dropped.runs[0].report())
    run = dropped.runs[0]
    for table in ["customers", "visits", "states", "activities", "failures"]:
        with pytest.raises(AttributeError, match="keep_records=True"):
            getattr(run, table)
    for call in [
        lambda: run.plot_queue(),
        lambda: run.plot_customer(1),
        lambda: run.viewer(),
        lambda: run.export(tmp_path / "run"),
    ]:
        with pytest.raises(ValueError, match="reads raw records"):
            call()
    assert "Raw records were dropped" in repr(run)
    assert "Raw records were dropped" in repr(dropped)
    assert "Raw records were dropped" not in repr(kept)
    dropped.export(tmp_path / "experiment")
    assert (tmp_path / "experiment" / "stations.csv").exists()
    with pytest.raises(ValueError, match="keep_records must be True or False"):
        service_network().experiment(
            duration=120,
            keep_records="no",
        )


def test_experiment_and_comparison_table_estimate_and_by_type():
    comp = compare(
        scenarios={
            "One": service_network(service_capacity=1),
            "Two": service_network(service_capacity=2),
        },
        duration=120,
        replications=4,
        seed=7,
        drain=True,
    )
    wide = comp.table(["mean_wip", "throughput", "mean_in_system_time"])
    assert wide.columns == [
        "scenario",
        "mean_wip",
        "throughput",
        "mean_in_system_time",
    ]
    assert wide.get_column("scenario").to_list() == ["One", "Two"]
    station_wide = comp.table(
        ["utilization", "mean_wait"],
        station="Service",
        intervals=True,
    )
    assert station_wide.columns == [
        "scenario",
        "utilization",
        "utilization_lower",
        "utilization_upper",
        "mean_wait",
        "mean_wait_lower",
        "mean_wait_upper",
    ]
    exp_wide = comp.experiments["One"].table(["mean_wip", "throughput"])
    assert exp_wide.columns == ["mean_wip", "throughput"]
    assert exp_wide.height == 1
    custom = comp.estimate(lambda r: float(r.summary["overtime"].item() <= 30))
    assert custom.get_column("scenario").to_list() == ["One", "Two"]
    assert custom.get_column("observed_runs").to_list() == [4, 4]
    diff_custom = comp.estimate(
        lambda r: float(r.summary["overtime"].item()),
        differences=True,
    )
    assert diff_custom.get_column("scenario").to_list() == ["Two"]
    assert diff_custom.get_column("baseline").to_list() == ["One"]

    # Hand-checked by_type()
    model = Model()
    arrivals = model.source(
        name="Orders",
        interarrival=1,
        first_arrival=0,
        limit=2,
        types={"A": 1.0},
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=2,
    )
    model.route([arrivals, desk, model.exit])
    by_type = model.run(duration=10, drain=True).by_type()
    assert by_type.get_column("customer_type").to_list() == ["A"]
    assert by_type.get_column("completed").to_list() == [2]
    assert by_type.get_column("mean_flow_time").to_list() == [2.5]


def test_new_diagnostic_plots_render_expected_traces():
    run = service_network().run(
        duration=120,
        seed=7,
        warmup=20,
        drain=True,
    )
    gantt = run.plot_gantt(start=0, end=40)
    assert gantt.data
    assert gantt.layout.barmode == "overlay"

    wip = run.plot_wip()
    assert wip.data[0].name == "In system (WIP)"
    assert len(wip.layout.shapes) == 2  # Warm-up and Closing

    ecdf = run.plot_wait("Service", kind="ecdf")
    assert ecdf.data[0].type == "scatter"
    assert ecdf.layout.yaxis.title.text == "Cumulative share"

    breakdown = run.plot_utilization(breakdown=True)
    assert breakdown.layout.barmode == "stack"
    assert [trace.name for trace in breakdown.data] == [
        "Processing",
        "Blocked",
        "Paused",
        "Idle",
    ]

    exp = service_network().experiment(
        duration=120,
        replications=3,
        seed=5,
        warmup=20,
    )
    welch = exp.plot_warmup(metric="wip", window=3)
    assert len(welch.data) == 2
    assert "Welch" in welch.data[1].name
    chain_exp = beer_chain().experiment(
        duration=30,
        replications=2,
        seed=7,
    )
    chain_welch = chain_exp.plot_warmup(metric="on_hand", stock_point="Retailer")
    assert len(chain_welch.data) == 1


def test_stack_preserves_label_dtype_for_empty_tables():
    empty = pl.DataFrame(schema={"value": pl.Float64})
    non_empty = pl.DataFrame({"value": [1.0]})
    from flowsim.results import stack

    first = stack([(1, empty), (2, empty)], column="replication")
    second = stack([(1, non_empty), (2, non_empty)], column="replication")
    assert first.schema["replication"] == pl.Int64
    combined = stack([("Empty", first), ("Full", second)], column="scenario")
    assert combined.height == 2
    assert combined.get_column("scenario").to_list() == ["Full", "Full"]
