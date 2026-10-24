"""Run the code the service-day video shows and capture its numbers and screenshots.

    pixi run python manim/service-day/capture.py

Runs in the project environment. Writes captured/numbers.json and captured/*.png, which
service_day.py reads and asserts in the manim environment.
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
SNIPPETS = HERE / "snippets"


def main():
    OUT.mkdir(exist_ok=True)
    numbers = {"sources": {}, "images": {}}

    def record_image(name, path):
        numbers["images"][name] = {"file": Path(path).name, "size": png_size(path)}

    for path in [
        *sorted(SNIPPETS.glob("*.py")),
        ROOT / "examples" / "models.py",
        ROOT / "examples" / "service_day.py",
    ]:
        numbers["sources"][relative(path)] = digest(path)

    exercise, _ = run_snippet(SNIPPETS / "exercise.py")
    comparison, decision = exercise["comparison"], exercise["decision"]
    record_image("decision", frame_png(exercise["targets"], OUT / "decision.png"))
    numbers["decision"] = decision.to_dicts()
    numbers["days"] = {
        name: {
            "mean_total_wait": column(experiment.summary.sort("replication"), "mean_total_wait"),
            "overtime": column(experiment.summary.sort("replication"), "overtime"),
            "remaining": column(experiment.summary.sort("replication"), "remaining"),
        }
        for name, experiment in comparison.experiments.items()
    }
    numbers["drain"] = all(run.drain for experiment in comparison.experiments.values() for run in experiment.runs)
    numbers["durations"] = sorted(
        {run.duration for experiment in comparison.experiments.values() for run in experiment.runs},
    )
    # Day 1 of one and two servers, as the saved viewers show the Service queue.
    def choose_service(page):
        page.select_option("#station-choice", "Service")
        page.wait_for_timeout(400)

    numbers["first_day"] = {}
    for name in ["One server", "Two servers"]:
        run = comparison.experiments[name].runs[0]
        folder = name.lower().replace(" ", "-")
        service = run.stations.filter(pl.col("station") == "Service").row(0, named=True)
        per_run = comparison.experiments[name].stations.filter(
            (pl.col("station") == "Service") & (pl.col("replication") == 1),
        ).row(0, named=True)
        numbers["first_day"][name] = {
            "max_queue": service["max_queue"],
            "mean_queue": service["mean_queue"],
            "replication_max_queue": per_run["max_queue"],
            "replication_mean_queue": per_run["mean_queue"],
            "overtime": run.summary.row(0, named=True)["overtime"],
            "seed": run.seed,
        }
        record_image(
            f"day_{folder}",
            shoot(
                ROOT / "output" / "service-day" / folder / "viewer.html",
                OUT / f"day_{folder}.png",
                selector="#queues",
                viewport=(760, 900),
                wait_ready=True,
                before=choose_service,
            ),
        )
    page = ROOT / "output" / "service-day" / "overtime-comparison.html"
    record_image("overtime_viewer", shoot(page, OUT / "overtime_viewer.png", selector="section >> nth=0", viewport=(1000, 900)))
    write_numbers(OUT, numbers)


if __name__ == "__main__":
    main()
