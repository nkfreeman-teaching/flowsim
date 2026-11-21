"""Offline HTML dashboard builder for experiments and scenario comparisons."""

from __future__ import annotations

import base64
import functools
import gzip
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import polars as pl

from flowsim.catalog import (
    METRICS,
    SCOPES,
    Inapplicable,
    metric_units,
)
from flowsim.plots import (
    building_page,
    fill_template,
    page_json,
    page_parts,
    run_payload,
)

if TYPE_CHECKING:
    from flowsim.results import Experiment


# Metric menu headings, in catalog order.
_GROUPS = [(scope, facts.menu) for scope, facts in SCOPES.items()]


def _extract_table_arrays(
    frame: pl.DataFrame,
    *,
    expected: list[int],
    key_col: str | None,
    location_label: str,
) -> dict[str | None, dict[str, np.ndarray]]:
    """Extract every metric column once per location in replication order."""
    result: dict[str | None, dict[str, np.ndarray]] = {}
    if key_col is None:
        ordered = frame.sort("replication")
        if ordered.get_column("replication").to_list() != expected:
            raise ValueError(
                "Each replication needs one row in summary; found missing or "
                "duplicate rows."
            )
        result[None] = {
            col: ordered.get_column(col)
            .cast(pl.Float64)
            .fill_null(float("nan"))
            .to_numpy()
            for col in ordered.columns
            if col != "replication" and ordered.schema[col].is_numeric()
        }
        return result
    if frame.is_empty():
        return result
    for key, sub in frame.partition_by(
        key_col,
        as_dict=True,
        maintain_order=True,
    ).items():
        place = str(key[0])
        ordered = sub.sort("replication")
        if ordered.get_column("replication").to_list() != expected:
            raise ValueError(
                f"Each replication needs one row for {location_label} {place!r}; "
                "found missing or duplicate rows."
            )
        result[place] = {
            col: ordered.get_column(col)
            .cast(pl.Float64)
            .fill_null(float("nan"))
            .to_numpy()
            for col in ordered.columns
            if col not in {"replication", key_col} and ordered.schema[col].is_numeric()
        }
    return result


class _CachedExperiment:
    """Snapshot one Experiment's pooled tables and NumPy columns once per page."""

    def __init__(self, experiment: Experiment):
        self._experiment = experiment
        self.runs = experiment.runs
        self.settings = experiment.settings
        self.stock_point_names = experiment.stock_point_names
        self.seeds = [run.settings.seed for run in self.runs]
        self._expected = list(range(1, len(self.runs) + 1))

    @functools.cached_property
    def summary(self) -> pl.DataFrame:
        return self._experiment.summary

    @functools.cached_property
    def stations(self) -> pl.DataFrame:
        return self._experiment.stations

    @functools.cached_property
    def stock_points(self) -> pl.DataFrame:
        return self._experiment.stock_points

    @functools.cached_property
    def arrays(self) -> dict[str, dict[str | None, dict[str, np.ndarray]]]:
        return {
            "summary": _extract_table_arrays(
                self.summary,
                expected=self._expected,
                key_col=None,
                location_label="system",
            ),
            "stations": _extract_table_arrays(
                self.stations,
                expected=self._expected,
                key_col="station",
                location_label="station",
            ),
            "stock_points": _extract_table_arrays(
                self.stock_points,
                expected=self._expected,
                key_col="stock_point",
                location_label="stock point",
            ),
        }


def scenario_runs(
    values: Mapping[str, Mapping[str | None, np.ndarray]],
    place: str | None,
) -> dict[str | None, list[float | None]]:
    """Return each scenario's run values at one location, None where missing."""
    return {
        name: [
            None if not math.isfinite(value) else float(value) for value in runs[place]
        ]
        for name, runs in values.items()
        if place in runs
    }


def _gzip_base64(text: str) -> str:
    return base64.b64encode(
        gzip.compress(text.encode("utf-8"), compresslevel=6)
    ).decode("ascii")


