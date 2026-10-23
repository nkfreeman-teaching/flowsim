"""Run examples, check their accounting, and export browser viewers."""

from pathlib import Path

import polars as pl

from examples.models import (
    branching_service,
    deterministic_queue,
    service_network,
)


def main():
    output = Path("output")
    scenarios = [
        ("deterministic", deterministic_queue(), 7),
        ("two-stage", service_network(), 480),
        ("branching", branching_service(), 480),
    ]
    for name, model, duration in scenarios:
        results = model.run(
            duration=duration,
            seed=42,
        )
        results.export(output / name)
        results.viewer(output / name / "viewer.html")
        model.diagram().write_html(
            file=output / name / "network.html",
            include_plotlyjs=True,
        )
        summary = results.summary.to_dicts()[0]
        assert summary["arrivals"] == summary["completed"] + summary["remaining"]
        print(f"\n{name}")
        print(
            results.summary.select(
                "arrivals",
                "completed",
                "remaining",
                "mean_total_wait",
                "mean_flow_time",
            )
        )
        print(
            results.stations.select(
                "station",
                "capacity",
                "mean_wait",
                "mean_queue",
                "utilization",
            )
        )

    comparison = []
    for capacity in [1, 2, 3]:
        trials = service_network(service_capacity=capacity).experiment(
            duration=480,
            replications=12,
            seed=42,
        )
        interval = (
            trials.intervals()
            .filter(pl.col("station") == "Service")
            .with_columns(pl.lit(capacity).alias("servers"))
        )
        comparison.append(interval)
        if capacity == 2:
            trials.intervals().write_csv(output / "replication-intervals.csv")
    staffing = pl.concat(comparison)
    staffing.write_csv(output / "staffing-comparison.csv")
    print("\nMean wait at the Service station across 12 replications")
    print(
        staffing.select(
            "servers",
            "mean",
            "lower",
            "upper",
        )
    )
    print(f"\nViewers and raw records were written to {output.resolve()}.")


if __name__ == "__main__":
    main()
