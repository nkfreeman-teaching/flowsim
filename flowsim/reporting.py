"""Interval tables, plots, pages, and exports shared by experiments and comparisons.

Experiment and Comparison call these functions, so the same request gives the
same rows, figure, page, and files in both. A request names a metric and, for
a station or stock-point metric, optionally one location. Without a location,
a station metric covers every station and a stock-point metric covers every
stock point.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping, Sequence
from numbers import Real
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl
from scipy.stats import t

from flowsim._dashboard import build_dashboard, scenario_runs
from flowsim._export import (
    EXPORT_FILE_NAMES,
    export_tables,
    remove_stale_exports,
    require_flowsim_folder,
    write_export,
    write_text,
)
from flowsim._export import request_metadata as _request_metadata
from flowsim.catalog import (
    METRICS,
    SCOPES,
    Inapplicable,
    inapplicable,
    metric_error,
    metric_units,
    scope_name,
    unknown,
)
from flowsim.plots import (
    BLUE,
    STAGE_COLORS,
    base_layout,
    dashed_line,
    label,
)
from flowsim.records import interval_frame
from flowsim.validation import boolean, number

if TYPE_CHECKING:
    from flowsim.results import Experiment, Results


@functools.lru_cache(maxsize=256)
def _t_critical(confidence: float, df: int) -> float:
    return float(t.ppf((1 + confidence) / 2, df=df))


def confidence_level(value: float) -> float:
    level = number(
        value=value,
        label="Confidence level",
        positive=True,
    )
    if level >= 1:
        raise ValueError("Confidence level must be below one.")
    return level


def interval_estimate(values: np.ndarray | list[float], confidence: float) -> dict:
    """Estimate uncertainty across independent finite replication values."""
    array = np.asarray(values, dtype=float)
    values = array[np.isfinite(array)]
    count = len(values)
    mean = float(values.mean()) if count else None
    lower = upper = None
    # Estimates have the metric's units. Standard error divides by sqrt(runs).
    if mean is not None and count >= 2:
        half_width = float(
            _t_critical(confidence, count - 1) * values.std(ddof=1) / np.sqrt(count)
        )
        lower = mean - half_width
        upper = mean + half_width
    return {
        "observed_runs": count,
        "mean": mean,
        "lower": lower,
        "upper": upper,
    }


def location_column(metric: str) -> str:
    """Name the interval table's location column for a metric.

    Stock-point metrics use a stock_point column. Every other metric keeps the
    station column, which is null for a system metric.
    """
    return SCOPES[METRICS[metric].scope].column


def check_request(metric: str, station: str | None, stock_point: str | None) -> None:
    """Reject an unknown metric or a location argument that its scope lacks."""
    if metric not in METRICS:
        raise metric_error(metric)
    scope = METRICS[metric].scope
    kind = scope_name(metric)
    if station is not None and scope != "station":
        raise ValueError(
            f"{metric!r} is a {kind} metric, so it takes no station=. Station "
            "metrics such as 'mean_wait' take station=."
        )
    if stock_point is not None and scope != "stock_point":
        raise ValueError(
            f"{metric!r} is a {kind} metric, so it takes no stock_point=. "
            "Stock-point metrics such as 'fill_rate' take stock_point=."
        )


def locations(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
) -> list[str | None]:
    """Return the locations a checked request covers in one experiment.

    A system metric covers one location, None. A station or stock-point metric
    covers the named location or, when none is named, every one in definition
    order. A metric that the model cannot measure raises Inapplicable.
    """
    # A run records its capacities, and only a comparison's shared settings
    # hold None.
    capacities = experiment.settings.capacities
    assert capacities is not None
    stations = list(capacities)
    stock_points = experiment.stock_point_names
    # The same test Results.report uses, so both agree on what a supply chain is.
    error = inapplicable(
        metric,
        stations=bool(stations),
        stock_points=bool(stock_points),
        supply=experiment.runs[0].supply is not None,
    )
    if error is not None:
        raise error
    scope = METRICS[metric].scope
    if scope == "system":
        return [None]
    if scope == "station":
        names, chosen, kind = stations, station, "station"
    else:
        names, chosen, kind = stock_points, stock_point, "stock point"
    if chosen is None:
        return [*names]
    if chosen not in names:
        raise unknown(
            kind=kind,
            name=chosen,
            choices=names,
        )
    return [chosen]


def scenario_locations(
    experiments: Mapping[str, Experiment],
    metric: str,
    station: str | None,
    stock_point: str | None,
) -> dict[str, list[str | None]]:
    """Return the locations a checked request covers in each scenario.

    A named location must exist in every scenario. Without one, a scenario
    whose model cannot measure the metric adds no station or stock-point rows
    and a row of missing or zero system values, so a comparison of a supply
    chain with and without production stations still reports the jobs of the
    scenarios that have them. The request fails only when no scenario applies.
    """
    found = {}
    skipped = []
    for name, experiment in experiments.items():
        try:
            found[name] = locations(
                experiment=experiment,
                metric=metric,
                station=station,
                stock_point=stock_point,
            )
        except Inapplicable as error:
            if station is not None or stock_point is not None:
                raise ValueError(f"Scenario {name!r}: {error}") from None
            skipped.append(error)
            found[name] = [None] if METRICS[metric].scope == "system" else []
        except ValueError as error:
            raise ValueError(f"Scenario {name!r}: {error}") from None
    if len(skipped) == len(experiments):
        raise skipped[0]
    return found


def run_values(
    experiment: Experiment,
    metric: str,
    names: list[str | None],
) -> dict[str | None, np.ndarray]:
    """Return each location's values, one per replication in replication order."""
    pooled = getattr(experiment, METRICS[metric].table)
    column = location_column(metric)
    expected = list(range(1, len(experiment.runs) + 1))
    values = {}
    for name in names:
        rows = pooled if name is None else pooled.filter(pl.col(column) == name)
        rows = rows.sort("replication")
        if rows.get_column("replication").to_list() != expected:
            raise ValueError("Some replications are missing or duplicated.")
        values[name] = np.asarray(
            rows.get_column(metric).to_numpy(),
            dtype=float,
        )
    return values


