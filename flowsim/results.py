"""Raw records and duration-weighted summaries with explicit censoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
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
STATION_SCHEMA = {
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
}
# State counts integrated over time for the station table.
AREA_FIELDS = [
    "waiting",
    "busy",
    "processing",
    "blocked",
    "down",
    "scheduled",
    "available",
    "outside",
]


class Status(StrEnum):
    """A customer's status, as written to the customers table."""

    OUTSIDE = "outside"
    WAITING = "waiting"
    IN_SERVICE = "in_service"
    BLOCKED = "blocked"
    PAUSED = "paused"
    REJECTED = "rejected"
    COMPLETED = "completed"


class Phase(StrEnum):
    """A server's phase. Activity rows record every phase except idle."""

    IDLE = "idle"
    PROCESSING = "processing"
    BLOCKED = "blocked"
    PAUSED = "paused"


# The run builds one record per row, and each record's fields equal its schema's
# columns in order (tests check this). Slots make a misspelled field an error
# rather than a silent extra key.
@dataclass(
    slots=True,
    kw_only=True,
)
class _Customer:
    customer_id: int
    source: str
    arrival_time: float
    exit_time: float | None = None
    flow_time: float | None = None
    total_wait: float = 0.0
    total_blocked: float = 0.0
    admitted: bool = False
    admission_time: float | None = None
    outside_wait: float | None = None
    # The customer's process sets a status when it starts, at the arrival time.
    status: Status | None = None
    station: str | None = None


@dataclass(
    slots=True,
    kw_only=True,
)
class _Visit:
    customer_id: int
    source: str
    station: str
    arrival_time: float
    service_start: float | None = None
    service_end: float | None = None
    departure_time: float | None = None
    server_id: int | None = None
    blocked_time: float | None = None
    wait_time: float | None = None
    service_time: float


@dataclass(
    slots=True,
    kw_only=True,
)
class _State:
    station: str
    time: float
    waiting: int
    busy: int
    processing: int
    blocked: int
    paused: int
    down: int
    scheduled: int
    available: int
    outside: int


@dataclass(
    slots=True,
    kw_only=True,
)
class _Activity:
    customer_id: int
    station: str
    server_id: int
    state: Phase
    start: float
    end: float | None = None


@dataclass(
    slots=True,
    kw_only=True,
)
class _Failure:
    station: str
    server_id: int
    failure_time: float
    time_to_failure: float
    repair_time: float
    repair_end: float | None = None


