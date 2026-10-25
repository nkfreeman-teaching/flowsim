"""Run the code the machining-line video shows and capture its numbers and screenshots.

    pixi run python manim/machining-line/capture.py

Runs in the project environment. Writes captured/numbers.json and captured/*.png, which
machining_line.py reads and asserts in the manim environment.
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
    relative,
    run_snippet,
    shoot,
    write_numbers,
)

OUT = HERE / "captured"
# Minutes of day 1 that the CNC resource chart shows.
CNC_WINDOW = (250, 400)
SNIPPETS = HERE / "snippets"
STATION_METRICS = [
    "utilization",
    "processing_utilization",
    "blocking_fraction",
    "downtime_fraction",
    "mean_scheduled_servers",
]


def main():
    OUT.mkdir(exist_ok=True)
    numbers = {"sources": {}, "images": {}}

    def record_image(name, path):
        numbers["images"][name] = {"file": Path(path).name, "size": png_size(path)}

    for path in [*sorted(SNIPPETS.glob("*.py")), ROOT / "examples" / "operations.py"]:
        numbers["sources"][relative(path)] = digest(path)

    line, _ = run_snippet(SNIPPETS / "line.py")
    comparison = line["comparison"]
    record_image("output", frame_png(line["output"], OUT / "output.png"))
    record_image("gains", frame_png(line["gains"], OUT / "gains.png"))
    record_image("moved", frame_png(line["moved"], OUT / "moved.png"))
    numbers["scenarios"] = list(comparison.experiments)
    numbers["completed"] = {
        name: column(experiment.summary.sort("replication"), "completed_at_close")
        for name, experiment in comparison.experiments.items()
    }
    numbers["output"] = {row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in line["output"].to_dicts()}
    numbers["gains"] = {row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in line["gains"].to_dicts()}
    numbers["moved"] = {row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in line["moved"].to_dicts()}
    numbers["stations"] = {}
    for name, experiment in comparison.experiments.items():
        table = experiment.stations.sort("replication")
        numbers["stations"][name] = {
            station: {metric: column(table.filter(pl.col("station") == station), metric) for metric in STATION_METRICS}
            for station in ["Saw", "CNC", "Wash", "Assembly", "Pack"]
        }
    runs = [run for experiment in comparison.experiments.values() for run in experiment.runs]
    numbers["durations"] = sorted({run.duration for run in runs})
    numbers["drain"] = sorted({run.drain for run in runs})
    numbers["replications"] = sorted({len(experiment.runs) for experiment in comparison.experiments.values()})

    viewer = ROOT / "output" / "machining" / "viewer.html"
    for station in ["Assembly", "CNC"]:

        def choose(page, station=station):
            page.select_option("#station-choice", station)
            page.wait_for_timeout(400)
            # CNC's chart shows a window where both down and blocked spans appear.
            if station == "CNC":
                page.evaluate(f"Plotly.relayout('resources', {{'xaxis.range': {list(CNC_WINDOW)}}})")
                page.wait_for_timeout(400)

        record_image(
            f"resources_{station.lower()}",
            shoot(viewer, OUT / f"resources_{station.lower()}.png", selector="#resources", viewport=(900, 900), wait_ready=True, before=choose),
        )
    page = ROOT / "output" / "machining" / "comparison.html"
    for index, name in enumerate(["comparison_means", "comparison_differences"]):
        record_image(name, shoot(page, OUT / f"{name}.png", selector=f"section >> nth={index}", viewport=(1000, 900)))
    numbers["cnc_window"] = list(CNC_WINDOW)
    write_numbers(OUT, numbers)


if __name__ == "__main__":
    main()