def metric_entry(
    experiments: Mapping[str, _CachedExperiment],
    metric: str,
    comparing: bool,
    level: float,
    *,
    scenario_locations,
    location_column,
    interval_estimate,
    interval_figure,
    replication_figure,
    window_text,
) -> dict[str, Any] | None:
    """Return one metric's dashboard views, one per location, or None."""
    try:
        found = scenario_locations(
            experiments=experiments,
            metric=metric,
            station=None,
            stock_point=None,
        )
    except Inapplicable:
        return None
    places = list(dict.fromkeys(place for chosen in found.values() for place in chosen))
    first = next(iter(experiments.values()))
    settings = first.settings
    column = location_column(metric)
    table_name = METRICS[metric].table
    values: dict[str, dict[str | None, np.ndarray]] = {}
    for name, chosen in found.items():
        table_arrays = experiments[name].arrays[table_name]
        values[name] = {place: table_arrays[place][metric] for place in chosen}

    views = []
    for place in places:
        chosen_rows: list[dict[str, Any]] = []
        for name, by_place in values.items():
            if place not in by_place:
                continue
            runs_arr = by_place[place]
            est = interval_estimate(runs_arr, level)
            row: dict[str, Any] = {}
            if comparing:
                row["scenario"] = name
            row[column] = place
            row["metric"] = metric
            row["runs"] = len(runs_arr)
            row.update(est)
            row["confidence"] = level
            chosen_rows.append(row)

        runs_map = scenario_runs(values=values, place=place)
        changes: dict[str, dict[str, Any] | None] = {}
        if comparing:
            for baseline in experiments:
                if baseline not in values or place not in values[baseline]:
                    changes[baseline] = None
                    continue
                base_arr = values[baseline][place]
                base_seeds = experiments[baseline].seeds
                diff_rows: list[dict[str, Any]] = []
                for name, by_place in values.items():
                    if name == baseline or place not in by_place:
                        continue
                    if experiments[name].seeds != base_seeds:
                        raise ValueError(
                            "Compared scenarios need identical replication seeds "
                            "to pair differences."
                        )
                    est = interval_estimate(by_place[place] - base_arr, level)
                    diff_rows.append(
                        {
                            "scenario": name,
                            "baseline": baseline,
                            column: place,
                            "metric": metric,
                            "runs": len(base_arr),
                            **est,
                            "confidence": level,
                        }
                    )
                changes[baseline] = (
                    None
                    if not diff_rows
                    else {
                        "intervals": diff_rows,
                        "figure": interval_figure(
                            table=diff_rows,
                            metric=metric,
                            time_unit=settings.time_unit,
                            differences=True,
                        ),
                    }
                )
        views.append(
            {
                "title": METRICS[metric].label
                + ("" if place is None else f" at {place}"),
                "intervals": chosen_rows,
                "means": interval_figure(
                    table=chosen_rows,
                    metric=metric,
                    time_unit=settings.time_unit,
                ),
                "runs": replication_figure(
                    values=runs_map if comparing else {None: runs_map[""]},
                    scenarios=list(experiments) if comparing else [None],
                    metric=metric,
                    place=place,
                    time_unit=settings.time_unit,
                ),
                "changes": changes,
            }
        )
    kind = METRICS[metric].kind
    return {
        "name": metric,
        "label": METRICS[metric].label,
        "scope": METRICS[metric].scope,
        "location_column": column,
        "fraction": kind == "fraction",
        "units": "percent"
        if kind == "fraction"
        else metric_units(metric, settings.time_unit),
        "meaning": METRICS[metric].meaning,
        "window": window_text(
            metric,
            duration=settings.duration,
            warmup=settings.warmup,
            drain=settings.drain,
            time_unit=settings.time_unit,
        ),
        "locations": places,
        "views": views,
    }


def build_dashboard(
    experiments: Mapping[str, Experiment],
    *,
    comparing: bool,
    metric: str,
    station: str | None,
    stock_point: str | None,
    level: float,
    reference: str | None,
    helpers: dict[str, Any],
) -> str:
    """Build the offline page of every applicable metric and every kept run."""
    cached = {
        name: _CachedExperiment(experiment) for name, experiment in experiments.items()
    }
    first_run = next(iter(cached.values())).runs[0]
    has_supply = any(exp.runs[0].supply is not None for exp in cached.values())
    has_service = any(exp.runs[0].supply is None for exp in cached.values())
    model_kind = (
        "supply"
        if has_supply and not has_service
        else ("mixed" if has_supply and has_service else "service")
    )
    # Run views built here hold their record columns as typed arrays.
    with building_page():
        entries = [
            entry
            for name in METRICS
            if (
                entry := metric_entry(
                    experiments=cached,
                    metric=name,
                    comparing=comparing,
                    level=level,
                    **helpers,
                )
            )
            is not None
        ]
        records = all(
            run.records_kept
            for experiment in cached.values()
            for run in experiment.runs
        )
        runs = []
        run_data = []
        for scenario, (name, experiment) in enumerate(cached.items()):
            prefix = f"{name}, replication" if comparing else "Replication"
            runs.append(
                [
                    {"label": f"{prefix} {index} (seed {run.settings.seed})"}
                    for index, run in enumerate(experiment.runs, start=1)
                ]
            )
            if records:
                run_data += [
                    f'<script id="run-{scenario}-{index}" '
                    'type="application/gzip;base64">'
                    f"{_gzip_base64(page_json(run_payload(run)))}</script>"
                    for index, run in enumerate(experiment.runs)
                ]
        payload = {
            "kind": model_kind,
            "time_unit": first_run.settings.time_unit,
            "scenarios": list(cached) if comparing else [None],
            "replications": len(next(iter(cached.values())).runs),
            "confidence_text": f"{level * 100:g}%",
            "groups": _GROUPS,
            "metrics": entries,
            "initial": {
                "metric": metric,
                "location": {"station": station, "stock_point": stock_point}.get(
                    METRICS[metric].scope
                ),
                "baseline": reference,
            },
            "records": records,
            "runs": runs,
        }
    return fill_template(
        "dashboard.html",
        {
            **page_parts(),
            "HEADING": "Scenario comparison" if comparing else "Replication intervals",
            "DASHBOARD_JSON": page_json(payload),
            "RUN_DATA": "\n".join(run_data),
        },
    )