def scenario_values(
    experiments: Mapping[str, Experiment],
    metric: str,
    found: Mapping[str, list[str | None]],
) -> dict[str, dict[str | None, np.ndarray]]:
    """Return each scenario's run values at the locations found for it."""
    values = {}
    for name, experiment in experiments.items():
        try:
            values[name] = run_values(
                experiment=experiment,
                metric=metric,
                names=found[name],
            )
        except ValueError as error:
            raise ValueError(f"Scenario {name!r}: {error}") from None
    return values


def estimate_rows(
    values: Mapping[str | None, np.ndarray],
    metric: str,
    level: float,
) -> list[dict]:
    """Estimate one interval per location from its run values."""
    return [
        {
            "metric": metric,
            location_column(metric): name,
            # run_values holds one value per replication.
            "runs": len(runs),
            **interval_estimate(runs, level),
            "confidence": level,
        }
        for name, runs in values.items()
    ]


def experiment_intervals(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    names = locations(
        experiment=experiment,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    return interval_frame(
        rows=estimate_rows(
            values=run_values(
                experiment=experiment,
                metric=metric,
                names=names,
            ),
            metric=metric,
            level=level,
        ),
        keys=["metric", location_column(metric)],
    )


def scenario_intervals(
    values: Mapping[str, Mapping[str | None, np.ndarray]],
    metric: str,
    level: float,
) -> pl.DataFrame:
    """Estimate each scenario's intervals from scenario_values."""
    return interval_frame(
        rows=[
            {"scenario": name, **row}
            for name, runs in values.items()
            for row in estimate_rows(
                values=runs,
                metric=metric,
                level=level,
            )
        ],
        keys=["scenario", "metric", location_column(metric)],
    )


def comparison_intervals(
    experiments: Mapping[str, Experiment],
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    found = scenario_locations(
        experiments=experiments,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    return scenario_intervals(
        values=scenario_values(
            experiments=experiments,
            metric=metric,
            found=found,
        ),
        metric=metric,
        level=level,
    )


def paired_differences(
    experiments: Mapping[str, Experiment],
    values: Mapping[str, Mapping[str | None, np.ndarray]],
    reference: str,
    metric: str,
    level: float,
) -> pl.DataFrame:
    """Estimate each scenario minus the baseline within matched replications.

    The values come from scenario_values. Each scenario is paired with the
    baseline at every location they share. A missing value in either run
    excludes that pair, not other observations.
    """
    column = location_column(metric)
    seeds = [run.settings.seed for run in experiments[reference].runs]
    baseline = values[reference]
    rows = []
    for name, experiment in experiments.items():
        if name == reference:
            continue
        if [run.settings.seed for run in experiment.runs] != seeds:
            raise ValueError("Paired scenarios need identical replication seeds.")
        rows += [
            {
                "scenario": name,
                "baseline": reference,
                "metric": metric,
                column: place,
                "runs": len(experiment.runs),
                **interval_estimate(values[name][place] - baseline[place], level),
                "confidence": level,
            }
            for place in baseline
            if place in values[name]
        ]
    return interval_frame(
        rows=rows,
        keys=["scenario", "baseline", "metric", column],
    )


def comparison_differences(
    experiments: Mapping[str, Experiment],
    reference: str,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> pl.DataFrame:
    level = confidence_level(confidence)
    check_request(
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    found = scenario_locations(
        experiments=experiments,
        metric=metric,
        station=station,
        stock_point=stock_point,
    )
    return paired_differences(
        experiments=experiments,
        values=scenario_values(
            experiments=experiments,
            metric=metric,
            found=found,
        ),
        reference=reference,
        metric=metric,
        level=level,
    )


def metric_axis_parts(
    metric: str,
    place: str | None,
    time_unit: str,
) -> tuple[str, str | None]:
    """Return a metric's axis name with its location, and its units.

    A fraction has no units, so its second part is None.
    """
    text = METRICS[metric].label
    if place is not None:
        text += f" at {place}"
    if METRICS[metric].kind == "fraction":
        return text, None
    return text, f"({metric_units(metric, time_unit)})"


def metric_axis_label(metric: str, place: str | None, time_unit: str) -> str:
    """Name a metric's value axis, with its location and units."""
    name, units = metric_axis_parts(
        metric=metric,
        place=place,
        time_unit=time_unit,
    )
    return name if units is None else f"{name} {units}"


def interval_figure(
    table: pl.DataFrame,
    metric: str,
    time_unit: str,
    *,
    differences: bool = False,
) -> dict:
    """Return each interval-table row as a mean with its confidence limits.

    Rows are scenarios in a comparison and locations in an experiment. When a
    comparison covers several locations, each row names both, and each location
    has its own color. The figure is plain data, as in flowsim.plots.
    """
    column = location_column(metric)
    rows = table.to_dicts()
    places = list(dict.fromkeys(row[column] for row in rows))
    several = len(places) > 1
    scenarios = "scenario" in table.columns

    def row_label(row: dict) -> str:
        place = "System" if row[column] is None else label(row[column])
        if not scenarios:
            return place
        return label(row["scenario"]) + (f"<br>{place}" if several else "")

    data = []
    for index, place in enumerate(places):
        chosen = [row for row in rows if row[column] == place]
        where = "" if place is None else f"<br>{label(place)}"
        color = (
            STAGE_COLORS[index % len(STAGE_COLORS)] if scenarios and several else BLUE
        )
        trace = {
            "type": "scatter",
            "x": [row["mean"] for row in chosen],
            "y": [row_label(row) for row in chosen],
            "name": "System" if place is None else label(place),
            "mode": "markers",
            "marker": {
                "size": 12,
                "color": color,
                "line": {"color": "black", "width": 1},
            },
            "error_x": {
                "type": "data",
                "array": [
                    None if row["upper"] is None else row["upper"] - row["mean"]
                    for row in chosen
                ],
                "thickness": 2.5,
                "width": 5,
            },
            "showlegend": scenarios and several,
            "hovertemplate": (
                f"%{{y}}{'' if scenarios and several else where}"
                "<br>Estimate: %{x:.3f}<extra></extra>"
            ),
        }
        # A system row has no location, and Plotly writes no meta for None.
        if place is not None:
            trace["meta"] = place
        data.append(trace)
    fraction = METRICS[metric].kind == "fraction"
    axis_label = metric_axis_label(
        metric=metric,
        place=places[0] if len(places) == 1 else None,
        time_unit=time_unit,
    )
    if differences:
        axis_label = "Difference in " + axis_label[0].lower() + axis_label[1:]
    if scenarios:
        y_label = "Scenario"
    elif places and places[0] is not None:
        y_label = SCOPES[METRICS[metric].scope].heading
    else:
        y_label = ""
    layout = base_layout(
        x_label=axis_label,
        y_label=y_label,
    )
    layout["height"] = max(240, 150 + 50 * len(rows))
    layout["margin"] = {"l": 155, "r": 35, "t": 35, "b": 80}
    # List rows top to bottom in the order they were defined.
    layout["yaxis"].update(autorange="reversed", automargin=True)
    if fraction:
        layout["xaxis"]["tickformat"] = ".0%"
    figure = {"data": data, "layout": layout}
    if differences:
        dashed_line(figure, 0)
    return figure


def window_text(
    metric: str,
    *,
    duration: float,
    warmup: float,
    drain: bool,
    time_unit: str,
) -> str:
    """Describe the measurement window behind a page's intervals."""
    if METRICS[metric].scope == "stock_point":
        return (
            f"Stock points review each period until {duration:g} {time_unit}. "
            f"Measurement begins at {warmup:g} {time_unit}."
        )
    return (
        f"Operating hours end at {duration:g} {time_unit}. "
        f"Measurement begins at {warmup:g} {time_unit}. "
        + (
            "Arrivals stopped at closing, and the run continued until every "
            "customer who was not rejected had completed service or abandoned."
            if drain
            else "Service stops at closing. Waiting and flow averages include "
            "observed outcomes."
        )
    )


def replication_figure(
    values: Mapping[str | None, list[float | None]],
    scenarios: list[str | None],
    metric: str,
    place: str | None,
    time_unit: str,
) -> dict:
    """Return each replication's value, one marker series per scenario.

    The values map each scenario (None for an experiment) to its runs in
    replication order, and a missing value leaves a gap. A scenario without
    the location has no values. Each point's customdata holds its scenario's
    position in scenarios, the full list, and its replication, both counted
    from 0, which the dashboard uses to open that run. The position also sets
    the color, so a scenario keeps its color at every location.
    """
    data = []
    for scenario, runs in values.items():
        index = scenarios.index(scenario)
        data.append(
            {
                "type": "scatter",
                "x": list(range(1, len(runs) + 1)),
                "y": runs,
                "name": "Runs" if scenario is None else label(scenario),
                "mode": "markers",
                "marker": {
                    "size": 10,
                    "color": STAGE_COLORS[index % len(STAGE_COLORS)],
                    "line": {"color": "black", "width": 1},
                },
                "customdata": [[index, run] for run in range(len(runs))],
                "showlegend": scenario is not None,
                "hovertemplate": (
                    ("" if scenario is None else f"{label(scenario)}<br>")
                    + "Replication %{x}<br>Value: %{y:.3f}<extra></extra>"
                ),
            }
        )
    name, units = metric_axis_parts(
        metric=metric,
        place=place,
        time_unit=time_unit,
    )
    layout = base_layout(
        x_label="Replication",
        y_label=name,
    )
    layout["height"] = 380
    layout["margin"] = {"l": 95, "r": 30, "t": 60, "b": 70}
    if units is not None:
        # The units take a second line, so a long title fits the chart's
        # height. base_layout escapes its labels, so the break is added here.
        layout["yaxis"]["title"]["text"] = f"{label(name)}<br>{label(units)}"
    layout["xaxis"]["rangemode"] = "normal"
    # Plotly labels fractional replications (1.2, 1.4) on a short axis.
    if max((len(runs) for runs in values.values()), default=0) <= 10:
        layout["xaxis"]["dtick"] = 1
    plotted = [value for runs in values.values() for value in runs if value is not None]
    if plotted:
        # A "tozero" range puts a zero value on the plot's lower edge, where
        # Firefox misses a click on its point, so the range pads both ends by
        # 5% of the span from zero to the furthest value (1 if all are zero).
        # Autoscale and double-click return to the same range.
        low = min(0.0, *plotted)
        high = max(0.0, *plotted)
        if high == low:
            high = low + 1.0
        pad = 0.05 * (high - low)
        layout["yaxis"].update(
            range=[low - pad, high + pad],
            autorangeoptions={"minallowed": low - pad, "maxallowed": high + pad},
        )
    if METRICS[metric].kind == "fraction":
        layout["yaxis"]["tickformat"] = ".0%"
    return {"data": data, "layout": layout}


def summary_table(
    experiments: Mapping[str, Experiment],
    metrics: Sequence[str],
    *,
    comparing: bool,
    station: str | None = None,
    stock_point: str | None = None,
    confidence: float = 0.95,
    intervals: bool = False,
    differences: bool = False,
    reference: str | None = None,
) -> pl.DataFrame:
    """Join one or more replication metrics into a wide summary table."""
    intervals = boolean(intervals, "intervals")
    differences = boolean(differences, "differences")
    if isinstance(metrics, str) or not isinstance(metrics, Sequence) or not metrics:
        raise ValueError("metrics must be a nonempty sequence of metric names.")
    seen: list[str] = []
    for name in metrics:
        if not isinstance(name, str) or name not in METRICS:
            raise metric_error(str(name))
        if name in seen:
            raise ValueError(f"Duplicate metric {name!r} in table request.")
        seen.append(name)
    scopes = {METRICS[name].scope for name in seen}
    if (
        "station" in scopes
        and "stock_point" in scopes
        and (station is None or stock_point is None)
    ):
        raise ValueError(
            "Pass station= and stock_point= when mixing station and stock-point "
            "metrics in one table."
        )
    parts: list[tuple[str, pl.DataFrame, list[str]]] = []
    all_keys: list[str] = ["scenario"] if comparing else []
    for name in seen:
        scope = METRICS[name].scope
        loc_station = station if scope == "station" else None
        loc_stock = stock_point if scope == "stock_point" else None
        if comparing and differences:
            assert reference is not None
            frame = comparison_differences(
                experiments=experiments,
                reference=reference,
                metric=name,
                station=loc_station,
                stock_point=loc_stock,
                confidence=confidence,
            )
        elif comparing:
            frame = comparison_intervals(
                experiments=experiments,
                metric=name,
                station=loc_station,
                stock_point=loc_stock,
                confidence=confidence,
            )
        else:
            only = next(iter(experiments.values()))
            frame = experiment_intervals(
                experiment=only,
                metric=name,
                station=loc_station,
                stock_point=loc_stock,
                confidence=confidence,
            )
        keys: list[str] = []
        if comparing:
            keys.append("scenario")
        if scope == "station" and station is None:
            keys.append("station")
        elif scope == "stock_point" and stock_point is None:
            keys.append("stock_point")
        for key in keys:
            if key not in all_keys:
                all_keys.append(key)
        value_exprs = [pl.col("mean").alias(name)]
        if intervals:
            value_exprs += [
                pl.col("lower").alias(f"{name}_lower"),
                pl.col("upper").alias(f"{name}_upper"),
            ]
        parts.append((name, frame.select(*keys, *value_exprs), keys))
    if not all_keys:
        return pl.concat(
            [frame for _, frame, _ in parts],
            how="horizontal",
        )
    # Start from the first table that carries the finest key set.
    parts.sort(key=lambda item: len(item[2]), reverse=True)
    result = parts[0][1]
    ordered_cols = [*all_keys]
    for name in seen:
        ordered_cols.append(name)
        if intervals:
            ordered_cols += [f"{name}_lower", f"{name}_upper"]
    for _, frame, keys in parts[1:]:
        if keys:
            result = result.join(
                other=frame,
                on=keys,
                how="left",
                maintain_order="left",
            )
        else:
            result = result.join(
                other=frame,
                how="cross",
            )
    return result.select(ordered_cols)


def _eval_custom(fn: Callable[[Results], float | None], run: Results) -> float:
    value = fn(run)
    if value is None:
        return float("nan")
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ValueError(
            f"Custom estimator must return a finite number or None, not {value!r}."
        )
    result = float(value)
    if not np.isfinite(result):
        raise ValueError(
            f"Custom estimator must return a finite number or None, not {value!r}."
        )
    return result


def custom_estimate(
    experiments: Mapping[str, Experiment],
    fn: Callable[[Results], float | None],
    *,
    comparing: bool,
    confidence: float = 0.95,
    differences: bool = False,
    reference: str | None = None,
) -> pl.DataFrame:
    """Estimate a user-supplied per-run function across replications or scenarios."""
    if not callable(fn):
        raise ValueError(
            "fn must be a callable taking one Results and returning a number or None."
        )
    level = confidence_level(confidence)
    differences = boolean(differences, "differences")
    values = {
        name: np.array([_eval_custom(fn, run) for run in exp.runs], dtype=float)
        for name, exp in experiments.items()
    }
    schema: dict[str, Any] = {}
    if comparing:
        schema["scenario"] = pl.String
    if comparing and differences:
        schema["baseline"] = pl.String
    schema.update(
        {
            "runs": pl.Int64,
            "observed_runs": pl.Int64,
            "mean": pl.Float64,
            "lower": pl.Float64,
            "upper": pl.Float64,
            "confidence": pl.Float64,
        }
    )
    rows: list[dict[str, Any]] = []
    if comparing and differences:
        assert reference is not None
        base_vals = values[reference]
        base_seeds = [run.settings.seed for run in experiments[reference].runs]
        for name, exp in experiments.items():
            if name == reference:
                continue
            if [run.settings.seed for run in exp.runs] != base_seeds:
                raise ValueError(
                    "Compared scenarios need identical replication seeds to pair "
                    "differences."
                )
            estimate = interval_estimate(values[name] - base_vals, level)
            rows.append(
                {
                    "scenario": name,
                    "baseline": reference,
                    "runs": len(base_vals),
                    **estimate,
                    "confidence": level,
                }
            )
    else:
        for name, vals in values.items():
            estimate = interval_estimate(vals, level)
            row: dict[str, Any] = {
                "runs": len(vals),
                **estimate,
                "confidence": level,
            }
            if comparing:
                row["scenario"] = name
            rows.append(row)
    return pl.DataFrame(
        data=rows,
        schema=schema,
    )


def dashboard(
    experiments: Mapping[str, Experiment],
    *,
    comparing: bool,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
    reference: str | None,
) -> str:
    """Build the offline page of every applicable metric and every kept run."""
    return build_dashboard(
        experiments=experiments,
        comparing=comparing,
        metric=metric,
        station=station,
        stock_point=stock_point,
        level=confidence_level(confidence),
        reference=reference,
        helpers={
            "scenario_locations": scenario_locations,
            "location_column": location_column,
            "scenario_values": scenario_values,
            "run_values": run_values,
            "scenario_intervals": scenario_intervals,
            "paired_differences": paired_differences,
            "interval_figure": interval_figure,
            "replication_figure": replication_figure,
            "window_text": window_text,
        },
    )


def request_metadata(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
) -> dict[str, Any]:
    """Describe an export's request, settings, and replication seeds."""
    return _request_metadata(
        experiment=experiment,
        metric=metric,
        station=station,
        stock_point=stock_point,
        confidence=confidence,
        level=confidence_level(confidence),
    )


__all__ = [
    "EXPORT_FILE_NAMES",
    "confidence_level",
    "dashboard",
    "export_tables",
    "interval_estimate",
    "remove_stale_exports",
    "request_metadata",
    "require_flowsim_folder",
    "scenario_runs",
    "write_export",
    "write_text",
]
