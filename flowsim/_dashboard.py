"""Offline HTML dashboard builder for experiments and scenario comparisons."""

from __future__ import annotations

import functools
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


class _CachedExperiment:
    """Snapshot one Experiment's pooled tables once while building a page.

    Experiment rebuilds each pooled table on every access so estimates always
    read current runs. A dashboard reads each table across every metric, so
    caching them here avoids repeated stacking and removes any circular import
    on flowsim.results.
    """

    def __init__(self, experiment: Experiment):
        self._experiment = experiment
        self.runs = experiment.runs
        self.settings = experiment.settings
        self.stock_point_names = experiment.stock_point_names

    @functools.cached_property
    def summary(self) -> pl.DataFrame:
        return self._experiment.summary

    @functools.cached_property
    def stations(self) -> pl.DataFrame:
        return self._experiment.stations

    @functools.cached_property
    def stock_points(self) -> pl.DataFrame:
        return self._experiment.stock_points


def scenario_runs(
    values: Mapping[str, Mapping[str | None, np.ndarray]],
    place: str | None,
) -> dict[str | None, list[float | None]]:
    """Return each scenario's run values at one location, None where missing.

    The values come from scenario_values. A scenario without the location is
    left out.
    """
    return {
        name: [
            None if not math.isfinite(value) else float(value) for value in runs[place]
        ]
        for name, runs in values.items()
        if place in runs
    }


def metric_entry(
    experiments: Mapping[str, Any],
    metric: str,
    comparing: bool,
    level: float,
    *,
    scenario_locations,
    location_column,
    scenario_values,
    run_values,
    scenario_intervals,
    paired_differences,
    interval_figure,
    replication_figure,
    window_text,
) -> dict[str, Any] | None:
    """Return one metric's dashboard views, one per location, or None.

    None means no scenario's model can measure the metric. Each view holds
    the interval table and figure, the per-replication figure, and, in a
    comparison, the paired differences from each scenario as the baseline.
    The run values are read once and feed all of them.
    """
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
    if comparing:
        values = scenario_values(
            experiments=experiments,
            metric=metric,
            found=found,
        )
    else:
        # An experiment's errors name no scenario, as experiment.intervals().
        values = {
            "": run_values(
                experiment=first,
                metric=metric,
                names=found[""],
            )
        }
    table = scenario_intervals(
        values=values,
        metric=metric,
        level=level,
    )
    if comparing:
        changes = {
            baseline: paired_differences(
                experiments=experiments,
                values=values,
                reference=baseline,
                metric=metric,
                level=level,
            )
            for baseline in experiments
        }
    else:
        # An experiment's table has no scenario column, as experiment.intervals().
        table = table.drop("scenario")
        changes = {}
    views = []
    for place in places:
        here = pl.col(column).is_null() if place is None else pl.col(column) == place
        chosen = table.filter(here)
        runs = scenario_runs(
            values=values,
            place=place,
        )
        paired = {baseline: rows.filter(here) for baseline, rows in changes.items()}
        views.append(
            {
                "title": METRICS[metric].label
                + ("" if place is None else f" at {place}"),
                "intervals": chosen.to_dicts(),
                "means": interval_figure(
                    table=chosen,
                    metric=metric,
                    time_unit=settings.time_unit,
                ),
                "runs": replication_figure(
                    values=runs if comparing else {None: runs[""]},
                    scenarios=list(experiments) if comparing else [None],
                    metric=metric,
                    place=place,
                    time_unit=settings.time_unit,
                ),
                "changes": {
                    baseline: None
                    if rows.is_empty()
                    else {
                        "intervals": rows.to_dicts(),
                        "figure": interval_figure(
                            table=rows,
                            metric=metric,
                            time_unit=settings.time_unit,
                            differences=True,
                        ),
                    }
                    for baseline, rows in paired.items()
                },
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
                    f'<script id="run-{scenario}-{index}" type="application/json">'
                    f"{page_json(run_payload(run))}</script>"
                    for index, run in enumerate(experiment.runs)
                ]
        payload = {
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
