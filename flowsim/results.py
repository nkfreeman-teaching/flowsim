"""Raw records and duration-weighted summaries with explicit censoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import polars as pl
from scipy.stats import t

if TYPE_CHECKING:
    import networkx as nx
    from plotly.graph_objects import Figure

CUSTOMER_SCHEMA = {
    "customer_id": pl.Int64,
    "source": pl.String,
    "arrival_time": pl.Float64,
    "exit_time": pl.Float64,
    "flow_time": pl.Float64,
    "total_wait": pl.Float64,
    "total_blocked": pl.Float64,
    "admitted": pl.Boolean,
    "admission_time": pl.Float64,
    "outside_wait": pl.Float64,
    "status": pl.String,
    "station": pl.String,
}
VISIT_SCHEMA = {
    "customer_id": pl.Int64,
    "source": pl.String,
    "station": pl.String,
    "arrival_time": pl.Float64,
    "service_start": pl.Float64,
    "service_end": pl.Float64,
    "departure_time": pl.Float64,
    "server_id": pl.Int64,
    "blocked_time": pl.Float64,
    "wait_time": pl.Float64,
    "service_time": pl.Float64,
}
STATE_SCHEMA = {
    "station": pl.String,
    "time": pl.Float64,
    "waiting": pl.Int64,
    "busy": pl.Int64,
    "processing": pl.Int64,
    "blocked": pl.Int64,
    "paused": pl.Int64,
    "down": pl.Int64,
    "scheduled": pl.Int64,
    "available": pl.Int64,
    "outside": pl.Int64,
}
ACTIVITY_SCHEMA = {
    "customer_id": pl.Int64,
    "station": pl.String,
    "server_id": pl.Int64,
    "state": pl.String,
    "start": pl.Float64,
    "end": pl.Float64,
}
FAILURE_SCHEMA = {
    "station": pl.String,
    "server_id": pl.Int64,
    "failure_time": pl.Float64,
    "time_to_failure": pl.Float64,
    "repair_time": pl.Float64,
    "repair_end": pl.Float64,
}


@dataclass(frozen=True)
class Metric:
    """A replication metric: its table, its display label, and its kind.

    The kind sets units and number formats: "time", "rate", "fraction",
    "servers", or "customers".
    """

    scope: str
    label: str
    kind: str


METRICS = {
    "mean_total_wait": Metric("system", "Mean total waiting time", "time"),
    "mean_flow_time": Metric("system", "Mean flow time", "time"),
    "throughput": Metric("system", "Throughput during operating hours", "rate"),
    "remaining_at_close": Metric("system", "Customers present at closing", "customers"),
    "completed_at_close": Metric(
        "system", "Customers completed before closing", "customers"
    ),
    "remaining": Metric("system", "Customers unfinished at the end", "customers"),
    "overtime": Metric("system", "Time to finish after closing", "time"),
    "mean_wip": Metric("system", "Time-average customers in the system", "customers"),
    "rejected": Metric("system", "Rejected arrivals", "customers"),
    "admitted": Metric("system", "Admitted customers", "customers"),
    "measurement_rejected": Metric(
        "system", "Rejected arrivals after warm-up", "customers"
    ),
    "measurement_admitted": Metric(
        "system", "Admissions after warm-up, before closing", "customers"
    ),
    "mean_total_blocked": Metric(
        "system", "Mean time blocked between stations", "time"
    ),
    "mean_outside_wait": Metric("system", "Mean waiting time outside", "time"),
    "mean_wait": Metric("station", "Mean station waiting time", "time"),
    "mean_queue": Metric("station", "Time-average customers waiting", "customers"),
    "utilization": Metric("station", "Occupied / installed capacity", "fraction"),
    "p95_wait": Metric("station", "95th percentile station waiting time", "time"),
    "processing_utilization": Metric(
        "station", "Processing / installed capacity", "fraction"
    ),
    "blocking_fraction": Metric("station", "Blocked / installed capacity", "fraction"),
    "downtime_fraction": Metric("station", "Down / installed capacity", "fraction"),
    "staffed_utilization": Metric(
        "station", "Processing / available capacity", "fraction"
    ),
    "mean_scheduled_servers": Metric("station", "Mean scheduled servers", "servers"),
    "mean_available_servers": Metric("station", "Mean available servers", "servers"),
    "mean_outside_queue": Metric(
        "station", "Time-average customers waiting outside", "customers"
    ),
}
SYSTEM_METRICS = [name for name, metric in METRICS.items() if metric.scope == "system"]
STATION_METRICS = [
    name for name, metric in METRICS.items() if metric.scope == "station"
]


def metric_units(metric: str, time_unit: str) -> str:
    return {
        "time": time_unit,
        "rate": f"customers per {time_unit}",
        "fraction": "share of capacity",
        "servers": "servers",
        "customers": "customers",
    }[METRICS[metric].kind]


def confidence_level(value: float) -> float:
    from flowsim.model import number

    level = number(
        value=value,
        label="Confidence level",
        positive=True,
    )
    if level >= 1:
        raise ValueError("Confidence level must be below one.")
    return level


INTERVAL_SCHEMA = {
    "scenario": pl.String,
    "baseline": pl.String,
    "station": pl.String,
    "metric": pl.String,
    "runs": pl.Int64,
    "observed_runs": pl.Int64,
    "mean": pl.Float64,
    "lower": pl.Float64,
    "upper": pl.Float64,
    "confidence": pl.Float64,
}


def interval_frame(rows: list[dict], keys: list[str]) -> pl.DataFrame:
    """Build an interval table whose columns exist even when it has no rows.

    The keys name the identifying columns in display order, and the estimate
    columns from "runs" to "confidence" follow them.
    """
    columns = [*keys, "runs", "observed_runs", "mean", "lower", "upper", "confidence"]
    return pl.DataFrame(
        data=rows,
        schema={column: INTERVAL_SCHEMA[column] for column in columns},
    )


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination.write_text(
        data=text,
        encoding="utf-8",
    )


def interval_estimate(values: np.ndarray, confidence: float) -> dict:
    """Estimate uncertainty across independent finite replication values."""
    values = values[np.isfinite(values)]
    count = len(values)
    mean = float(values.mean()) if count else None
    half_width = None
    # Estimates have the metric's units. Standard error divides by sqrt(runs).
    if count >= 2:
        half_width = float(
            t.ppf((1 + confidence) / 2, df=count - 1)
            * values.std(ddof=1)
            / np.sqrt(count)
        )
    return {
        "observed_runs": count,
        "mean": mean,
        "lower": None if half_width is None else mean - half_width,
        "upper": None if half_width is None else mean + half_width,
    }


class Results:
    def __init__(
        self,
        customers: list[dict],
        visits: list[dict],
        states: list[dict],
        activities: list[dict],
        failures: list[dict],
        definitions: dict,
        capacities: dict[str, int],
        duration: float,
        end_time: float,
        drain: bool,
        closing_states: dict[str, dict],
        warmup: float,
        time_unit: str,
        seed: int,
        graph: nx.DiGraph,
    ):
        self.customers = pl.DataFrame(
            data=customers,
            schema=CUSTOMER_SCHEMA,
        )
        self.visits = pl.DataFrame(
            data=visits,
            schema=VISIT_SCHEMA,
        )
        self.states = pl.DataFrame(
            data=states,
            schema=STATE_SCHEMA,
        )
        self.activities = pl.DataFrame(
            data=activities,
            schema=ACTIVITY_SCHEMA,
        )
        self.failures = pl.DataFrame(
            data=failures,
            schema=FAILURE_SCHEMA,
        )
        self.definitions = definitions
        self.capacities = capacities.copy()
        self.duration = duration
        self.end_time = end_time
        self.drain = drain
        self.closing_states = closing_states
        self.warmup = warmup
        self.time_unit = time_unit
        self.seed = seed
        self.graph = graph.copy()
        self.stations = self._station_metrics()
        self.summary = self._system_metrics()

    def _station_metrics(self) -> pl.DataFrame:
        rows = []
        window = self.duration - self.warmup
        for name, capacity in self.capacities.items():
            history = self.states.filter(pl.col("station") == name).to_dicts()
            queue_area = 0.0
            busy_area = 0.0
            areas = {
                field: 0.0
                for field in [
                    "processing",
                    "blocked",
                    "down",
                    "scheduled",
                    "available",
                    "outside",
                ]
            }
            max_queue = 0
            for current, following in zip(history[:-1], history[1:]):
                width = max(
                    0.0,
                    min(following["time"], self.duration)
                    - max(current["time"], self.warmup),
                )
                # Areas have units customer*time and server*time.
                queue_area += current["waiting"] * width
                busy_area += current["busy"] * width
                for field in areas:
                    areas[field] += current[field] * width
                if width > 0:
                    max_queue = max(max_queue, current["waiting"])
            all_visits = self.visits.filter(pl.col("station") == name)
            visits = all_visits.filter(pl.col("arrival_time") >= self.warmup)
            during_hours = visits.filter(pl.col("arrival_time") < self.duration)
            waits = visits.get_column("wait_time").drop_nulls()
            rows.append(
                {
                    "station": name,
                    "capacity": capacity,
                    "arrivals": during_hours.height,
                    "wait_arrivals": visits.height,
                    "service_starts": all_visits.filter(
                        (pl.col("service_start") >= self.warmup)
                        & (pl.col("service_start") < self.duration)
                    ).height,
                    "service_completions": all_visits.filter(
                        (pl.col("service_end") >= self.warmup)
                        & (pl.col("service_end") < self.duration)
                    ).height,
                    "wait_observations": waits.len(),
                    "waiting_at_close": self.closing_states[name]["waiting"],
                    "occupied_at_close": self.closing_states[name]["busy"],
                    "waiting_at_end": history[-1]["waiting"],
                    "occupied_at_end": history[-1]["busy"],
                    "blocked_at_close": self.closing_states[name]["blocked"],
                    "paused_at_close": self.closing_states[name]["paused"],
                    "outside_at_close": self.closing_states[name]["outside"],
                    "mean_wait": waits.mean(),
                    "p95_wait": waits.quantile(0.95, interpolation="linear"),
                    "mean_queue": queue_area / window,
                    "max_queue": max_queue,
                    # Utilization is server*time / (servers*time), dimensionless.
                    "utilization": busy_area / (capacity * window),
                    "processing_utilization": areas["processing"] / (capacity * window),
                    "blocking_fraction": areas["blocked"] / (capacity * window),
                    "downtime_fraction": areas["down"] / (capacity * window),
                    "mean_scheduled_servers": areas["scheduled"] / window,
                    "mean_available_servers": areas["available"] / window,
                    "mean_outside_queue": areas["outside"] / window,
                    "staffed_utilization": (
                        None
                        if areas["available"] == 0
                        else areas["processing"] / areas["available"]
                    ),
                }
            )
        return pl.DataFrame(
            data=rows,
            schema={
                "station": pl.String,
                "capacity": pl.Int64,
                "arrivals": pl.Int64,
                "wait_arrivals": pl.Int64,
                "service_starts": pl.Int64,
                "service_completions": pl.Int64,
                "wait_observations": pl.Int64,
                "waiting_at_close": pl.Int64,
                "occupied_at_close": pl.Int64,
                "waiting_at_end": pl.Int64,
                "occupied_at_end": pl.Int64,
                "blocked_at_close": pl.Int64,
                "paused_at_close": pl.Int64,
                "outside_at_close": pl.Int64,
                "mean_wait": pl.Float64,
                "p95_wait": pl.Float64,
                "mean_queue": pl.Float64,
                "max_queue": pl.Int64,
                "utilization": pl.Float64,
                "processing_utilization": pl.Float64,
                "blocking_fraction": pl.Float64,
                "downtime_fraction": pl.Float64,
                "mean_scheduled_servers": pl.Float64,
                "mean_available_servers": pl.Float64,
                "mean_outside_queue": pl.Float64,
                "staffed_utilization": pl.Float64,
            },
        )

    def _system_metrics(self) -> pl.DataFrame:
        eligible = self.customers.filter(pl.col("status") != "rejected")
        cohort = eligible.filter(pl.col("arrival_time") >= self.warmup)
        finished = cohort.filter(pl.col("status") == "completed")
        completed = eligible.get_column("exit_time").count()
        rejected = self.customers.height - eligible.height
        exits = self.customers.filter(
            (pl.col("exit_time") >= self.warmup) & (pl.col("exit_time") < self.duration)
        ).height
        completed_at_close = self.customers.filter(
            pl.col("exit_time") < self.duration
        ).height
        window = self.duration - self.warmup
        # Sum each customer's presence clipped to the observation window.
        # Customer*time / time gives the time-average work in process.
        inside = eligible.filter(pl.col("admission_time").is_not_null())
        presence = inside.select(
            (
                pl.col("exit_time")
                .fill_null(self.duration)
                .clip(upper_bound=self.duration)
                - pl.col("admission_time").clip(lower_bound=self.warmup)
            )
            .clip(lower_bound=0)
            .sum()
            .alias("presence")
        ).item()
        return pl.DataFrame(
            {
                "arrivals": [self.customers.height],
                "admitted": [self.customers.filter(pl.col("admitted")).height],
                "admitted_at_close": [
                    inside.filter(pl.col("admission_time") < self.duration).height
                ],
                "outside_at_close": [
                    eligible.filter(
                        pl.col("admission_time").is_null()
                        | (pl.col("admission_time") >= self.duration)
                    ).height
                ],
                "rejected": [rejected],
                "completed": [completed],
                "remaining": [eligible.height - completed],
                "completed_at_close": [completed_at_close],
                "remaining_at_close": [eligible.height - completed_at_close],
                "after_close_completions": [completed - completed_at_close],
                "end_time": [self.end_time],
                "overtime": [self.end_time - self.duration],
                "measurement_arrivals": [
                    self.customers.filter(pl.col("arrival_time") >= self.warmup).height
                ],
                # A rejection happens at arrival, so both counts use the event's
                # own time in [warmup, duration), as measurement_completions does.
                "measurement_rejected": [
                    self.customers.filter(
                        (pl.col("status") == "rejected")
                        & (pl.col("arrival_time") >= self.warmup)
                    ).height
                ],
                "measurement_admitted": [
                    inside.filter(
                        (pl.col("admission_time") >= self.warmup)
                        & (pl.col("admission_time") < self.duration)
                    ).height
                ],
                "cohort_arrivals": [cohort.height],
                "measurement_completions": [exits],
                "cohort_completions": [finished.height],
                "cohort_remaining": [cohort.height - finished.height],
                "mean_flow_time": [finished.get_column("flow_time").mean()],
                "mean_total_wait": [finished.get_column("total_wait").mean()],
                "mean_total_blocked": [finished.get_column("total_blocked").mean()],
                "mean_outside_wait": [finished.get_column("outside_wait").mean()],
                "throughput": [exits / window],
                "mean_wip": [presence / window],
            },
            schema_overrides={
                "mean_flow_time": pl.Float64,
                "mean_total_wait": pl.Float64,
                "mean_total_blocked": pl.Float64,
                "mean_outside_wait": pl.Float64,
            },
        )

    def queue_plot(self) -> Figure:
        from flowsim.plots import queue_plot

        return queue_plot(self)

    def wait_plot(self) -> Figure:
        from flowsim.plots import wait_plot

        return wait_plot(self)

    def utilization_plot(self) -> Figure:
        from flowsim.plots import utilization_plot

        return utilization_plot(self)

    def resource_plot(self) -> Figure:
        from flowsim.plots import resource_plot

        return resource_plot(self)

    def customer_plot(self, customer_id: int) -> Figure:
        from flowsim.plots import customer_plot

        return customer_plot(self, customer_id)

    def viewer(self, path: str | Path | None = None) -> str:
        """Return an offline HTML viewer, optionally saving it to a file."""
        from flowsim.plots import viewer_html

        html = viewer_html(self)
        if path is not None:
            write_text(path, html)
        return html

    def export(self, directory: str | Path) -> Path:
        """Export raw records, metrics, and their measurement definitions."""
        destination = Path(directory)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )
        for name in [
            "customers",
            "visits",
            "states",
            "stations",
            "summary",
            "activities",
            "failures",
        ]:
            getattr(self, name).write_csv(destination / f"{name}.csv")
        from flowsim import __version__

        metadata = {
            "flowsim_version": __version__,
            "time_unit": self.time_unit,
            "duration": self.duration,
            "end_time": self.end_time,
            "drain": self.drain,
            "warmup": self.warmup,
            "seed": self.seed,
            "capacities": self.capacities,
            "definitions": self.definitions,
            "routes": [
                {"from": origin, "to": target, "probability": data["probability"]}
                for origin, target, data in self.graph.edges(data=True)
            ],
            "state_window": "[warmup, duration)",
            "wait_cohort": (
                "Station arrivals at or after warmup with observed service starts, "
                "including downstream arrivals after closing when drained"
            ),
            "flow_cohort": "System arrivals at or after warmup with observed exits",
            "censoring": "Missing starts and exits remain null, never zero",
        }
        write_text(destination / "metadata.json", json.dumps(metadata, indent=2))
        return destination


class Experiment:
    """Independent runs and Student t intervals across replication means."""

    def __init__(self, runs: list[Results]):
        runs = list(runs)
        if len(runs) < 2:
            raise ValueError("An experiment needs at least two runs.")
        if len({run.seed for run in runs}) != len(runs):
            raise ValueError(
                "Replications need distinct seeds. A repeated run is not an "
                "independent observation."
            )

        def settings(run: Results) -> tuple:
            return (
                run.duration,
                run.warmup,
                run.drain,
                run.time_unit,
                tuple(run.capacities.items()),
            )

        if any(settings(run) != settings(runs[0]) for run in runs):
            raise ValueError(
                "Replications need the same duration, warm-up, drain rule, "
                "time unit, and stations."
            )
        self.runs = runs
        self.stations = pl.concat(
            [
                run.stations.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(runs, start=1)
            ]
        )
        self.summary = pl.concat(
            [
                run.summary.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(runs, start=1)
            ]
        )

    def _values(self, metric: str, station: str | None) -> np.ndarray:
        """Return one value per replication, in replication order."""
        if station is None:
            table = self.summary
        else:
            if station not in self.runs[0].capacities:
                raise ValueError(f"Station {station!r} is missing in this experiment.")
            table = self.stations.filter(pl.col("station") == station)
        table = table.sort("replication")
        expected = list(range(1, len(self.runs) + 1))
        if table.get_column("replication").to_list() != expected:
            raise ValueError("Some replications are missing or duplicated.")
        return np.asarray(table.get_column(metric).to_numpy(), dtype=float)

    def intervals(
        self,
        metric: str = "mean_wait",
        *,
        station: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        """Estimate a metric across runs, reporting missing estimates.

        A station metric gives one row per station unless a station is named.
        A system metric gives one row with a null station.
        """
        level = confidence_level(confidence)
        if metric not in METRICS:
            raise ValueError(f"Choose a metric from {list(METRICS)}.")
        if METRICS[metric].scope == "system":
            if station is not None:
                raise ValueError(f"{metric!r} is a system metric with no station.")
            names = [None]
        else:
            names = list(self.runs[0].capacities) if station is None else [station]
        return interval_frame(
            rows=[
                {
                    "station": name,
                    "metric": metric,
                    "runs": len(self.runs),
                    **interval_estimate(self._values(metric, name), level),
                    "confidence": level,
                }
                for name in names
            ],
            keys=["station", "metric"],
        )
