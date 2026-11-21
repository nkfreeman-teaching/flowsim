"""Per-run Polars measure builders for stations, system summary, and stock points."""

from __future__ import annotations

from collections.abc import Mapping

import polars as pl

from flowsim.records import (
    AREA_FIELDS,
    STATION_SCHEMA,
    STOCK_POINT_SCHEMA,
    SUMMARY_SCHEMA,
    Status,
    _State,
)


def station_metrics(
    *,
    visits_df: pl.DataFrame,
    states_df: pl.DataFrame,
    capacities: Mapping[str, int],
    closing_states: Mapping[str, _State],
    warmup: float,
    duration: float,
) -> pl.DataFrame:
    """Summarize each station over [warmup, duration) and its wait cohort."""
    if not capacities:
        return pl.DataFrame(schema=STATION_SCHEMA)
    window = duration - warmup
    # Utilization is server*time / (servers*time), dimensionless.
    installed = pl.col("capacity") * window
    names = list(capacities)
    closing_rows = [closing_states[name] for name in names]
    base = pl.DataFrame(
        data={
            "station": names,
            "capacity": list(capacities.values()),
            "waiting_at_close": [row.waiting for row in closing_rows],
            "occupied_at_close": [row.busy for row in closing_rows],
            "blocked_at_close": [row.blocked for row in closing_rows],
            "paused_at_close": [row.paused for row in closing_rows],
            "outside_at_close": [row.outside for row in closing_rows],
        },
        schema={
            "station": pl.String,
            "capacity": pl.Int64,
            "waiting_at_close": pl.Int64,
            "occupied_at_close": pl.Int64,
            "blocked_at_close": pl.Int64,
            "paused_at_close": pl.Int64,
            "outside_at_close": pl.Int64,
        },
    )

    def in_window(column: str) -> pl.Expr:
        return pl.col(column).is_between(
            lower_bound=warmup,
            upper_bound=duration,
            closed="left",
        )

    # Waits belong to station arrivals at or after warm-up, with no upper
    # bound, so drained runs include arrivals after closing.
    cohort = pl.col("arrival_time") >= warmup
    waits = pl.col("wait_time").filter(cohort)
    visits = (
        visits_df.lazy()
        .group_by("station")
        .agg(
            in_window("arrival_time").sum().alias("arrivals"),
            cohort.sum().alias("wait_arrivals"),
            in_window("service_start").sum().alias("service_starts"),
            in_window("service_end").sum().alias("service_completions"),
            waits.count().alias("wait_observations"),
            waits.mean().alias("mean_wait"),
            waits.quantile(
                quantile=0.95,
                interpolation="linear",
            ).alias("p95_wait"),
        )
    )
    width = (
        (
            pl.col("time").shift(-1).over("station").clip(upper_bound=duration)
            - pl.col("time").clip(lower_bound=warmup)
        )
        .clip(lower_bound=0)
        .fill_null(0)
    )
    state_agg = (
        states_df.lazy()
        .with_columns(width.alias("width"))
        .group_by(
            "station",
            maintain_order=True,
        )
        .agg(
            *[
                (pl.col(field) * pl.col("width")).sum().alias(f"{field}_area")
                for field in AREA_FIELDS
            ],
            pl.col("waiting")
            .filter(pl.col("width") > 0)
            .max()
            .fill_null(0)
            .alias("max_queue"),
            pl.col("waiting").last().alias("waiting_at_end"),
            pl.col("busy").last().alias("occupied_at_end"),
        )
    )
    counts = [
        "arrivals",
        "wait_arrivals",
        "service_starts",
        "service_completions",
        "wait_observations",
    ]
    # A station no customer visited has zero counts and no waits.
    return (
        base.lazy()
        .join(
            other=visits,
            on="station",
            how="left",
            maintain_order="left",
        )
        .join(
            other=state_agg,
            on="station",
            how="left",
            maintain_order="left",
        )
        .with_columns(
            pl.col(counts).fill_null(0),
            (pl.col("waiting_area") / window).alias("mean_queue"),
            (pl.col("busy_area") / installed).alias("utilization"),
            (pl.col("processing_area") / installed).alias("processing_utilization"),
            (pl.col("blocked_area") / installed).alias("blocking_fraction"),
            (pl.col("down_area") / installed).alias("downtime_fraction"),
            (pl.col("scheduled_area") / window).alias("mean_scheduled_servers"),
            (pl.col("available_area") / window).alias("mean_available_servers"),
            (pl.col("outside_area") / window).alias("mean_outside_queue"),
            pl.when(pl.col("available_area") == 0)
            .then(None)
            .otherwise(pl.col("processing_area") / pl.col("available_area"))
            .alias("staffed_utilization"),
        )
        .select(
            [pl.col(column).cast(dtype) for column, dtype in STATION_SCHEMA.items()]
        )
        .collect()
    )


