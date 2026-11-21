"""Experiment and comparison dashboards: their data, runs, and checks."""

import base64
import json
import re
from pathlib import Path

import numpy as np
import pytest
from plotly.offline import get_plotlyjs_version

import flowsim
from flowsim import compare
from flowsim.catalog import STATION_METRICS, SYSTEM_METRICS
from flowsim.plots import PLOTLY_BUNDLE, page_template
from tests.models import (
    beer_chain,
    combined_line,
    deterministic_queue,
    embedded_json,
    queue_comparison,
    two_station_queue,
)


def test_experiment_viewer_shows_one_metric_without_differences(tmp_path):
    # One server gives waits 0, 1, and 2 in every replication, so the mean
    # station wait is 1 with a zero-width interval.
    experiment = deterministic_queue().experiment(
        duration=7,
        replications=3,
    )
    viewer = experiment.viewer(
        tmp_path / "page.html",
        metric="mean_wait",
    )
    page = viewer.html
    assert (tmp_path / "page.html").read_text(encoding="utf-8") == page
    assert "<h1>Replication intervals</h1>" in page
    data = embedded_json(page, "dashboard-data")
    assert data["scenarios"] == [None]
    assert data["initial"] == {
        "metric": "mean_wait",
        "location": None,
        "baseline": None,
    }
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    assert entry["locations"] == ["Service"]
    assert entry["units"] == "minutes"
    (view,) = entry["views"]
    assert view["title"] == "Mean station waiting time at Service"
    assert [
        (row["station"], row["mean"], row["lower"], row["upper"], row["observed_runs"])
        for row in view["intervals"]
    ] == [("Service", 1.0, 1.0, 1.0, 3)]
    assert view["changes"] == {}
    assert view["runs"]["data"][0]["y"] == [1.0, 1.0, 1.0]
    # The menu lists every metric that applies, in catalog order, so a
    # service network lists no stock-point metric.
    assert [item["name"] for item in data["metrics"]] == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    assert "__" + "DASHBOARD_JSON" + "__" not in page


