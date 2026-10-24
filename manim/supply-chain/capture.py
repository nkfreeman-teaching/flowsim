"""Run the code the supply-chain video shows and capture its numbers and screenshots.

    pixi run python manim/supply-chain/capture.py

Runs in the project environment. Writes captured/numbers.json and captured/*.png, which
supply_chain.py reads and asserts in the manim environment.
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
COLUMNS = ["bullwhip_ratio", "fill_rate", "order_variance", "demand_variance", "periods"]


def per_run(comparison):
    """Each scenario's stock-point columns by stage, in replication order."""
    table = comparison.stock_points.sort("replication")
    return {
        scenario: {
            stage: {
                name: column(table.filter((pl.col("scenario") == scenario) & (pl.col("stock_point") == stage)), name)
                for name in COLUMNS
            }
            for stage in table.get_column("stock_point").unique(maintain_order=True).to_list()
        }
        for scenario in comparison.experiments
    }


def intervals(comparison, metric, stage):
    rows = comparison.intervals(metric=metric, stock_point=stage).to_dicts()
    return {row["scenario"]: [row["mean"], row["lower"], row["upper"]] for row in rows}


def main():
    OUT.mkdir(exist_ok=True)
    numbers = {"sources": {}, "images": {}}

    def record_image(name, path):
        numbers["images"][name] = {"file": Path(path).name, "size": png_size(path)}

    for path in [*sorted(SNIPPETS.glob("*.py")), ROOT / "examples" / "supply_chain.py"]:
        numbers["sources"][relative(path)] = digest(path)

    bullwhip, _ = run_snippet(SNIPPETS / "bullwhip.py")
    comparison = bullwhip["comparison"]
    record_image("ratios", frame_png(bullwhip["ratios"], OUT / "ratios.png"))
    record_image("growth", frame_png(bullwhip["growth"], OUT / "growth.png"))
    numbers["bullwhip"] = {
        "scenarios": list(comparison.experiments),
        "runs": per_run(comparison),
        "growth": bullwhip["growth"].to_dicts(),
        "ratio": {stage: intervals(comparison, "bullwhip_ratio", stage) for stage in ["Retailer", "Wholesaler", "Distributor", "Factory"]},
        "fill": {stage: intervals(comparison, "fill_rate", stage) for stage in ["Retailer", "Wholesaler"]},
        "factory_differences": {
            row["scenario"]: [row["mean"], row["lower"], row["upper"]]
            for row in comparison.differences(metric="bullwhip_ratio", stock_point="Factory").to_dicts()
        },
        "warmup": sorted({run.warmup for experiment in comparison.experiments.values() for run in experiment.runs}),
        "duration": sorted({run.duration for experiment in comparison.experiments.values() for run in experiment.runs}),
    }
    viewer = ROOT / "output" / "supply" / "viewer.html"
    record_image("orders", shoot(viewer, OUT / "orders.png", selector="#orders", viewport=(900, 900), wait_ready=True))
    record_image(
        "stock_table",
        shoot(viewer, OUT / "stock_table.png", selector="section:has(#stock-points)", viewport=(1000, 900), wait_ready=True),
    )

    capacity_run, _ = run_snippet(SNIPPETS / "capacity.py")
    capacity = capacity_run["capacity"]
    record_image("fill", frame_png(capacity_run["fill"], OUT / "fill.png"))
    summary = capacity.summary.sort("replication")
    numbers["capacity"] = {
        "scenarios": list(capacity.experiments),
        "runs": per_run(capacity),
        "fill": intervals(capacity, "fill_rate", "Factory"),
        "ratio": intervals(capacity, "bullwhip_ratio", "Factory"),
        "job_time": {
            row["scenario"]: [row["mean"], row["lower"], row["upper"], row["observed_runs"]]
            for row in capacity.intervals("mean_flow_time").to_dicts()
        },
        "brewing_utilization": capacity_run["brewing"].stations.row(0, named=True)["utilization"],
        "brewing_station": capacity_run["brewing"].stations.row(0, named=True)["station"],
        "job_runs": {
            name: column(summary.filter(pl.col("scenario") == name), "mean_flow_time") for name in capacity.experiments
        },
    }
    brewing = ROOT / "output" / "supply" / "brewing.html"
    record_image(
        "production",
        shoot(brewing, OUT / "production.png", selector="#production-section #queues", viewport=(900, 900), wait_ready=True),
    )
    write_numbers(OUT, numbers)


if __name__ == "__main__":
    main()