def system_metrics(
    *,
    customers_df: pl.DataFrame,
    warmup: float,
    duration: float,
    end_time: float,
) -> pl.DataFrame:
    """Summarize system-wide arrivals, completions, flow times, and WIP."""
    if customers_df.is_empty():
        empty: dict[str, list[object]] = {
            column: [0] if dtype == pl.Int64 else [None]
            for column, dtype in SUMMARY_SCHEMA.items()
        }
        empty["end_time"] = [end_time]
        empty["overtime"] = [end_time - duration]
        empty["throughput"] = [0.0]
        empty["mean_wip"] = [0.0]
        return pl.DataFrame(
            data=empty,
            schema=SUMMARY_SCHEMA,
        )
    # One query over the customers table gives every count.
    status = pl.col("status")
    eligible = status != Status.REJECTED
    cohort = eligible & (pl.col("arrival_time") >= warmup)
    finished = cohort & (status == Status.COMPLETED)
    inside = eligible & pl.col("admission_time").is_not_null()
    abandon = pl.col("abandon_time")
    admission = pl.col("admission_time")
    exit_time = pl.col("exit_time")
    # Each customer's presence clipped to the observation window.
    # Customer*time / time gives the time-average work in process.
    presence = (
        pl.coalesce("exit_time", "abandon_time")
        .fill_null(duration)
        .clip(upper_bound=duration)
        - admission.clip(lower_bound=warmup)
    ).clip(lower_bound=0)
    counts = customers_df.select(
        pl.len().alias("arrivals"),
        pl.col("admitted").sum().alias("admitted"),
        (inside & (admission < duration)).sum().alias("admitted_at_close"),
        (
            eligible
            & (admission.is_null() | (admission >= duration))
            & (abandon.is_null() | (abandon >= duration))
        )
        .sum()
        .alias("outside_at_close"),
        eligible.sum().alias("eligible"),
        exit_time.filter(eligible).count().alias("completed"),
        # Abandoned customers leave without service, so they are neither
        # completed nor remaining, and their waits stay out of the averages.
        abandon.filter(eligible).count().alias("abandoned"),
        (eligible & (abandon < duration)).sum().alias("abandoned_at_close"),
        abandon.filter(cohort).count().alias("cohort_abandoned"),
        (pl.col("arrival_time") >= warmup).sum().alias("measurement_arrivals"),
        ((exit_time >= warmup) & (exit_time < duration)).sum().alias("exits"),
        (exit_time < duration).sum().alias("completed_at_close"),
        # A rejection happens at arrival, so both counts use the event's
        # own time in [warmup, duration), as measurement_completions does.
        ((status == Status.REJECTED) & (pl.col("arrival_time") >= warmup))
        .sum()
        .alias("measurement_rejected"),
        # Abandonments count by their own time, like completions. The
        # rate instead follows the customers who arrived after warm-up.
        (eligible & (abandon >= warmup) & (abandon < duration))
        .sum()
        .alias("measurement_abandoned"),
        (inside & (admission >= warmup) & (admission < duration))
        .sum()
        .alias("measurement_admitted"),
        cohort.sum().alias("cohort"),
        finished.sum().alias("finished"),
    ).row(0, named=True)
    # Float sums and means stay on filtered frames, as before, since a
    # filtered expression can sum in a different order (last-bit changes).
    done = customers_df.filter(finished)
    for column in ["flow_time", "total_wait", "total_blocked", "outside_wait"]:
        counts[f"mean_{column}"] = done.get_column(column).mean()
    counts["presence"] = customers_df.filter(inside).select(presence.sum()).item()
    window = duration - warmup
    rejected = counts["arrivals"] - counts["eligible"]
    values = {
        "arrivals": [counts["arrivals"]],
        "admitted": [counts["admitted"]],
        "admitted_at_close": [counts["admitted_at_close"]],
        "outside_at_close": [counts["outside_at_close"]],
        "rejected": [rejected],
        "abandoned": [counts["abandoned"]],
        "completed": [counts["completed"]],
        "remaining": [counts["eligible"] - counts["completed"] - counts["abandoned"]],
        "completed_at_close": [counts["completed_at_close"]],
        "remaining_at_close": [
            counts["eligible"]
            - counts["completed_at_close"]
            - counts["abandoned_at_close"]
        ],
        "after_close_completions": [counts["completed"] - counts["completed_at_close"]],
        "end_time": [end_time],
        "overtime": [end_time - duration],
        "measurement_arrivals": [counts["measurement_arrivals"]],
        "measurement_rejected": [counts["measurement_rejected"]],
        "measurement_abandoned": [counts["measurement_abandoned"]],
        "abandonment_rate": [
            counts["cohort_abandoned"] / counts["measurement_arrivals"]
            if counts["measurement_arrivals"]
            else None
        ],
        "measurement_admitted": [counts["measurement_admitted"]],
        "cohort_arrivals": [counts["cohort"]],
        "measurement_completions": [counts["exits"]],
        "cohort_completions": [counts["finished"]],
        "cohort_remaining": [
            counts["cohort"] - counts["finished"] - counts["cohort_abandoned"]
        ],
        "mean_flow_time": [counts["mean_flow_time"]],
        "mean_total_wait": [counts["mean_total_wait"]],
        "mean_total_blocked": [counts["mean_total_blocked"]],
        "mean_outside_wait": [counts["mean_outside_wait"]],
        "throughput": [counts["exits"] / window],
        "mean_wip": [counts["presence"] / window],
    }
    return pl.DataFrame(
        data={column: values[column] for column in SUMMARY_SCHEMA},
        schema=SUMMARY_SCHEMA,
    )