def test_comparison_dashboard_holds_every_metric_baseline_and_run(tmp_path):
    # One server gives a mean station wait of 1 and two servers give 0 in
    # every replication, so each paired difference is -1 from One and +1
    # from Two.
    comparison = queue_comparison(replications=3)
    page = comparison.viewer(
        metric="mean_wait",
        station="Service",
        baseline="Two",
    ).html
    data = embedded_json(page, "dashboard-data")
    assert data["scenarios"] == ["One", "Two"]
    assert data["initial"] == {
        "metric": "mean_wait",
        "location": "Service",
        "baseline": "Two",
    }
    assert [item["name"] for item in data["metrics"]] == [
        *SYSTEM_METRICS,
        *STATION_METRICS,
    ]
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    (view,) = entry["views"]
    assert [(row["scenario"], row["mean"]) for row in view["intervals"]] == [
        ("One", 1.0),
        ("Two", 0.0),
    ]
    for baseline, scenario, difference in [("One", "Two", -1.0), ("Two", "One", 1.0)]:
        (row,) = view["changes"][baseline]["intervals"]
        assert (row["scenario"], row["baseline"], row["mean"]) == (
            scenario,
            baseline,
            difference,
        )
    traces = view["runs"]["data"]
    assert [trace["y"] for trace in traces] == [[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]
    assert traces[1]["customdata"] == [[1, 0], [1, 1], [1, 2]]
    # Each run's records sit in their own element, as its run page holds them.
    for scenario, (name, experiment) in enumerate(comparison.experiments.items()):
        for index, run in enumerate(experiment.runs):
            embedded = embedded_json(page, f"run-{scenario}-{index}")
            single = embedded_json(run.viewer().html, "result-data")
            assert embedded == single
            assert data["runs"][scenario][index]["label"] == (
                f"{name}, replication {index + 1} (seed {run.settings.seed})"
            )
    # Plotly and the shared template appear once, and no figure repeats it.
    assert page.count(plotly_bundle()[:400]) == 1
    assert embedded_json(page, "plot-template") == page_template()
    assert '"template"' not in json.dumps(data)
    assert '"template"' not in json.dumps(embedded_json(page, "run-0-0"))


def test_dashboard_without_records_holds_no_runs():
    comparison = queue_comparison(
        replications=3,
        keep_records=False,
    )
    # compare passes keep_records to every scenario's runs, not only some.
    for experiment in comparison.experiments.values():
        assert all(not run.records_kept for run in experiment.runs)
    for page in [comparison.viewer().html, comparison.experiments["One"].viewer().html]:
        data = embedded_json(page, "dashboard-data")
        assert data["records"] is False
        assert '<script id="run-' not in page
        assert len(data["runs"][0]) == 3


def test_dashboard_requests_are_checked_before_the_page_is_built():
    comparison = queue_comparison(replications=2)
    with pytest.raises(ValueError, match="Close matches"):
        comparison.viewer(metric="mean_wiat")
    with pytest.raises(ValueError, match="Unknown baseline scenario"):
        comparison.viewer(baseline="Three")
    with pytest.raises(ValueError, match="takes no station="):
        comparison.experiments["One"].viewer(station="Service")


def test_replication_points_keep_their_scenario_where_another_lacks_the_station():
    comparison = compare(
        scenarios={
            "Without": deterministic_queue(),
            "With": two_station_queue(),
        },
        duration=7,
        replications=2,
    )
    data = embedded_json(comparison.viewer().html, "dashboard-data")
    entry = next(item for item in data["metrics"] if item["name"] == "mean_wait")
    assert entry["locations"] == ["Service", "Check"]
    service, check = entry["views"]
    assert [trace["customdata"] for trace in service["runs"]["data"]] == [
        [[0, 0], [0, 1]],
        [[1, 0], [1, 1]],
    ]
    # Only "With" has Check, and its points still open its own runs, in its
    # own color.
    (trace,) = check["runs"]["data"]
    assert trace["name"] == "With"
    assert trace["customdata"] == [[1, 0], [1, 1]]
    assert trace["marker"]["color"] == service["runs"]["data"][1]["marker"]["color"]
    assert [row["scenario"] for row in check["intervals"]] == ["With"]
    assert check["changes"]["Without"] is None


def as_page_holds_it(figure) -> dict:
    """Return a plot method's figure as page JSON, without the shared template."""
    data = json.loads(figure.to_json())
    del data["layout"]["template"]
    return data


def decoded(value: object) -> object:
    """Return page JSON with its typed arrays turned back into lists."""
    if isinstance(value, dict):
        if set(value) == {"dtype", "bdata"}:
            raw = base64.b64decode(value["bdata"])
            return np.frombuffer(raw, dtype=value["dtype"]).tolist()
        return {key: decoded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decoded(item) for item in value]
    return value


@pytest.mark.parametrize(
    ("model", "metric", "location", "run_figures"),
    [
        (
            combined_line,
            "mean_wait",
            {"station": "Finishing"},
            {
                "queues": lambda run: run.plot_queue(),
                "waits": lambda run: run.plot_wait(),
                "utilization": lambda run: run.plot_utilization(),
                "resources": lambda run: run.plot_resources(),
            },
        ),
        (
            beer_chain,
            "fill_rate",
            {"stock_point": "Wholesaler"},
            {
                "orders": lambda run: run.plot_orders(),
                "inventory": lambda run: run.plot_inventory(),
            },
        ),
    ],
)
def test_pages_hold_the_figures_the_plot_methods_return(
    model,
    metric,
    location,
    run_figures,
):
    # Each figure is defined once, so a page's copy is the plot method's
    # figure without the template, which the page holds once.
    comparison = compare(
        scenarios={"A": model(), "B": model()},
        duration=60,
        replications=2,
        warmup=5,
    )
    page = comparison.viewer(metric=metric, **location).html
    data = embedded_json(page, "dashboard-data")
    entry = next(item for item in data["metrics"] if item["name"] == metric)
    view = entry["views"][entry["locations"].index(*location.values())]
    assert view["means"] == as_page_holds_it(comparison.plot(metric, **location))
    assert view["changes"]["A"]["figure"] == as_page_holds_it(
        comparison.plot(
            metric,
            differences=True,
            baseline="A",
            **location,
        )
    )
    run = comparison.experiments["B"].runs[1]
    payload = decoded(embedded_json(page, "run-1-1"))
    assert isinstance(payload, dict)
    for name, plot in run_figures.items():
        assert payload["figures"][name] == as_page_holds_it(plot(run))
    if "resources" in run_figures:
        assert payload["stacked_resources"] == as_page_holds_it(
            run.plot_resources(stacked=True)
        )


def plotly_bundle() -> str:
    package = Path(flowsim.__file__).parent
    return (package / PLOTLY_BUNDLE).read_text(encoding="utf-8")


def test_the_plotly_bundle_matches_the_installed_plotly_version():
    # Figures are built by the plotly package and drawn by the bundle, so the
    # two must be the same plotly.js release. Replace the bundle file when
    # plotly is upgraded (see PLOTLY_BUNDLE in flowsim/plots.py).
    header = plotly_bundle()[:200]
    assert f"plotly.js (cartesian - minified) v{get_plotlyjs_version()}\n" in header


def test_the_plotly_bundle_holds_every_trace_type_flowsim_draws():
    # The cartesian bundle leaves out most trace types (e.g., table and
    # scattergl), and a page would fail to draw one of those.
    # A figure names its traces as go.Scatter(...) or as "type": "scatter" in a
    # plain figure. A shape is a "line" and an error bar's values are "data".
    sources = [
        path.read_text(encoding="utf-8")
        for path in Path(flowsim.__file__).parent.glob("*.py")
    ]
    built = {
        name.lower()
        for source in sources
        for name in re.findall(r"\bgo\.([A-Z]\w*)\(", source)
    } - {"figure", "layout"}
    named = {
        name for source in sources for name in re.findall(r'"type": "(\w+)"', source)
    } - {"line", "data"}
    assert named == {"scatter", "bar", "histogram"}
    drawn = built | named
    assert drawn == {"scatter", "bar", "histogram"}
    bundle = plotly_bundle()
    for name in drawn:
        assert f'moduleType:"trace",name:"{name}"' in bundle
