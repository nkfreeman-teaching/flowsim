"""A worked staffing exercise for an eight-hour service day."""

import math
from pathlib import Path

import polars as pl

from flowsim import compare

# `python -m examples.service_day` runs this file inside the examples package.
# Marimo puts only the notebook's own folder on the import path, so the lesson
# imports this file as a top-level module named service_day.
if __package__:
    from .models import service_network
else:
    from models import service_network

# The exercise targets, stated once for this script, the lesson, and the README.
DAY_LENGTH = 480  # operating minutes per simulated day
DAYS = 20  # simulated days per staffing level
WAIT_TARGET = 5  # maximum mean total wait, in minutes
OVERTIME_LIMIT = 30  # minutes after closing to finish every admitted customer
ON_TIME_SHARE = 0.9  # share of days that must finish within the limit


def staffing_exercise(replications: int = DAYS, seed: int = 42):
    """Compare the lowest staffing level meeting two finite-experiment targets."""
    scenarios = {
        "One server": service_network(service_capacity=1),
        "Two servers": service_network(service_capacity=2),
        "Three servers": service_network(service_capacity=3),
    }
    comparison = compare(
        scenarios=scenarios,
        duration=DAY_LENGTH,
        replications=replications,
        seed=seed,
        drain=True,
    )
    # Both targets describe this finite experiment. The 90% requirement is an
    # observed day count, not a confidence bound on a population probability.
    rows = []
    intervals = comparison.intervals().to_dicts()
    for servers, row in enumerate(intervals, start=1):
        runs = comparison.experiments[row["scenario"]].summary
        on_time = runs.filter(pl.col("overtime") <= OVERTIME_LIMIT).height
        rows.append(
            {
                "scenario": row["scenario"],
                "servers": servers,
                "mean_wait_minutes": row["mean"],
                "wait_lower": row["lower"],
                "wait_upper": row["upper"],
                "days_finished_on_time": on_time,
                "days": replications,
                "meets_targets": (
                    row["mean"] is not None
                    and row["mean"] <= WAIT_TARGET
                    and on_time >= math.ceil(ON_TIME_SHARE * replications)
                ),
            }
        )
    return comparison, pl.DataFrame(rows)


def main():
    comparison, decision = staffing_exercise()
    output = Path("output/service-day")
    comparison.export(output)
    comparison.viewer(output / "comparison.html")
    comparison.viewer(
        path=output / "overtime-comparison.html",
        metric="overtime",
    )
    decision.write_csv(output / "staffing-decision.csv")
    for name, experiment in comparison.experiments.items():
        first_day = experiment.runs[0]
        folder = output / name.lower().replace(" ", "-")
        first_day.export(folder)
        first_day.viewer(folder / "viewer.html")
        totals = first_day.summary.to_dicts()[0]
        assert totals["arrivals"] == totals["completed"]
        assert totals["remaining"] == 0
    print("Staffing targets")
    print(decision)
    print("\nPaired differences in mean total wait from one server")
    print(comparison.differences())
    eligible = decision.filter(pl.col("meets_targets"))
    if eligible.height:
        choice = eligible.to_dicts()[0]
        print(f"\nLowest staffing meeting both observed targets: {choice['scenario']}.")
    else:
        print("\nNo staffing level met both observed targets.")
    print(f"Reports and raw first-day records were written to {output.resolve()}.")


if __name__ == "__main__":
    main()