def stock_point_metrics(
    *,
    inventory_df: pl.DataFrame,
    names: list[str],
    warmup: float,
) -> pl.DataFrame:
    """Summarize each stock point over the review periods in [warmup, duration)."""
    if not names:
        return pl.DataFrame(schema=STOCK_POINT_SCHEMA)
    measured = (
        inventory_df.lazy()
        .filter(pl.col("time") >= warmup)
        .group_by("stock_point")
        .agg(
            pl.len().alias("periods"),
            pl.col("demand").mean().alias("mean_demand"),
            pl.col("order_quantity").mean().alias("mean_order"),
            pl.col("demand").var(ddof=1).alias("demand_variance"),
            pl.col("order_quantity").var(ddof=1).alias("order_variance"),
            pl.col("demand").sum().alias("demanded"),
            pl.col("filled").sum().alias("filled"),
            pl.col("on_hand").mean().alias("mean_on_hand"),
            pl.col("backorders").mean().alias("mean_backorders"),
            pl.col("lost").sum().alias("lost_units"),
        )
    )
    return (
        pl.DataFrame(
            data={"stock_point": names},
            schema={"stock_point": pl.String},
        )
        .lazy()
        .join(
            other=measured,
            on="stock_point",
            how="left",
            maintain_order="left",
        )
        .with_columns(
            pl.when(pl.col("demand_variance") > 0)
            .then(pl.col("order_variance") / pl.col("demand_variance"))
            .alias("bullwhip_ratio"),
            pl.when(pl.col("demanded") > 0)
            .then(pl.col("filled") / pl.col("demanded"))
            .alias("fill_rate"),
            pl.col("periods").fill_null(0),
        )
        .select(
            [pl.col(column).cast(dtype) for column, dtype in STOCK_POINT_SCHEMA.items()]
        )
        .collect()
    )
