"""Scenario comparisons with matched replication seeds and paired intervals."""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import polars as pl

from flowsim.model import Model
from flowsim.plots import BLUE, label, style
from flowsim.results import (
    METRICS,
    STATION_METRICS,
    STOCK_POINT_METRICS,
    SYSTEM_METRICS,
    Experiment,
    _run_settings,
    _write_metadata,
    confidence_level,
    interval_estimate,
    interval_frame,
    metric_units,
    write_text,
)


class Comparison:
    def __init__(self, experiments: dict[str, Experiment]):
        if len(experiments) < 2:
            raise ValueError("A comparison needs at least two experiments.")
        self.experiments = experiments
        self.baseline = next(iter(experiments))
        first = experiments[self.baseline].runs[0]
        if any(
            _run_settings(experiment.runs[0]) != _run_settings(first)
            for experiment in experiments.values()
        ):
            raise ValueError(
                "Compared scenarios need the same duration, warm-up, drain rule, "
                "and time unit."
            )
        self.time_unit = first.time_unit
        self.duration = first.duration
        self.warmup = first.warmup
        self.drain = first.drain

    # The combined tables are built from the experiments on each access, so
    # estimates and exports always read the same replication values.
    @property
    def summary(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.summary.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    @property
    def stations(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.stations.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    @property
    def stock_points(self) -> pl.DataFrame:
        return pl.concat(
            [
                experiment.stock_points.select(pl.lit(name).alias("scenario"), pl.all())
                for name, experiment in self.experiments.items()
            ]
        )

    def _values(
        self,
        scenario: str,
        metric: str,
        station: str | None,
        stock_point: str | None = None,
    ) -> np.ndarray:
        if stock_point is not None:
            if metric not in STOCK_POINT_METRICS:
                raise ValueError(
                    f"Choose a stock-point metric from {STOCK_POINT_METRICS}."
                )
            if station is not None:
                raise ValueError("Name a station or a stock point, not both.")
        elif metric in STOCK_POINT_METRICS:
            raise ValueError(
                f"{metric!r} is a stock-point metric, so name a stock point."
            )
        elif station is None and metric not in SYSTEM_METRICS:
            raise ValueError(
                f"Choose a system metric from {SYSTEM_METRICS}, "
                "or name a station for a station metric."
            )
        if station is not None and metric not in STATION_METRICS:
            raise ValueError(f"Choose a station metric from {STATION_METRICS}.")
        try:
            return self.experiments[scenario]._values(
                metric=metric,
                station=station,
                stock_point=stock_point,
            )
        except ValueError as error:
            raise ValueError(f"Scenario {scenario!r}: {error}") from None

    def _reference(self, baseline: str | None) -> str:
        reference = self.baseline if baseline is None else baseline
        if reference not in self.experiments:
            raise ValueError(f"Unknown baseline scenario {reference!r}.")
        return reference

    def intervals(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        level = confidence_level(confidence)
        rows = []
        for name, experiment in self.experiments.items():
            values = self._values(
                scenario=name,
                metric=metric,
                station=station,
                stock_point=stock_point,
            )
            rows.append(
                {
                    "scenario": name,
                    "metric": metric,
                    **_location(station, stock_point),
                    "runs": len(experiment.runs),
                    **interval_estimate(values, level),
                    "confidence": level,
                }
            )
        return interval_frame(
            rows=rows,
            keys=["scenario", "metric", *_location(station, stock_point)],
        )

    def differences(
        self,
        metric: str = "mean_total_wait",
        *,
        baseline: str | None = None,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        reference = self._reference(baseline)
        level = confidence_level(confidence)
        baseline_values = self._values(
            scenario=reference,
            metric=metric,
            station=station,
            stock_point=stock_point,
        )
        baseline_seeds = [run.seed for run in self.experiments[reference].runs]
        rows = []
        for name, experiment in self.experiments.items():
            if name == reference:
                continue
            values = self._values(
                scenario=name,
                metric=metric,
                station=station,
                stock_point=stock_point,
            )
            if [run.seed for run in experiment.runs] != baseline_seeds:
                raise ValueError("Paired scenarios need identical replication seeds.")
            # Subtract within each matched replication before estimating error.
            # A missing result excludes that pair, not unrelated observations.
            rows.append(
                {
                    "scenario": name,
                    "baseline": reference,
                    "metric": metric,
                    **_location(station, stock_point),
                    "runs": len(experiment.runs),
                    **interval_estimate(values - baseline_values, level),
                    "confidence": level,
                }
            )
        return interval_frame(
            rows=rows,
            keys=["scenario", "baseline", "metric", *_location(station, stock_point)],
        )

    def plot(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
        differences: bool = False,
        baseline: str | None = None,
    ) -> go.Figure:
        table = (
            self.differences(
                metric=metric,
                baseline=baseline,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            )
            if differences
            else self.intervals(
                metric=metric,
                station=station,
                stock_point=stock_point,
                confidence=confidence,
            )
        )
        rows = table.to_dicts()
        figure = go.Figure(
            go.Scatter(
                x=[row["mean"] for row in rows],
                y=[label(row["scenario"]) for row in rows],
                mode="markers",
                marker={
                    "size": 12,
                    "color": BLUE,
                    "line": {"color": "black", "width": 1},
                },
                error_x={
                    "type": "data",
                    "array": [
                        None if row["upper"] is None else row["upper"] - row["mean"]
                        for row in rows
                    ],
                    "thickness": 2.5,
                    "width": 5,
                },
                hovertemplate="%{y}<br>Estimate: %{x:.3f}<extra></extra>",
            )
        )
        fraction = METRICS[metric].kind == "fraction"
        axis_label = METRICS[metric].label
        if not fraction:
            axis_label += f" ({metric_units(metric, self.time_unit)})"
        if differences:
            axis_label = "Difference in " + axis_label[0].lower() + axis_label[1:]
        style(
            figure=figure,
            x_label=axis_label,
            y_label="Scenario",
        )
        figure.update_layout(
            height=max(240, 150 + 50 * len(rows)),
            margin={"l": 155, "r": 35, "t": 35, "b": 80},
        )
        # List scenarios top to bottom in the order they were defined.
        figure.update_yaxes(
            autorange="reversed",
            automargin=True,
        )
        if fraction:
            figure.update_xaxes(tickformat=".0%")
        if differences:
            figure.add_vline(
                x=0,
                line_color="#667085",
                line_dash="dash",
            )
        return figure

    def viewer(
        self,
        path: str | Path | None = None,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
        baseline: str | None = None,
    ) -> str:
        reference = self._reference(baseline)
        means = self.plot(
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )
        changes = self.plot(
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
            differences=True,
            baseline=reference,
        )
        # plots.style sets an 800-pixel width, so let each card set the width.
        for figure in (means, changes):
            figure.update_layout(width=None, autosize=True)
        means_html = means.to_html(
            full_html=False,
            include_plotlyjs=True,
            div_id="scenario-means",
        )
        changes_html = changes.to_html(
            full_html=False,
            include_plotlyjs=False,
            div_id="scenario-differences",
        )
        table = self.intervals(
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )
        fraction = METRICS[metric].kind == "fraction"

        def cell(row: dict, key: str) -> str:
            if row["mean"] is None:
                return "Not observed"
            if row[key] is None:
                return "Needs two runs"
            return f"{row[key]:.1%}" if fraction else f"{row[key]:.3f}"

        table_rows = ""
        for row in table.to_dicts():
            cells = [
                html.escape(row["scenario"]),
                *[cell(row, key) for key in ["mean", "lower", "upper"]],
                str(row["observed_runs"]),
            ]
            table_rows += (
                "<tr>" + "".join(f"<td>{value}</td>" for value in cells) + "</tr>"
            )
        title = METRICS[metric].label
        if stock_point is not None:
            title += f" at {stock_point}"
        units = html.escape(
            "percent" if fraction else metric_units(metric, self.time_unit)
        )
        if stock_point is not None:
            text = (
                f"Stock points review each period until {self.duration:g} "
                f"{self.time_unit}. Measurement begins at {self.warmup:g} "
                f"{self.time_unit}."
            )
        else:
            text = (
                f"Operating hours end at {self.duration:g} {self.time_unit}. "
                f"Measurement begins at {self.warmup:g} {self.time_unit}. "
                + (
                    "Every admitted customer is served to completion."
                    if self.drain
                    else "Service stops at closing. Waiting and flow averages include observed outcomes."
                )
            )
        values = {
            "TEXT": html.escape(text),
            "TITLE": html.escape(title),
            "CONFIDENCE": f"{confidence:.0%}",
            "MEANS": means_html,
            "UNITS": units,
            "TABLE_ROWS": table_rows,
            "REFERENCE": html.escape(reference),
            "CHANGES": changes_html,
        }
        template = (
            Path(__file__).with_name("comparison.html").read_text(encoding="utf-8")
        )
        # One pass over the template, so a placeholder-like scenario name or
        # Plotly text inside a value is never replaced.
        document = re.sub(
            pattern=r"__([A-Z_]+)__",
            repl=lambda match: values[match.group(1)],
            string=template,
        )
        if path is not None:
            write_text(path, document)
        return document

    def export(
        self,
        directory: str | Path,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        stock_point: str | None = None,
        confidence: float = 0.95,
        baseline: str | None = None,
    ) -> Path:
        reference = self._reference(baseline)
        intervals = self.intervals(
            metric=metric,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )
        differences = self.differences(
            metric=metric,
            baseline=reference,
            station=station,
            stock_point=stock_point,
            confidence=confidence,
        )
        destination = Path(directory)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.summary.write_csv(destination / "runs.csv")
        self.stations.write_csv(destination / "stations.csv")
        if any(
            experiment.runs[0].supply is not None
            for experiment in self.experiments.values()
        ):
            self.stock_points.write_csv(destination / "stock_points.csv")
        intervals.write_csv(destination / "intervals.csv")
        differences.write_csv(destination / "differences.csv")
        metadata = {
            "baseline": reference,
            "metric": metric,
            "station": station,
            **({} if stock_point is None else {"stock_point": stock_point}),
            "confidence": confidence,
            "time_unit": self.time_unit,
            "duration": self.duration,
            "warmup": self.warmup,
            "drain": self.drain,
            "replication_seeds": [run.seed for run in self.experiments[reference].runs],
            "difference": "Scenario minus baseline within matched replication",
        }
        _write_metadata(destination / "metadata.json", metadata)
        return destination


def _location(station: str | None, stock_point: str | None) -> dict:
    """Return the interval table's location column, keyed by its name.

    Stock-point metrics use a stock_point column, and every other metric keeps
    the station column, which is null for system metrics.
    """
    if stock_point is not None:
        return {"stock_point": stock_point}
    return {"station": station}


def compare(
    scenarios: Mapping[str, Model],
    duration: float,
    *,
    replications: int = 20,
    seed: int = 42,
    warmup: float = 0,
    drain: bool = False,
) -> Comparison:
    """Run named scenarios using the same independent replication seeds."""
    if not isinstance(scenarios, Mapping) or len(scenarios) < 2:
        raise ValueError("A comparison needs at least two named models.")
    for name, model in scenarios.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Each scenario needs a nonempty name.")
        if not isinstance(model, Model):
            raise ValueError(f"Scenario {name!r} must contain a Model.")
        model.validate()
    if len({model.time_unit for model in scenarios.values()}) != 1:
        raise ValueError("Compared scenarios must declare the same time unit.")
    return Comparison(
        {
            name: model.experiment(
                duration=duration,
                replications=replications,
                seed=seed,
                warmup=warmup,
                drain=drain,
            )
            for name, model in scenarios.items()
        }
    )
