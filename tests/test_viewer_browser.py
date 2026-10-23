"""Exercise the saved viewers in a real browser when Chrome is available."""

import polars as pl
import pytest

from flowsim import Model, compare
from tests.models import (
    beer_chain,
    combined_line,
    deterministic_queue,
    service_network,
)


@pytest.mark.parametrize("drain", [False, True])
def test_offline_viewer_controls_and_download(tmp_path, offline_page, drain):
    result = service_network().run(
        duration=480,
        seed=42,
        drain=drain,
    )
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 4
    assert "Unfinished at closing" in page.locator("#cards").inner_text()
    if drain:
        assert (
            "every admitted customer was served" in page.locator("#notice").inner_text()
        )
    assert page.locator("#station-choice option").all_text_contents() == [
        "Check-in",
        "Service",
    ]
    page.select_option("#station-choice", "Service")
    page.wait_for_function("document.getElementById('queues').data[2].visible === true")
    assert page.evaluate(
        "document.getElementById('queues').data.map(trace => trace.visible)"
    ) == [False, False, True, True]
    assert page.evaluate(
        "document.getElementById('waits').data.map(trace => trace.visible)"
    ) == [False, True]
    page.fill("#customer-choice", "2")
    page.click("#show-customer")
    assert "Customer 2 arrived" in page.locator("#customer-details").inner_text()
    page.select_option("#status-choice", "in_service")
    # The expected counts come from the run, so this test checks the viewer's
    # filter and download rather than a seeded count.
    in_service = result.customers.filter(pl.col("status") == "in_service").height
    remaining = result.customers.get_column("exit_time").null_count()
    assert (in_service > 0) is not drain
    assert page.locator("#customers tbody tr").count() == in_service
    assert (
        f"{in_service} matching customers" in page.locator("#page-details").inner_text()
    )
    with page.expect_download() as download_info:
        page.click("#download-customers")
    download = download_info.value
    downloaded_path = tmp_path / download.suggested_filename
    download.save_as(downloaded_path)
    downloaded = pl.read_csv(
        source=downloaded_path,
        schema_overrides=result.customers.schema,
    )
    assert downloaded.height == result.customers.height
    assert downloaded.get_column("exit_time").null_count() == remaining


def test_empty_run_downloads_use_export_columns(tmp_path, offline_page):
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=10,
    )
    service = model.station(
        name="Service",
        capacity=1,
        service_time=1,
    )
    model.route([arrivals, service, model.exit])
    result = model.run(duration=5)
    assert result.customers.height == result.visits.height == 0
    viewer = tmp_path / "viewer.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    for name in ["customers", "visits"]:
        with page.expect_download() as download_info:
            page.click(f"#download-{name}")
        path = tmp_path / f"{name}.csv"
        download_info.value.save_as(path)
        header = path.read_text().strip().split(",")
        assert header == [f'"{column}"' for column in getattr(result, name).columns]


def test_scenario_report_renders_intervals_offline(tmp_path, offline_page):
    comparison = compare(
        scenarios={
            "One server": deterministic_queue(),
            "Two servers": deterministic_queue(capacity=2),
        },
        duration=3,
        replications=3,
        drain=True,
    )
    viewer = tmp_path / "comparison.html"
    comparison.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function(
        "document.getElementById('scenario-differences').data !== undefined"
    )
    assert page.locator(".js-plotly-plot").count() == 2
    assert page.locator("table tbody tr").count() == 2
    assert page.evaluate("document.getElementById('scenario-means').data[0].x") == [
        1,
        0,
    ]
    assert page.evaluate(
        "document.getElementById('scenario-differences').data[0].x"
    ) == [-1]


def test_extended_viewer_shows_resource_states_rejections_and_paused_work(
    tmp_path, offline_page
):
    result = combined_line().run(
        duration=180,
        drain=True,
    )
    paused = result.activities.filter(pl.col("state") == "paused").to_dicts()
    assert paused
    viewer = tmp_path / "extensions.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 5
    assert page.locator("#resources-section").is_visible()
    assert page.locator("#failure-records tbody tr").count() == result.failures.height
    assert "Rejected arrivals:" in page.locator("#notice").inner_text()
    page.select_option("#station-choice", "Finishing")
    page.wait_for_function(
        "document.getElementById('resources').data[6].visible === true"
    )
    # Assembly and Finishing each draw six resource traces.
    assert (
        page.evaluate(
            "document.getElementById('resources').data.map(trace => trace.visible)"
        )
        == [False] * 6 + [True] * 6
    )
    page.fill("#customer-choice", str(paused[0]["customer_id"]))
    page.click("#show-customer")
    page.wait_for_function("document.getElementById('timeline').data[2].x.length > 0")
    assert page.evaluate("document.getElementById('timeline').data[2].name") == "Paused"
    page.select_option("#status-choice", "rejected")
    rejected = result.summary.to_dicts()[0]["rejected"]
    assert (
        f"{rejected} matching customers" in page.locator("#page-details").inner_text()
    )


def test_supply_viewer_switches_stock_points_and_downloads_records(
    tmp_path, offline_page
):
    result = beer_chain().run(
        duration=30,
        seed=4,
        warmup=5,
    )
    viewer = tmp_path / "supply.html"
    result.viewer(viewer)
    page = offline_page(viewer)
    page.wait_for_function("window.flowsimReady !== undefined")
    page.evaluate("window.flowsimReady")
    assert page.locator(".js-plotly-plot").count() == 2
    assert page.locator("#stock-points tbody tr").count() == 4
    assert page.locator("#stock-choice option").all_text_contents() == [
        "Retailer",
        "Wholesaler",
        "Distributor",
        "Factory",
    ]
    # Consumer demand plus one order trace per stage.
    assert page.evaluate("document.getElementById('orders').data.length") == 5
    page.select_option("#stock-choice", "Factory")
    page.wait_for_function(
        "document.getElementById('inventory').data[12].visible === true"
    )
    # Each stock point draws four traces.
    assert (
        page.evaluate(
            "document.getElementById('inventory').data.map(trace => trace.visible)"
        )
        == [False] * 12 + [True] * 4
    )
    for name in ["inventory", "shipments"]:
        with page.expect_download() as download_info:
            page.click(f"#download-{name}")
        path = tmp_path / f"{name}.csv"
        download_info.value.save_as(path)
        downloaded = pl.read_csv(
            source=path,
            schema_overrides=getattr(result, name).schema,
        )
        assert downloaded.height == getattr(result, name).height
        assert downloaded.columns == getattr(result, name).columns
