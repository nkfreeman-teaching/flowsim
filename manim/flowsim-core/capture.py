"""Run the code the flowsim-core video shows and capture its numbers and screenshots.

    pixi run python manim/flowsim-core/capture.py

Runs in the project environment. Writes captured/numbers.json and captured/*.png, which
flowsim_core.py reads and asserts in the manim environment.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))

import polars as pl  # noqa: E402
from capture_tools import (  # noqa: E402
    ROOT,
    column,
    digest,
    frame_png,
    png_size,
    readme_blocks,
    relative,
    run_readme_block,
    run_snippet,
    shoot,
    write_numbers,
)

OUT = HERE / "captured"
SNIPPETS = HERE / "snippets"
# The viewer's customer timeline shows this customer, who waits before service.
TIMELINE_CUSTOMER = 3
# README headings whose blocks the extension tour quotes; each block runs here.
TOUR = [
    "Branches and shared stations",
    "Customer types",
    "Demand and staffing schedules",
    "Finite buffers and blocking",
    "Priorities and abandonment",
    "Failures and repair",
    "Inventory and ordering",
]


def main():
    OUT.mkdir(exist_ok=True)
    numbers = {"sources": {}, "images": {}}

    def record_image(name, path):
        numbers["images"][name] = {"file": Path(path).name, "size": png_size(path)}

    for path in [*sorted(SNIPPETS.glob("*.py")), ROOT / "examples" / "models.py"]:
        numbers["sources"][relative(path)] = digest(path)

    # The deterministic queue (README "For maintainers", examples/models.py).
    queue, _ = run_snippet(SNIPPETS / "queue.py")
    results = queue["results"]
    for name in ["customers", "visits", "stations", "summary"]:
        record_image(name, frame_png(queue[name], OUT / f"{name}.png"))
    customers = results.customers
    station = results.stations.row(0, named=True)
    totals = results.summary.row(0, named=True)
    numbers["queue"] = {
        "arrival_time": column(customers, "arrival_time"),
        "exit_time": column(customers, "exit_time"),
        "flow_time": column(customers, "flow_time"),
        "total_wait": column(customers, "total_wait"),
        "service_start": column(results.visits, "service_start"),
        "service_end": column(results.visits, "service_end"),
        "server_id": column(results.visits, "server_id"),
        "mean_wait": station["mean_wait"],
        "mean_queue": station["mean_queue"],
        "utilization": station["utilization"],
        "capacity": station["capacity"],
        "arrivals": totals["arrivals"],
        "completed": totals["completed"],
        "mean_flow_time": totals["mean_flow_time"],
        "throughput": totals["throughput"],
        "end_time": totals["end_time"],
        "warmup": results.warmup,
    }
    viewer = ROOT / "output" / "queue" / "viewer.html"
    shots = {
        "viewer_top": "section:has(#stations)",
    }
    for name, selector in shots.items():
        record_image(
            name,
            shoot(viewer, OUT / f"{name}.png", selector=selector, viewport=(1000, 900), wait_ready=True),
        )

    # The chart alone, at a narrower page width, so its labels stay readable on a slide.
    record_image(
        "viewer_queues",
        shoot(viewer, OUT / "viewer_queues.png", selector="#queues", viewport=(760, 900), wait_ready=True),
    )

    def show_customer(page):
        page.fill("#customer-choice", str(TIMELINE_CUSTOMER))
        page.click("#show-customer")

    record_image(
        "viewer_timeline",
        shoot(
            viewer,
            OUT / "viewer_timeline.png",
            selector="#timeline",
            viewport=(760, 900),
            wait_ready=True,
            before=show_customer,
        ),
    )
    numbers["timeline_customer"] = TIMELINE_CUSTOMER
    record_image(
        "viewer_cards",
        shoot(viewer, OUT / "viewer_cards.png", selector="#cards", viewport=(1000, 900), wait_ready=True),
    )
    export = ROOT / "output" / "queue"
    numbers["export_files"] = sorted(
        path.name for path in export.iterdir() if path.is_file() and path.name != "viewer.html"
    )
    numbers["viewer_bytes"] = viewer.stat().st_size

    # Twenty replications of the two-stage network (README "Replications and scenario
    # comparisons").
    replications, _ = run_snippet(SNIPPETS / "replications.py")
    experiment = replications["experiment"]
    record_image("waits", frame_png(replications["waits"], OUT / "waits.png"))
    full = experiment.intervals("mean_wait")
    service = full.filter(pl.col("station") == "Service").row(0, named=True)
    per_run = experiment.stations.filter(pl.col("station") == "Service").sort("replication")
    # The waits table also shows Check-in's interval, so its runs are recorded too.
    checkin = full.filter(pl.col("station") == "Check-in").row(0, named=True)
    checkin_runs = experiment.stations.filter(pl.col("station") == "Check-in").sort("replication")
    numbers["replications"] = {
        "service_runs": column(per_run, "mean_wait"),
        "service_mean": service["mean"],
        "service_lower": service["lower"],
        "service_upper": service["upper"],
        "runs": service["runs"],
        "checkin_runs": column(checkin_runs, "mean_wait"),
        "checkin_interval": [checkin["mean"], checkin["lower"], checkin["upper"]],
        "confidence": service["confidence"],
        "seeds_distinct": len({run.seed for run in experiment.runs}),
    }

    # Paired comparison of one, two, and three Service servers, against two.
    paired, _ = run_snippet(SNIPPETS / "compare.py")
    comparison = paired["comparison"]
    record_image("means", frame_png(paired["means"], OUT / "means.png"))
    record_image("paired", frame_png(paired["paired"], OUT / "paired.png"))
    scenario_runs = {
        name: column(experiment.summary.sort("replication"), "mean_total_wait")
        for name, experiment in comparison.experiments.items()
    }
    seeds = {name: [run.seed for run in experiment.runs] for name, experiment in comparison.experiments.items()}
    numbers["compare"] = {
        "runs": scenario_runs,
        "same_seeds": len({tuple(value) for value in seeds.values()}) == 1,
        "means": {row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in paired["means"].to_dicts()},
        "differences": {
            row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in paired["paired"].to_dicts()
        },
        "baseline": paired["paired"].get_column("baseline").unique().to_list(),
    }
    page = ROOT / "output" / "staffing" / "comparison.html"
    for index, name in enumerate(["comparison_means", "comparison_differences"]):
        record_image(name, shoot(page, OUT / f"{name}.png", selector=f"section >> nth={index}", viewport=(1000, 900)))

    # The extension tour quotes README blocks; each one runs here as written.
    blocks = readme_blocks()
    numbers["readme_blocks"] = {}
    for heading in TOUR:
        run_readme_block(heading)
        numbers["readme_blocks"][heading] = digest_text(blocks[heading][0])
    write_numbers(OUT, numbers)


def digest_text(text):
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


if __name__ == "__main__":
    main()
