"""Scenario comparisons with matched replication seeds and paired intervals."""

from __future__ import annotations

import html
import json
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
    SYSTEM_METRICS,
    Experiment,
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

        def settings(run) -> tuple:
            return (run.duration, run.warmup, run.drain, run.time_unit)

        if any(
            settings(experiment.runs[0]) != settings(first)
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

    def _values(self, scenario: str, metric: str, station: str | None) -> np.ndarray:
        if station is None and metric not in SYSTEM_METRICS:
            raise ValueError(
                f"Choose a system metric from {SYSTEM_METRICS}, "
                "or name a station for a station metric."
            )
        if station is not None and metric not in STATION_METRICS:
            raise ValueError(f"Choose a station metric from {STATION_METRICS}.")
        experiment = self.experiments[scenario]
        if station is not None and station not in experiment.runs[0].capacities:
            raise ValueError(
                f"Station {station!r} is missing in scenario {scenario!r}."
            )
        try:
            return experiment._values(metric, station)
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
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        level = confidence_level(confidence)
        rows = []
        for name, experiment in self.experiments.items():
            values = self._values(
                scenario=name,
                metric=metric,
                station=station,
            )
            rows.append(
                {
                    "scenario": name,
                    "metric": metric,
                    "station": station,
                    "runs": len(experiment.runs),
                    **interval_estimate(values, level),
                    "confidence": level,
                }
            )
        return interval_frame(
            rows=rows,
            keys=["scenario", "metric", "station"],
        )

    def differences(
        self,
        metric: str = "mean_total_wait",
        *,
        baseline: str | None = None,
        station: str | None = None,
        confidence: float = 0.95,
    ) -> pl.DataFrame:
        reference = self._reference(baseline)
        level = confidence_level(confidence)
        baseline_values = self._values(
            scenario=reference,
            metric=metric,
            station=station,
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
                    "station": station,
                    "runs": len(experiment.runs),
                    **interval_estimate(values - baseline_values, level),
                    "confidence": level,
                }
            )
        return interval_frame(
            rows=rows,
            keys=["scenario", "baseline", "metric", "station"],
        )

    def plot(
        self,
        metric: str = "mean_total_wait",
        *,
        station: str | None = None,
        confidence: float = 0.95,
        differences: bool = False,
        baseline: str | None = None,
    ) -> go.Figure:
        table = (
            self.differences(
                metric=metric,
                baseline=baseline,
                station=station,
                confidence=confidence,
            )
            if differences
            else self.intervals(
                metric=metric,
                station=station,
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
        figure.update_yaxes(autorange="reversed", automargin=True)
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
        confidence: float = 0.95,
        baseline: str | None = None,
    ) -> str:
        reference = self._reference(baseline)
        means = self.plot(
            metric=metric,
            station=station,
            confidence=confidence,
        )
        changes = self.plot(
            metric=metric,
            station=station,
            confidence=confidence,
            differences=True,
            baseline=reference,
        )
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
        units = html.escape(
            "percent" if fraction else metric_units(metric, self.time_unit)
        )
        text = (
            f"Operating hours end at {self.duration:g} {self.time_unit}. "
            f"Measurement begins at {self.warmup:g} {self.time_unit}. "
            + (
                "Every admitted customer is served to completion."
                if self.drain
                else "Service stops at closing. Waiting and flow averages include observed outcomes."
            )
        )
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FlowSim scenario comparison</title>
<style>
body {{font-family: system-ui, sans-serif; color: #172b3a; background: #f3f6f8; margin: 0;}}
main {{max-width: 1000px; margin: auto; padding: 28px;}}
section {{background: white; padding: 20px; margin: 18px 0; border: 1px solid #dce3e8; border-radius: 10px; overflow-x: auto;}}
p {{line-height: 1.5;}} h1 {{font-size: 28px;}} h2 {{font-size: 20px;}}
table {{border-collapse: collapse; width: 100%;}}
td,th {{text-align: right; padding: 10px; border-bottom: 1px solid #e4eaef;}}
td:first-child,th:first-child {{text-align: left;}}
</style></head><body><main>
<h1>Scenario comparison</h1><p>{html.escape(text)}</p>
<section><h2>{html.escape(title)}</h2>
<p>Points show means across independent replications.
Intervals show {confidence:.0%} Student t uncertainty across run estimates.</p>
{means_html}
<table><thead><tr><th>Scenario</th><th>Mean ({units})</th><th>Lower limit ({units})</th><th>Upper limit ({units})</th><th>Observed runs</th></tr></thead>
<tbody>{table_rows}</tbody></table></section>
<section><h2>Difference from {html.escape(reference)}</h2>
<p>Each difference is the scenario value minus its baseline value within the same
replication. Negative values indicate a smaller metric. The dashed line marks zero.</p>
{changes_html}</section>
<p>The saved report works offline. Intervals describe the selected finite-day statistic.
They do not establish steady-state performance. Wait and flow averages exclude rejected
arrivals, which can be compared separately. Raw runs remain available in Python.</p>
</main></body></html>"""
        if path is not None:
            write_text(path, document)
        return document

    def export(
        self,
        directory: str | Path,
        *,
        metric: str = "mean_total_wait",
        station: str | None = None,
        confidence: float = 0.95,
        baseline: str | None = None,
    ) -> Path:
        reference = self._reference(baseline)
        intervals = self.intervals(
            metric=metric,
            station=station,
            confidence=confidence,
        )
        differences = self.differences(
            metric=metric,
            baseline=reference,
            station=station,
            confidence=confidence,
        )
        destination = Path(directory)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.summary.write_csv(destination / "runs.csv")
        self.stations.write_csv(destination / "stations.csv")
        intervals.write_csv(destination / "intervals.csv")
        differences.write_csv(destination / "differences.csv")
        from flowsim import __version__

        metadata = {
            "flowsim_version": __version__,
            "baseline": reference,
            "metric": metric,
            "station": station,
            "confidence": confidence,
            "time_unit": self.time_unit,
            "duration": self.duration,
            "warmup": self.warmup,
            "drain": self.drain,
            "replication_seeds": [run.seed for run in self.experiments[reference].runs],
            "difference": "Scenario minus baseline within matched replication",
        }
        write_text(destination / "metadata.json", json.dumps(metadata, indent=2))
        return destination


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