def _frame(records: list, schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Build a table from records, reading each column by its field name.

    Polars would match dataclass fields to the schema by position and cast
    mismatches silently, so the columns are gathered by name instead.
    """
    return pl.DataFrame(
        data={
            column: [getattr(record, column) for record in records] for column in schema
        },
        schema=schema,
    )


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


def _run_settings(run: Results) -> tuple:
    """Return the settings that pooled or compared runs must share."""
    return (run.duration, run.warmup, run.drain, run.time_unit)


def _write_metadata(path: str | Path, data: dict) -> None:
    """Write export metadata as JSON, stamped with the FlowSim version."""
    from flowsim import __version__

    write_text(path, json.dumps({"flowsim_version": __version__, **data}, indent=2))


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
        customers: list[_Customer],
        visits: list[_Visit],
        states: list[_State],
        activities: list[_Activity],
        failures: list[_Failure],
        definitions: dict,
        capacities: dict[str, int],
        duration: float,
        end_time: float,
        drain: bool,
        closing_states: dict[str, _State],
        warmup: float,
        time_unit: str,
        seed: int,
        graph: nx.DiGraph,
        definition: tuple,
    ):
        self.customers = _frame(customers, CUSTOMER_SCHEMA)
        self.visits = _frame(visits, VISIT_SCHEMA)
        self.states = _frame(states, STATE_SCHEMA)
        self.activities = _frame(activities, ACTIVITY_SCHEMA)
        self.failures = _frame(failures, FAILURE_SCHEMA)
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
        # Experiment pools only runs whose model definitions match.
        self._definition = definition
        self.stations = self._station_metrics()
        self.summary = self._system_metrics()

    def _station_areas(self) -> pl.DataFrame:
        """Integrate each station's state counts over [warmup, duration).

        A state row holds until the station's next row, so its width is the
        part of that span inside the window. Areas have units customer*time
        and server*time. The largest queue counts only rows with positive width.
        """
        width = (
            (
                pl.col("time").shift(-1).over("station").clip(upper_bound=self.duration)
                - pl.col("time").clip(lower_bound=self.warmup)
            )
            .clip(lower_bound=0)
            .fill_null(0)
        )
        return (
            self.states.with_columns(width.alias("width"))
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
            )
        )

    def _station_counts(self) -> pl.DataFrame:
        """Count each station's visits in the window and its closing states."""

        def in_window(column: str) -> pl.Expr:
            return pl.col(column).is_between(
                lower_bound=self.warmup,
                upper_bound=self.duration,
                closed="left",
            )

        # Waits belong to station arrivals at or after warm-up, with no upper
        # bound, so drained runs include arrivals after closing.
        cohort = pl.col("arrival_time") >= self.warmup
        waits = pl.col("wait_time").filter(cohort)
        visits = self.visits.group_by("station").agg(
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
        closing = _frame(list(self.closing_states.values()), STATE_SCHEMA).select(
            "station",
            pl.col("waiting").alias("waiting_at_close"),
            pl.col("busy").alias("occupied_at_close"),
            pl.col("blocked").alias("blocked_at_close"),
            pl.col("paused").alias("paused_at_close"),
            pl.col("outside").alias("outside_at_close"),
        )
        final = self.states.group_by(
            "station",
            maintain_order=True,
        ).agg(
            pl.col("waiting").last().alias("waiting_at_end"),
            pl.col("busy").last().alias("occupied_at_end"),
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
            closing.join(
                other=visits,
                on="station",
                how="left",
                maintain_order="left",
            )
            .join(
                other=final,
                on="station",
                how="left",
                maintain_order="left",
            )
            .with_columns(pl.col(counts).fill_null(0))
        )

    def _station_metrics(self) -> pl.DataFrame:
        window = self.duration - self.warmup
        # Utilization is server*time / (servers*time), dimensionless.
        installed = pl.col("capacity") * window
        stations = (
            pl.DataFrame(
                data={
                    "station": list(self.capacities),
                    "capacity": list(self.capacities.values()),
                },
                schema={"station": pl.String, "capacity": pl.Int64},
            )
            .join(
                other=self._station_counts(),
                on="station",
                how="left",
                maintain_order="left",
            )
            .join(
                other=self._station_areas(),
                on="station",
                how="left",
                maintain_order="left",
            )
        )
        return stations.with_columns(
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
        ).select(
            [pl.col(column).cast(dtype) for column, dtype in STATION_SCHEMA.items()]
        )

    def _system_metrics(self) -> pl.DataFrame:
        eligible = self.customers.filter(pl.col("status") != Status.REJECTED)
        cohort = eligible.filter(pl.col("arrival_time") >= self.warmup)
        finished = cohort.filter(pl.col("status") == Status.COMPLETED)
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
                        (pl.col("status") == Status.REJECTED)
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
        metadata = {
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
        _write_metadata(destination / "metadata.json", metadata)
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
        # The model check below also covers station names and capacities.
        if any(_run_settings(run) != _run_settings(runs[0]) for run in runs):
            raise ValueError(
                "Replications need the same duration, warm-up, drain rule, "
                "and time unit."
            )
        if any(run._definition != runs[0]._definition for run in runs):
            raise ValueError(
                "Replications need runs of the same model. Separately built "
                "models count as different when their sampling functions are "
                "different objects, so run every replication from one Model."
            )
        self.runs = runs

    # The pooled tables are built from the runs on each access, so estimates
    # and exports always read the runs' current values.
    @property
    def stations(self) -> pl.DataFrame:
        return pl.concat(
            [
                run.stations.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(self.runs, start=1)
            ]
        )

    @property
    def summary(self) -> pl.DataFrame:
        return pl.concat(
            [
                run.summary.select(
                    pl.lit(index).alias("replication"),
                    pl.all(),
                )
                for index, run in enumerate(self.runs, start=1)
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
