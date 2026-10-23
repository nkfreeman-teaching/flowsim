"""Plotly figures and an offline viewer, with no notebook dependency."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
import plotly.graph_objects as go
import polars as pl
from plotly.offline import get_plotlyjs

from flowsim.results import METRICS, Phase, Status
from flowsim.validation import integer

if TYPE_CHECKING:
    from flowsim.model import Model
    from flowsim.results import Results

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
GRAY = "#667085"

# Customer timeline activities in legend order, with their bar colors.
TIMELINE_COLORS = {
    "Waiting": BLUE,
    "In service": ORANGE,
    "Paused": PURPLE,
    "Blocked": GREEN,
    "Outside": GRAY,
}


def label(text: str) -> str:
    """Escape model text, since Plotly renders a subset of HTML in labels."""
    return html.escape(text, quote=False)


def style(figure: go.Figure, x_label: str, y_label: str) -> go.Figure:
    figure.update_layout(
        template="plotly_white",
        width=800,
        height=500,
        font={"family": "Georgia, serif", "size": 14},
        xaxis={"title": label(x_label), "rangemode": "tozero"},
        yaxis={"title": label(y_label), "rangemode": "tozero"},
        margin={"l": 85, "r": 30, "t": 35, "b": 70},
        legend={"orientation": "h", "y": 1.14, "x": 0},
        hovermode="closest",
    )
    return figure


def station_menu(figure: go.Figure, stations: list[str]) -> None:
    """Add a station menu that shows the traces whose meta names that station.

    The viewer's station choice selects traces by the same meta value.
    """
    if not stations:
        return
    buttons = [
        {
            "label": label(station),
            "method": "update",
            "args": [{"visible": [trace.meta == station for trace in figure.data]}],
        }
        for station in stations
    ]
    figure.update_layout(
        updatemenus=[{"buttons": buttons, "x": 1, "y": 1.16, "xanchor": "right"}],
    )


def network_diagram(model: Model) -> go.Figure:
    graph = model.graph
    positions = {}
    layers = list(nx.topological_generations(graph))
    for layer, names in enumerate(layers):
        for index, name in enumerate(names):
            positions[name] = (layer, (len(names) - 1) / 2 - index)
    figure = go.Figure()
    for origin, target, data in graph.edges(data=True):
        x_start, y_start = positions[origin]
        x_end, y_end = positions[target]
        figure.add_annotation(
            x=x_end - 0.17,
            y=y_end,
            ax=x_start + 0.17,
            ay=y_start,
            xref="x",
            yref="y",
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowwidth=2,
            arrowcolor=GRAY,
            text="",
        )
        if data["probability"] != 1:
            figure.add_annotation(
                x=(x_start + x_end) / 2,
                y=(y_start + y_end) / 2 + 0.1,
                text=f"{data['probability']:.0%}",
                showarrow=False,
                bgcolor="white",
            )
    for kind, color in [("source", GREEN), ("station", BLUE), ("exit", ORANGE)]:
        nodes = [node for node in model.nodes.values() if node.kind == kind]
        labels = []
        for node in nodes:
            text = label(node.name)
            if kind == "station":
                suffix = "server" if node.capacity == 1 else "servers"
                text += f"<br>{node.capacity} {suffix}"
            labels.append(text)
        figure.add_trace(
            go.Scatter(
                x=[positions[node.name][0] for node in nodes],
                y=[positions[node.name][1] for node in nodes],
                mode="markers+text",
                text=labels,
                textposition="bottom center",
                marker={
                    "size": 30,
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            )
        )
    style(
        figure=figure,
        x_label="",
        y_label="",
    )
    figure.update_layout(
        height=400,
        xaxis={"visible": False, "range": [-0.45, len(layers) - 0.55]},
        yaxis={
            "visible": False,
            "range": [
                min(y for _, y in positions.values()) - 0.65,
                max(y for _, y in positions.values()) + 0.35,
            ],
        },
        margin={"l": 50, "r": 50, "t": 50, "b": 80},
    )
    return figure


def queue_plot(result: Results) -> go.Figure:
    figure = go.Figure()
    for index, station in enumerate(result.capacities):
        history = result.states.filter(pl.col("station") == station)
        for field, color, name in [
            ("waiting", BLUE, "Waiting"),
            ("busy", ORANGE, "Occupied servers"),
        ]:
            figure.add_trace(
                go.Scatter(
                    x=history.get_column("time").to_list(),
                    y=history.get_column(field).to_list(),
                    name=name,
                    mode="lines",
                    line={"shape": "hv", "color": color, "width": 2},
                    visible=index == 0,
                    meta=station,
                    hovertemplate=f"%{{x:.2f}} {label(result.time_unit)}"
                    "<br>%{y} customers<extra>%{fullData.name}</extra>",
                )
            )
    station_menu(
        figure=figure,
        stations=list(result.capacities),
    )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.time_unit})",
        y_label="Customers",
    )
    figure.update_xaxes(rangeslider={"visible": True, "thickness": 0.1})
    if result.drain:
        figure.add_vline(
            x=result.duration,
            line_color=GRAY,
            line_dash="dash",
        )
    return figure


def wait_plot(result: Results) -> go.Figure:
    figure = go.Figure()
    for index, station in enumerate(result.capacities):
        waits = (
            result.visits.filter(
                (pl.col("station") == station)
                & (pl.col("arrival_time") >= result.warmup)
                & pl.col("wait_time").is_not_null()
            )
            .get_column("wait_time")
            .to_list()
        )
        figure.add_trace(
            go.Histogram(
                x=waits,
                name=label(station),
                visible=index == 0,
                meta=station,
                marker={"color": BLUE, "line": {"color": "black", "width": 1}},
                hovertemplate="Wait bin: %{x}<br>Customers: %{y}<extra></extra>",
            )
        )
    station_menu(
        figure=figure,
        stations=list(result.capacities),
    )
    figure.update_layout(showlegend=False)
    return style(
        figure=figure,
        x_label=f"Waiting time ({result.time_unit})",
        y_label="Customers",
    )


def utilization_plot(result: Results) -> go.Figure:
    figure = go.Figure(
        go.Scatter(
            x=result.stations.get_column("utilization").to_list(),
            y=[label(name) for name in result.stations.get_column("station")],
            mode="markers",
            marker={"size": 12, "color": BLUE, "line": {"color": "black", "width": 1}},
            hovertemplate="%{y}<br>Occupied capacity: %{x:.1%}<extra></extra>",
        )
    )
    style(
        figure=figure,
        x_label="Occupied server capacity",
        y_label="Station",
    )
    figure.update_xaxes(
        range=[0, 1.05],
        tickformat=".0%",
    )
    figure.update_layout(height=max(220, 150 + 40 * len(result.capacities)))
    return figure


def resource_plot(result: Results) -> go.Figure:
    figure = go.Figure()
    fields = [
        ("processing", ORANGE, "Processing"),
        ("blocked", GREEN, "Blocked"),
        ("paused", PURPLE, "Paused"),
        ("down", "#222222", "Down"),
        ("available", GRAY, "Available"),
        ("scheduled", BLUE, "Scheduled"),
    ]
    for index, station in enumerate(result.capacities):
        history = result.states.filter(pl.col("station") == station)
        for field, color, name in fields:
            figure.add_trace(
                go.Scatter(
                    x=history.get_column("time").to_list(),
                    y=history.get_column(field).to_list(),
                    name=name,
                    mode="lines",
                    line={
                        "shape": "hv",
                        "color": color,
                        "width": 2,
                        "dash": "dash"
                        if field in {"scheduled", "available"}
                        else "solid",
                    },
                    visible=index == 0,
                    meta=station,
                )
            )
    station_menu(
        figure=figure,
        stations=list(result.capacities),
    )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.time_unit})",
        y_label="Servers",
    )
    figure.update_layout(
        legend={"orientation": "v", "x": 1.02, "y": 1},
        margin={"l": 85, "r": 175, "t": 60, "b": 70},
    )
    if result.drain:
        figure.add_vline(
            x=result.duration,
            line_color=GRAY,
            line_dash="dash",
        )
    return figure


def timeline_spans(result: Results) -> pl.DataFrame:
    """Return every customer's timeline bars, grouped in TIMELINE_COLORS order.

    Waiting runs from station arrival to service start, and the server activity
    rows give service, paused, and blocked time. A customer who waited outside a
    full buffer gets an "Outside" bar until admission. An open end runs to the
    end time. Zero-length service writes no activity row, so it draws no bar.
    """
    waiting = result.visits.select(
        "customer_id",
        pl.lit("Waiting").alias("activity"),
        "station",
        pl.col("arrival_time").alias("start"),
        pl.col("service_start").alias("end"),
    )
    activities = [
        result.activities.filter(pl.col("state") == state).select(
            "customer_id",
            pl.lit(activity).alias("activity"),
            "station",
            "start",
            "end",
        )
        for activity, state in [
            ("In service", Phase.PROCESSING),
            ("Paused", Phase.PAUSED),
            ("Blocked", Phase.BLOCKED),
        ]
    ]
    outside = result.customers.filter(
        (pl.col("status") == Status.OUTSIDE)
        | (pl.col("outside_wait").is_not_null() & (pl.col("outside_wait") != 0))
    ).select(
        "customer_id",
        pl.lit("Outside").alias("activity"),
        pl.lit("Outside").alias("station"),
        pl.col("arrival_time").alias("start"),
        pl.col("admission_time").alias("end"),
    )
    return pl.concat([waiting, *activities, outside]).with_columns(
        pl.col("end").fill_null(result.end_time),
    )


def customer_plot(result: Results, customer_id: int) -> go.Figure:
    identifier = integer(customer_id, "Customer ID")
    if result.customers.filter(pl.col("customer_id") == identifier).is_empty():
        raise ValueError(f"Customer {identifier} does not exist in this run.")
    spans = timeline_spans(result).filter(pl.col("customer_id") == identifier)
    figure = go.Figure()
    for activity, color in TIMELINE_COLORS.items():
        bars = spans.filter(pl.col("activity") == activity)
        figure.add_trace(
            go.Bar(
                base=bars.get_column("start").to_list(),
                x=(bars.get_column("end") - bars.get_column("start")).to_list(),
                y=[label(station) for station in bars.get_column("station")],
                orientation="h",
                name=activity,
                marker={
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate="%{y}<br>Duration: %{x:.2f}<extra>%{fullData.name}</extra>",
            )
        )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.time_unit})",
        y_label="Station",
    )
    figure.update_layout(barmode="overlay")
    figure.update_yaxes(autorange="reversed")
    return figure


def viewer_html(result: Results) -> str:
    figures = {
        "queues": json.loads(result.queue_plot().to_json()),
        "waits": json.loads(result.wait_plot().to_json()),
        "utilization": json.loads(result.utilization_plot().to_json()),
    }
    if any(
        definition["staffing"] is not None
        or definition["buffer"] is not None
        or definition["failures_enabled"]
        for definition in result.definitions.values()
    ):
        figures["resources"] = json.loads(result.resource_plot().to_json())
    payload = {
        "figures": figures,
        "customers": result.customers.to_dicts(),
        "visits": result.visits.to_dicts(),
        # Table cells for these station metrics display as percentages.
        "percent_columns": [
            name for name, metric in METRICS.items() if metric.kind == "fraction"
        ],
        # Downloads use the export column order, even for empty tables.
        "columns": {
            "customers": result.customers.columns,
            "visits": result.visits.columns,
        },
        # The viewer draws these bars as given, so it matches customer_plot.
        "timeline": timeline_spans(result).to_dicts(),
        "timeline_colors": TIMELINE_COLORS,
        "failures": result.failures.to_dicts(),
        "stations": result.stations.to_dicts(),
        "summary": result.summary.to_dicts()[0],
        "duration": result.duration,
        "end_time": result.end_time,
        "drain": result.drain,
        "warmup": result.warmup,
        "time_unit": result.time_unit,
        "seed": result.seed,
    }
    # Escape '<' so model labels cannot terminate the embedded JSON script.
    data = json.dumps(payload, allow_nan=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("viewer.html").read_text(encoding="utf-8")
    return template.replace("__PLOTLY_JS__", get_plotlyjs()).replace(
        "__RESULT_JSON__", data
    )
