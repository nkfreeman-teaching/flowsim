"""Plotly figures and page data, with no notebook dependency.

A function named ..._figure returns a figure as plain data, a dict of "data"
(the traces) and "layout" as Plotly's JSON holds them. A viewer page embeds
that dict as it is, and the plot methods wrap the same dict with
plotly_figure, so each figure is defined once. Building Plotly objects for the
hundreds of figures a dashboard holds cost most of its build time.
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
import functools
import html
import json
import math
import re
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import plotly.graph_objects as go
import polars as pl

from flowsim.catalog import METRICS, unknown
from flowsim.records import Phase, Status
from flowsim.validation import boolean, integer, number

if TYPE_CHECKING:
    from flowsim.results import Experiment, Results

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
GRAY = "#667085"
# Marks a diagram node that keeps the model from running.
WARNING = "#C62828"

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


# True while a page is built, when trace columns become typed arrays.
_BUILDING_PAGE = contextvars.ContextVar("building_page", default=False)


@contextlib.contextmanager
def building_page() -> Iterator[None]:
    """Write the trace columns of figures built inside the block as typed arrays."""
    token = _BUILDING_PAGE.set(True)
    try:
        yield
    finally:
        _BUILDING_PAGE.reset(token)


# plotly.js names the typed arrays it reads by these codes.
TYPED_ARRAY_CODES = {
    "int8": "i1",
    "uint8": "u1",
    "int16": "i2",
    "uint16": "u2",
    "int32": "i4",
    "uint32": "u4",
    "float32": "f4",
    "float64": "f8",
}


def typed_array(values: np.ndarray) -> dict | list:
    """Encode an array as plotly.js typed-array data, as Plotly's own JSON does.

    plotly.js has no 64-bit integers, so an int64 array takes the smallest
    integer type that holds it. An empty array, or one that no typed array
    holds, stays a list.
    """
    if values.size == 0:
        return []
    if values.dtype == np.int64:
        lo = int(values.min())
        hi = int(values.max())
        smaller = [
            kind
            for kind in [np.int8, np.int16, np.int32]
            if np.iinfo(kind).min <= lo and hi <= np.iinfo(kind).max
        ]
        if not smaller:
            return values.tolist()
        values = values.astype(smaller[0])
    code = TYPED_ARRAY_CODES.get(str(values.dtype))
    if code is None:
        return values.tolist()
    return {
        "dtype": code,
        "bdata": base64.b64encode(np.ascontiguousarray(values)).decode("ascii"),
    }


def trace_values(values: pl.Series) -> list | dict:
    """Return a record column for a trace: a typed array on a page, a list otherwise.

    A typed array is compact base64 data, which keeps run pages small and fast
    to write. A column with a null or NaN stays a list on a page, with NaN and
    infinite values as None, as Plotly's own JSON writes them. Figures
    returned to users hold lists.
    """
    if not _BUILDING_PAGE.get():
        return values.to_list()
    if values.null_count() > 0 or (values.dtype.is_float() and values.is_nan().any()):
        return [
            None if value is not None and not math.isfinite(value) else value
            for value in values.to_list()
        ]
    return typed_array(values.to_numpy())


def base_layout(x_label: str, y_label: str) -> dict:
    """Return FlowSim's size, font, axis titles, margins, and legend as layout data."""
    return {
        "width": 800,
        "height": 500,
        "font": {"family": "Georgia, serif", "size": 14},
        "xaxis": {"title": {"text": label(x_label)}, "rangemode": "tozero"},
        "yaxis": {"title": {"text": label(y_label)}, "rangemode": "tozero"},
        "margin": {"l": 85, "r": 30, "t": 60, "b": 70},
        "legend": {"orientation": "h", "y": 1.04, "x": 0, "yanchor": "bottom"},
        "hovermode": "closest",
    }


def plotly_figure(figure: dict) -> go.Figure:
    """Wrap a figure's data in a Plotly figure with the plotly_white template.

    A page holds that template once (see page_template) and adds it to each
    figure it draws, so its figures leave it out.
    """
    return go.Figure(
        data=figure["data"],
        layout={**figure["layout"], "template": "plotly_white"},
    )


def _merged(base: dict, extra: dict) -> dict:
    """Return base updated with extra, as Plotly's update_layout merges them.

    A dict merges into an existing dict, and any other value replaces the old
    one.
    """
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merged(merged[key], value)
        else:
            merged[key] = value
    return merged


def style(figure: go.Figure, x_label: str, y_label: str) -> go.Figure:
    """Give a Plotly figure base_layout's values and the plotly_white template.

    The figure gets one new Layout, its own layout merged with these values,
    because update_layout costs about three times as much per figure. Layout
    set before (e.g., a legend position) is kept, but the new axis titles
    replace the old ones whole. The merge leaves out the old template, since
    validating it again is slow.
    """
    layout = figure.layout.to_plotly_json()
    layout.pop("template", None)
    for axis in ["xaxis", "yaxis"]:
        layout.get(axis, {}).pop("title", None)
    shared = {**base_layout(x_label, y_label), "template": "plotly_white"}
    figure.layout = go.Layout(_merged(layout, shared))
    return figure


def dashed_line(
    figure: dict,
    x: float,
    *,
    text: str | None = None,
    dash: str = "dash",
) -> None:
    """Add a vertical reference line at x, optionally labeled above the plot."""
    figure["layout"].setdefault("shapes", []).append(
        {
            "type": "line",
            "x0": x,
            "x1": x,
            "xref": "x",
            "y0": 0,
            "y1": 1,
            "yref": "y domain",
            "line": {"color": GRAY, "dash": dash},
        }
    )
    if text:
        figure["layout"].setdefault("annotations", []).append(
            {
                "x": x,
                "y": 1,
                "xref": "x",
                "yref": "y domain",
                "text": label(text),
                "showarrow": False,
                "yanchor": "bottom",
                "font": {"size": 11, "color": GRAY},
            }
        )


def warmup_line(figure: dict, result: Results) -> None:
    if result.settings.warmup > 0:
        dashed_line(
            figure,
            result.settings.warmup,
            text="Warm-up",
            dash="dot",
        )


def station_menu(figure: dict, stations: list[str]) -> None:
    """Add a station menu that shows the traces whose meta names that station.

    The viewer's station choice selects traces by the same meta value.
    """
    if not stations:
        return
    buttons = [
        {
            "label": label(station),
            "method": "update",
            "args": [
                {"visible": [trace.get("meta") == station for trace in figure["data"]]}
            ],
        }
        for station in stations
    ]
    figure["layout"]["updatemenus"] = [
        {"buttons": buttons, "x": 1, "y": 1.16, "xanchor": "right"}
    ]


def require_stations(result: Results) -> None:
    """Explain that a run without stations has no station plots."""
    if not result.settings.capacities:
        if result.supply is not None:
            raise ValueError(
                "This run has no stations. plot_inventory() and plot_orders() "
                "show its stock points."
            )
        raise ValueError(
            "This run has no stations, so it has no station plots. Its summary "
            "table holds the customer totals, and plot_customer() shows one "
            "customer's timeline."
        )


def chosen_stations(result: Results, station: str | None) -> list[str]:
    """Return the stations a station plot draws, every one unless one is named.

    A run without stations draws empty station figures, as the viewer needs,
    and the public plot methods call require_stations first.
    """
    # Only a comparison's shared settings hold no capacities.
    capacities = result.settings.capacities
    assert capacities is not None
    names = list(capacities)
    if station is None:
        return names
    require_stations(result)
    if station not in names:
        raise unknown(
            kind="station",
            name=station,
            choices=names,
            intro=f"Station {station!r} is not in this run.",
        )
    return [station]


def chosen_stock_points(result: Results, stock_point: str | None) -> list[str]:
    """Return the stock points a plot draws, every one unless one is named."""
    names = result.stock_point_names
    if not names:
        raise ValueError(
            "This run has no stock points. plot_queue(), plot_wait(), "
            "plot_utilization(), and plot_resources() show its stations."
        )
    if stock_point is None:
        return names
    if stock_point not in names:
        raise unknown(
            kind="stock point",
            name=stock_point,
            choices=names,
            intro=f"Stock point {stock_point!r} is not in this run.",
        )
    return [stock_point]


def queue_figure(result: Results, station: str | None = None) -> dict:
    """Return waiting customers and occupied servers over time at each station.

    Without a station, a menu chooses among the stations, and the first is
    shown. A named station is the only one drawn.
    """
    names = chosen_stations(result, station)
    figure = {
        "data": [],
        "layout": base_layout(
            x_label=f"Simulation time ({result.settings.time_unit})",
            y_label="Customers",
        ),
    }
    by_station = (
        {
            key[0]: frame
            for key, frame in result.states.partition_by(
                "station",
                as_dict=True,
                maintain_order=True,
            ).items()
        }
        if len(names) > 1
        else {}
    )
    for index, place in enumerate(names):
        history = (
            by_station.get(place, result.states.clear())
            if len(names) > 1
            else result.states.filter(pl.col("station") == place)
        )
        for field, color, name in [
            ("waiting", BLUE, "Waiting"),
            ("busy", ORANGE, "Occupied servers"),
        ]:
            figure["data"].append(
                {
                    "type": "scatter",
                    "x": trace_values(history.get_column("time")),
                    "y": trace_values(history.get_column(field)),
                    "name": name,
                    "mode": "lines",
                    "line": {"shape": "hv", "color": color, "width": 2},
                    "visible": index == 0,
                    "meta": place,
                    "hovertemplate": f"%{{x:.2f}} {label(result.settings.time_unit)}"
                    "<br>%{y} customers<extra>%{fullData.name}</extra>",
                }
            )
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    figure["layout"]["xaxis"]["rangeslider"] = {"visible": True, "thickness": 0.1}
    if result.settings.drain:
        dashed_line(
            figure,
            result.settings.duration,
            text="Closing",
            dash="dash",
        )
    warmup_line(figure, result)
    return figure


def wait_figure(
    result: Results,
    station: str | None = None,
    *,
    kind: Literal["histogram", "ecdf"] = "histogram",
) -> dict:
    """Return each station's observed waits for station arrivals after warm-up."""
    if kind not in {"histogram", "ecdf"}:
        raise ValueError(f"kind must be 'histogram' or 'ecdf', not {kind!r}.")
    names = chosen_stations(result, station)
    unit = label(result.settings.time_unit)
    figure = {
        "data": [],
        "layout": base_layout(
            x_label=f"Waiting time ({result.settings.time_unit})",
            y_label="Cumulative share" if kind == "ecdf" else "Customers",
        ),
    }
    observed = result.visits.filter(
        (pl.col("arrival_time") >= result.settings.warmup)
        & pl.col("wait_time").is_not_null()
    )
    by_station = (
        {
            key[0]: frame
            for key, frame in observed.partition_by(
                "station",
                as_dict=True,
                maintain_order=True,
            ).items()
        }
        if len(names) > 1
        else {}
    )
    for index, place in enumerate(names):
        series = (
            by_station.get(place, observed.clear())
            if len(names) > 1
            else observed.filter(pl.col("station") == place)
        ).get_column("wait_time")
        if kind == "ecdf":
            sorted_vals = np.sort(series.to_numpy())
            if sorted_vals.size > 0:
                xs = np.concatenate([[0.0], sorted_vals]).tolist()
                ys = (np.arange(sorted_vals.size + 1) / sorted_vals.size).tolist()
            else:
                xs, ys = [], []
            figure["data"].append(
                {
                    "type": "scatter",
                    "x": xs,
                    "y": ys,
                    "name": label(place),
                    "mode": "lines",
                    "line": {"shape": "hv", "color": BLUE, "width": 2},
                    "visible": index == 0,
                    "meta": place,
                    "hovertemplate": f"Wait ≤ %{{x:.2f}} {unit}<br>"
                    "Share: %{y:.1%}<extra></extra>",
                }
            )
        else:
            waits = trace_values(series)
            figure["data"].append(
                {
                    "type": "histogram",
                    "x": waits,
                    "xbins": {"start": 0},
                    "name": label(place),
                    "visible": index == 0,
                    "meta": place,
                    "marker": {
                        "color": BLUE,
                        "line": {"color": "black", "width": 1},
                    },
                    "hovertemplate": f"Wait bin: %{{x}} {unit}<br>"
                    "Customers: %{y}<extra></extra>",
                }
            )
    if len(names) == 1 and observed.filter(pl.col("station") == names[0]).is_empty():
        figure["layout"].setdefault("annotations", []).append(
            {
                "x": 0.5,
                "y": 0.5,
                "xref": "paper",
                "yref": "paper",
                "text": "No observed waits after warm-up",
                "showarrow": False,
                "font": {"size": 14, "color": GRAY},
            }
        )
    if kind == "ecdf":
        figure["layout"]["yaxis"]["range"] = [0, 1.02]
        figure["layout"]["yaxis"]["tickformat"] = ".0%"
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    figure["layout"]["showlegend"] = False
    return figure


def utilization_figure(
    result: Results,
    station: str | None = None,
    *,
    breakdown: bool = False,
) -> dict:
    """Return each station's occupied share of installed capacity, or one station's."""
    breakdown = boolean(breakdown, "breakdown")
    names = chosen_stations(result, station)
    stations = result.stations.filter(pl.col("station").is_in(names))
    layout = base_layout(
        x_label="Share of installed capacity"
        if breakdown
        else "Occupied server capacity",
        y_label="Station",
    )
    layout["xaxis"].update(range=[0, 1.05], tickformat=".0%")
    layout["yaxis"].update(autorange="reversed", automargin=True)
    layout["height"] = max(220, 150 + 40 * len(names))
    station_labels = [label(name) for name in stations.get_column("station")]
    if breakdown:
        layout["barmode"] = "stack"
        data = [
            {
                "type": "bar",
                "orientation": "h",
                "x": trace_values(stations.get_column(column)),
                "y": station_labels,
                "name": name,
                "marker": {"color": color, "line": {"color": "black", "width": 0.5}},
                "hovertemplate": f"%{{y}}<br>{name}: %{{x:.1%}}<extra></extra>",
            }
            for column, color, name in [
                ("processing_utilization", ORANGE, "Processing"),
                ("blocking_fraction", GREEN, "Blocked"),
                ("paused_fraction", PURPLE, "Paused"),
                ("idle_fraction", "#BFC9D1", "Idle"),
            ]
        ]
        return {"data": data, "layout": layout}
    trace = {
        "type": "scatter",
        "x": trace_values(stations.get_column("utilization")),
        "y": station_labels,
        "mode": "markers",
        "marker": {"size": 12, "color": BLUE, "line": {"color": "black", "width": 1}},
        "hovertemplate": "%{y}<br>Occupied capacity: %{x:.1%}<extra></extra>",
    }
    return {"data": [trace], "layout": layout}


# Server-state lines in legend order, with their colors and dashes.
RESOURCE_LINES = [
    ("processing", ORANGE, "Processing", "solid"),
    ("blocked", GREEN, "Blocked", "solid"),
    ("paused", PURPLE, "Paused", "solid"),
    ("down", "#222222", "Down", "solid"),
    ("available", GRAY, "Available", "dash"),
    ("scheduled", BLUE, "Scheduled", "dash"),
]
# Stacked server states from the bottom up. Each server counts in one layer.
RESOURCE_LAYERS = [
    ("processing", ORANGE, "Processing"),
    ("blocked", GREEN, "Blocked"),
    ("paused", PURPLE, "Paused"),
    ("down", "#222222", "Down"),
    ("idle", "#BFC9D1", "Idle"),
]


def server_layers(result: Results, station: str) -> pl.DataFrame:
    """Count one station's servers in each stacked layer at every states time.

    The states table counts each condition on its own, so a down server that
    holds a paused job is both paused and down there, and the table cannot
    say which down servers hold a job. This function rebuilds each server's
    condition after every event at each states time from the activities
    table (its job and phase), the failures table (its repairs), and the
    states table's scheduled count (server k is on duty while that count is
    at least k, since shifts staff the lowest-numbered servers). A server
    holding a job counts in its phase, a down server without a job counts as
    down, and an on-duty server that is up and has no job is idle. An
    off-duty server with no job and no repair is not counted. Thus, the
    layers sum to the scheduled servers plus any off-duty server that still
    holds a job or is under repair.
    """
    capacities = result.settings.capacities
    assert capacities is not None
    capacity = capacities[station]
    # The recorded count, not the staffing schedule, since a run that stops at
    # closing does not execute a shift change scheduled exactly then.
    times = result.states.filter(pl.col("station") == station).select(
        "time",
        "scheduled",
    )
    # Zero-length intervals hold no state after the events at their time.
    jobs = result.activities.filter(
        (pl.col("station") == station)
        & (pl.col("end").is_null() | (pl.col("end") > pl.col("start")))
    )
    repairs = result.failures.filter(
        (pl.col("station") == station)
        & (
            pl.col("repair_end").is_null()
            | (pl.col("repair_end") > pl.col("failure_time"))
        )
    )
    servers = []
    for server in range(1, capacity + 1):
        # A server's intervals never overlap, so the latest one that starts at
        # or before a time is the only one that can cover it.
        servers.append(
            times.join_asof(
                jobs.filter(pl.col("server_id") == server)
                .select("start", "end", "state")
                .sort("start"),
                left_on="time",
                right_on="start",
                strategy="backward",
            )
            .join_asof(
                repairs.filter(pl.col("server_id") == server)
                .select("failure_time", "repair_end")
                .sort("failure_time"),
                left_on="time",
                right_on="failure_time",
                strategy="backward",
            )
            .select(
                "time",
                pl.when(pl.col("end").is_null() | (pl.col("time") < pl.col("end")))
                .then(pl.col("state"))
                .alias("phase"),
                (
                    pl.col("failure_time").is_not_null()
                    & (
                        pl.col("repair_end").is_null()
                        | (pl.col("time") < pl.col("repair_end"))
                    )
                ).alias("down"),
                (pl.col("scheduled") >= server).alias("on_duty"),
            )
        )
    free = pl.col("phase").is_null()
    return (
        pl.concat(servers)
        .group_by("time", maintain_order=True)
        .agg(
            *[
                (pl.col("phase") == phase).sum().cast(pl.Int64).alias(phase)
                for phase in [Phase.PROCESSING, Phase.BLOCKED, Phase.PAUSED]
            ],
            (free & pl.col("down")).sum().cast(pl.Int64).alias("down"),
            (free & ~pl.col("down") & pl.col("on_duty"))
            .sum()
            .cast(pl.Int64)
            .alias("idle"),
            pl.col("on_duty").sum().cast(pl.Int64).alias("scheduled"),
        )
        .sort("time")
    )


def resources_figure(
    result: Results,
    station: str | None = None,
    stacked: bool = False,
) -> dict:
    """Return each station's server states over time, as lines or stacked.

    The lines are the states table's processing, blocked, paused, down,
    available, and scheduled counts, which overlap (e.g., a down server
    holding a paused job counts as both paused and down). The stacked view
    counts each server in one layer from server_layers and draws the
    scheduled count as a dashed line over the stack.
    """
    names = chosen_stations(result, station)
    figure = {
        "data": [],
        "layout": base_layout(
            x_label=f"Simulation time ({result.settings.time_unit})",
            y_label="Servers",
        ),
    }
    hover = "%{x:.2f} " + label(result.settings.time_unit)
    for index, place in enumerate(names):
        history = result.states.filter(pl.col("station") == place)
        times = trace_values(history.get_column("time"))
        if stacked:
            layers = server_layers(result, place)
            for field, color, name in RESOURCE_LAYERS:
                figure["data"].append(
                    {
                        "type": "scatter",
                        "x": times,
                        "y": trace_values(layers.get_column(field)),
                        "name": name,
                        "mode": "lines",
                        # Each station stacks its own layers.
                        "stackgroup": f"station {index}",
                        "line": {"shape": "hv", "color": color, "width": 0.5},
                        "fillcolor": color,
                        "visible": index == 0,
                        "meta": place,
                        "hovertemplate": hover
                        + "<br>%{y} servers<extra>%{fullData.name}</extra>",
                    }
                )
        lines = (
            [line for line in RESOURCE_LINES if line[0] == "scheduled"]
            if stacked
            else RESOURCE_LINES
        )
        for field, color, name, dash in lines:
            figure["data"].append(
                {
                    "type": "scatter",
                    "x": times,
                    "y": trace_values(history.get_column(field)),
                    "name": name,
                    "mode": "lines",
                    "line": {"shape": "hv", "color": color, "width": 2, "dash": dash},
                    "visible": index == 0,
                    "meta": place,
                    "hovertemplate": hover
                    + "<br>%{y} servers<extra>%{fullData.name}</extra>",
                }
            )
    station_menu(
        figure=figure,
        stations=names if station is None else [],
    )
    figure["layout"].update(
        legend={"orientation": "v", "x": 1.02, "y": 1},
        margin={"l": 85, "r": 175, "t": 60, "b": 70},
    )
    if result.settings.drain:
        dashed_line(
            figure,
            result.settings.duration,
            text="Closing",
            dash="dash",
        )
    warmup_line(figure, result)
    return figure


def timeline_spans(result: Results) -> pl.DataFrame:
    """Return every customer's timeline bars, grouped in TIMELINE_COLORS order.

    Waiting runs from station arrival to service start or abandonment, and the
    server activity rows give service, paused, and blocked time. A customer who
    waited outside a full buffer gets an "Outside" bar until admission or
    abandonment. An open end runs to the end time. Zero-length service writes no
    activity row, so it draws no bar.
    """
    waiting = result.visits.select(
        "customer_id",
        pl.lit("Waiting").alias("activity"),
        "station",
        pl.col("arrival_time").alias("start"),
        pl.coalesce("service_start", "abandon_time").alias("end"),
    )
    if not result._resources_vary:
        parts = [
            waiting,
            result.activities.select(
                "customer_id",
                pl.lit("In service").alias("activity"),
                "station",
                "start",
                "end",
            ),
        ]
    else:
        parts = [
            waiting,
            *[
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
            ],
        ]
    outside = result.customers.filter(
        (pl.col("status") == Status.OUTSIDE)
        | (pl.col("outside_wait").is_not_null() & (pl.col("outside_wait") != 0))
        | (
            (pl.col("status") == Status.ABANDONED)
            & pl.col("admission_time").is_null()
            & (pl.col("abandon_time") > pl.col("arrival_time"))
        )
    ).select(
        "customer_id",
        pl.lit("Outside").alias("activity"),
        pl.lit("Outside").alias("station"),
        pl.col("arrival_time").alias("start"),
        pl.coalesce("admission_time", "abandon_time").alias("end"),
    )
    if not outside.is_empty():
        parts.append(outside)
    return pl.concat(parts).with_columns(
        pl.col("end").fill_null(result.settings.end_time),
    )


def plot_customer(result: Results, customer_id: int) -> go.Figure:
    identifier = integer(customer_id, "Customer ID")
    if result.customers.filter(pl.col("customer_id") == identifier).is_empty():
        raise ValueError(f"Customer {identifier} does not exist in this run.")
    spans = timeline_spans(result).filter(pl.col("customer_id") == identifier)
    figure = go.Figure()
    for activity, color in TIMELINE_COLORS.items():
        bars = spans.filter(pl.col("activity") == activity)
        starts = bars.get_column("start").to_list()
        ends = bars.get_column("end").to_list()
        figure.add_trace(
            go.Bar(
                base=starts,
                x=[end - start for start, end in zip(starts, ends)],
                y=[label(station) for station in bars.get_column("station")],
                customdata=list(zip(starts, ends)),
                orientation="h",
                name=activity,
                marker={
                    "color": color,
                    "line": {"color": "black", "width": 1},
                },
                hovertemplate=(
                    "%{y}<br>%{customdata[0]:.2f}–%{customdata[1]:.2f} "
                    "(duration %{x:.2f})<extra>%{fullData.name}</extra>"
                ),
            )
        )
    style(
        figure=figure,
        x_label=f"Simulation time ({result.settings.time_unit})",
        y_label="Station",
    )
    figure.update_layout(barmode="overlay")
    figure.update_yaxes(autorange="reversed")
    return figure


def gantt_figure(
    result: Results,
    *,
    start: float = 0.0,
    end: float | None = None,
    station: str | None = None,
) -> dict:
    """Return a station-by-server Gantt chart of processing, blocked, and paused bars."""
    start_time = number(start, "Start time")
    end_limit = result.settings.end_time
    assert end_limit is not None
    stop_time = (
        end_limit
        if end is None
        else number(
            value=end,
            label="End time",
            positive=True,
        )
    )
    if stop_time <= start_time:
        raise ValueError("End time must be greater than start time.")
    names = chosen_stations(result, station)
    capacities = result.settings.capacities
    assert capacities is not None
    lanes = [
        f"{place} #{server_id}" if capacities[place] > 1 else place
        for place in names
        for server_id in range(1, capacities[place] + 1)
    ]
    rows = (
        result.activities.filter(pl.col("station").is_in(names))
        .with_columns(pl.col("end").fill_null(end_limit))
        .filter((pl.col("end") > start_time) & (pl.col("start") < stop_time))
        .with_columns(
            pl.col("start").clip(lower_bound=start_time).alias("clip_start"),
            pl.col("end").clip(upper_bound=stop_time).alias("clip_end"),
        )
    )
    unit = label(result.settings.time_unit)
    data = []
    for state_name, activity_label in [
        (Phase.PROCESSING, "In service"),
        (Phase.BLOCKED, "Blocked"),
        (Phase.PAUSED, "Paused"),
    ]:
        subset = rows.filter(pl.col("state") == state_name)
        if subset.is_empty():
            continue
        stations_col = subset.get_column("station").to_list()
        servers_col = subset.get_column("server_id").to_list()
        starts = subset.get_column("clip_start").to_list()
        ends = subset.get_column("clip_end").to_list()
        cids = subset.get_column("customer_id").to_list()
        y_vals = [
            label(f"{st} #{sid}" if capacities[st] > 1 else st)
            for st, sid in zip(stations_col, servers_col)
        ]
        data.append(
            {
                "type": "bar",
                "orientation": "h",
                "name": activity_label,
                "base": starts,
                "x": [e - s for s, e in zip(starts, ends)],
                "y": y_vals,
                "customdata": list(zip(cids, starts, ends)),
                "marker": {
                    "color": TIMELINE_COLORS[activity_label],
                    "line": {"color": "black", "width": 0.6},
                },
                "hovertemplate": (
                    f"%{{y}}<br>Customer %{{customdata[0]}}<br>"
                    f"%{{customdata[1]:.2f}}–%{{customdata[2]:.2f}} {unit} "
                    "(duration %{x:.2f})<extra>%{fullData.name}</extra>"
                ),
            }
        )
    layout = base_layout(
        x_label=f"Simulation time ({result.settings.time_unit})",
        y_label="Server",
    )
    layout["barmode"] = "overlay"
    layout["height"] = max(260, 150 + 42 * len(lanes))
    layout["xaxis"]["range"] = [start_time, stop_time]
    layout["yaxis"].update(
        categoryorder="array",
        categoryarray=[label(lane) for lane in lanes],
        autorange="reversed",
        automargin=True,
    )
    return {"data": data, "layout": layout}


def wip_figure(result: Results) -> dict:
    """Return total system WIP (inside and, if nonzero, outside) over time."""
    require_stations(result)
    # Collect every unique state-change time across stations and forward-fill each
    # station's waiting + busy and outside counts onto that common time axis.
    times_df = result.states.select("time").unique().sort("time")
    times = times_df.get_column("time").to_numpy()
    inside_total = np.zeros(times.size, dtype=float)
    outside_total = np.zeros(times.size, dtype=float)
    for _, frame in result.states.partition_by(
        "station",
        as_dict=True,
        maintain_order=True,
    ).items():
        st_times = frame.get_column("time").to_numpy()
        idx = np.clip(
            np.searchsorted(st_times, times, side="right") - 1, 0, st_times.size - 1
        )
        inside_total += (
            frame.get_column("waiting").to_numpy()[idx]
            + frame.get_column("busy").to_numpy()[idx]
        )
        outside_total += frame.get_column("outside").to_numpy()[idx]
    unit = label(result.settings.time_unit)
    figure: dict = {
        "data": [
            {
                "type": "scatter",
                "x": times.tolist(),
                "y": inside_total.tolist(),
                "name": "In system (WIP)",
                "mode": "lines",
                "line": {"shape": "hv", "color": BLUE, "width": 2},
                "hovertemplate": f"%{{x:.2f}} {unit}<br>%{{y:.0f}} customers<extra>In system</extra>",
            }
        ],
        "layout": base_layout(
            x_label=f"Simulation time ({result.settings.time_unit})",
            y_label="Customers",
        ),
    }
    if np.any(outside_total > 0):
        figure["data"].append(
            {
                "type": "scatter",
                "x": times.tolist(),
                "y": outside_total.tolist(),
                "name": "Waiting outside",
                "mode": "lines",
                "line": {"shape": "hv", "color": ORANGE, "width": 2, "dash": "dash"},
                "hovertemplate": f"%{{x:.2f}} {unit}<br>%{{y:.0f}} customers<extra>Outside</extra>",
            }
        )
    if result.settings.drain:
        dashed_line(
            figure,
            result.settings.duration,
            text="Closing",
            dash="dash",
        )
    warmup_line(figure, result)
    return figure


def warmup_figure(
    experiment: Experiment,
    *,
    metric: Literal["wip", "queue", "on_hand"] = "wip",
    station: str | None = None,
    stock_point: str | None = None,
    bin_width: float | None = None,
    window: int = 1,
) -> dict:
    """Build a Welch ensemble moving-average plot to diagnose warm-up duration."""
    if not all(run.records_kept for run in experiment.runs):
        raise ValueError(
            "experiment.plot_warmup() reads raw records. Rerun with keep_records=True."
        )
    if metric not in {"wip", "queue", "on_hand"}:
        raise ValueError(
            f"metric must be 'wip', 'queue', or 'on_hand', not {metric!r}."
        )
    smooth = integer(
        value=window,
        label="Moving-average window",
        minimum=1,
    )
    first = experiment.runs[0]
    duration = experiment.settings.duration
    unit = experiment.settings.time_unit
    if metric == "on_hand":
        names = experiment.stock_point_names
        if not names:
            raise ValueError("metric='on_hand' requires a supply chain model.")
        chosen = names[0] if stock_point is None else stock_point
        if chosen not in names:
            raise unknown(
                kind="stock point",
                name=chosen,
                choices=names,
                intro=f"Stock point {chosen!r} is not in this experiment.",
            )
        series_list = []
        times_ref: np.ndarray | None = None
        for run in experiment.runs:
            sub = run.inventory.filter(pl.col("stock_point") == chosen).sort("period")
            if times_ref is None:
                times_ref = sub.get_column("time").to_numpy()
            series_list.append(sub.get_column("on_hand").to_numpy())
        assert times_ref is not None
        grid = times_ref
        ensemble = np.mean(np.vstack(series_list), axis=0)
        y_label = f"Mean on-hand stock at {chosen}"
    else:
        require_stations(first)
        capacities = first.settings.capacities
        assert capacities is not None
        station_names = list(capacities)
        chosen_station: str | None = None
        if metric == "queue":
            chosen_station = station_names[0] if station is None else station
            if chosen_station not in capacities:
                raise unknown(
                    kind="station",
                    name=chosen_station,
                    choices=station_names,
                    intro=f"Station {chosen_station!r} is not in this experiment.",
                )
        step = (
            duration / 50.0
            if bin_width is None
            else number(
                value=bin_width,
                label="Bin width",
                positive=True,
            )
        )
        grid = np.arange(0.0, duration, step)
        if grid.size == 0:
            grid = np.array([0.0])
        acc = np.zeros(grid.size, dtype=float)
        for run in experiment.runs:
            if metric == "queue":
                sub = run.states.filter(pl.col("station") == chosen_station)
                st_times = sub.get_column("time").to_numpy()
                idx = np.clip(
                    np.searchsorted(st_times, grid, side="right") - 1,
                    0,
                    st_times.size - 1,
                )
                acc += sub.get_column("waiting").to_numpy()[idx]
            else:
                for _, frame in run.states.partition_by(
                    "station",
                    as_dict=True,
                    maintain_order=True,
                ).items():
                    st_times = frame.get_column("time").to_numpy()
                    idx = np.clip(
                        np.searchsorted(st_times, grid, side="right") - 1,
                        0,
                        st_times.size - 1,
                    )
                    acc += (
                        frame.get_column("waiting").to_numpy()[idx]
                        + frame.get_column("busy").to_numpy()[idx]
                    )
        ensemble = acc / len(experiment.runs)
        y_label = (
            f"Ensemble mean queue at {chosen_station}"
            if metric == "queue"
            else "Ensemble mean WIP (customers)"
        )
    data = []
    if smooth > 1 and ensemble.size > 1:
        kernel = np.ones(min(smooth, ensemble.size)) / min(smooth, ensemble.size)
        smoothed = np.convolve(ensemble, kernel, mode="same")
        data.append(
            {
                "type": "scatter",
                "x": grid.tolist(),
                "y": ensemble.tolist(),
                "name": f"Ensemble mean ({len(experiment.runs)} runs)",
                "mode": "lines",
                "line": {"color": "#BFC9D1", "width": 1.5},
            }
        )
        data.append(
            {
                "type": "scatter",
                "x": grid.tolist(),
                "y": smoothed.tolist(),
                "name": f"Welch moving average (window={smooth})",
                "mode": "lines",
                "line": {"color": BLUE, "width": 2.5},
            }
        )
    else:
        data.append(
            {
                "type": "scatter",
                "x": grid.tolist(),
                "y": ensemble.tolist(),
                "name": f"Ensemble mean ({len(experiment.runs)} runs)",
                "mode": "lines",
                "line": {"color": BLUE, "width": 2},
            }
        )
    figure: dict = {
        "data": data,
        "layout": base_layout(
            x_label=f"Simulation time ({unit})",
            y_label=y_label,
        ),
    }
    if experiment.settings.warmup > 0:
        dashed_line(
            figure,
            experiment.settings.warmup,
            text="Warm-up",
            dash="dot",
        )
    return figure


def service_payload(result: Results) -> dict:
    """Return the data the service-network run view draws."""
    figures = {
        "queues": queue_figure(result),
        "waits": wait_figure(result),
        "utilization": utilization_figure(result),
    }
    if result._resources_vary:
        figures["resources"] = resources_figure(result)
        # The page's switch swaps this figure into the resources chart.
        stacked = resources_figure(
            result,
            stacked=True,
        )
    else:
        stacked = None
    return {
        "kind": "service",
        "figures": figures,
        "stacked_resources": stacked,
        # Record tables go column by column, which is about half the size of
        # rows, and the run view rebuilds the rows it needs.
        "customers": result.customers.to_dict(as_series=False),
        "visits": result.visits.to_dict(as_series=False),
        # Table cells for these station metrics display as percentages.
        "percent_columns": [
            name for name, metric in METRICS.items() if metric.kind == "fraction"
        ],
        # Downloads use the export column order, even for empty tables.
        "columns": {
            "customers": result.customers.columns,
            "visits": result.visits.columns,
        },
        # The viewer draws these bars as given, so it matches plot_customer.
        "timeline": timeline_spans(result).to_dict(as_series=False),
        "timeline_colors": TIMELINE_COLORS,
        "failures": result.failures.to_dict(as_series=False),
        "stations": result.stations.to_dict(as_series=False),
        "summary": result.summary.to_dicts()[0],
        "duration": result.settings.duration,
        "end_time": result.settings.end_time,
        "drain": result.settings.drain,
        "warmup": result.settings.warmup,
        "time_unit": result.settings.time_unit,
        "seed": result.settings.seed,
    }


# Stock-point order traces cycle through these colors, after consumer demand.
STAGE_COLORS = [BLUE, ORANGE, GREEN, PURPLE, "#E69F00", "#56B4E9"]


def orders_figure(result: Results) -> dict:
    """Return consumer demand and every stage's orders, which shows the bullwhip."""
    names = chosen_stock_points(result, None)
    # chosen_stock_points raises for a run without a supply chain.
    supply = result.supply
    assert supply is not None
    retailer = result.inventory.filter(pl.col("stock_point") == names[0])
    figure = {
        "data": [
            {
                "type": "scatter",
                "x": trace_values(retailer.get_column("time")),
                "y": trace_values(retailer.get_column("demand")),
                "name": label(supply.chain[0]),
                "mode": "lines",
                "line": {"color": GRAY, "width": 2, "dash": "dot"},
            }
        ],
        "layout": base_layout(
            x_label=f"Review time ({result.settings.time_unit})",
            y_label="Units per period",
        ),
    }
    for index, name in enumerate(names):
        rows = result.inventory.filter(pl.col("stock_point") == name)
        figure["data"].append(
            {
                "type": "scatter",
                "x": trace_values(rows.get_column("time")),
                "y": trace_values(rows.get_column("order_quantity")),
                "name": label(f"{name} orders"),
                "mode": "lines",
                "line": {"color": STAGE_COLORS[index % len(STAGE_COLORS)], "width": 2},
            }
        )
    warmup_line(figure, result)
    # Startup orders can dwarf the measured weeks, so the initial view scales
    # to the periods after warm-up. Autoscaling restores the full range.
    measured = result.inventory.filter(pl.col("time") >= result.settings.warmup)
    if result.settings.warmup > 0 and not measured.is_empty():
        top = measured.select(
            pl.max_horizontal(
                pl.col("order_quantity").max(),
                pl.col("demand").max(),
            )
        ).item()
        figure["layout"]["yaxis"]["range"] = [0, max(1.0, 1.05 * top)]
    return figure


def inventory_figure(result: Results, stock_point: str | None = None) -> dict:
    """Return a stock point's stock, backorders, and orders over review times.

    Without a stock point, a menu chooses among the stock points, and the
    first is shown. A named stock point is the only one drawn.
    """
    names = chosen_stock_points(result, stock_point)
    figure = {
        "data": [],
        "layout": base_layout(
            x_label=f"Review time ({result.settings.time_unit})",
            y_label="Units at the end of the period",
        ),
    }
    fields = [
        ("on_hand", BLUE, "On hand", "solid"),
        ("backorders", ORANGE, "Backorders", "solid"),
        ("order_quantity", GREEN, "Orders placed", "solid"),
        ("demand", GRAY, "Orders received", "dot"),
    ]
    for index, name in enumerate(names):
        rows = result.inventory.filter(pl.col("stock_point") == name)
        for field, color, trace_name, dash in fields:
            figure["data"].append(
                {
                    "type": "scatter",
                    "x": trace_values(rows.get_column("time")),
                    "y": trace_values(rows.get_column(field)),
                    "name": trace_name,
                    "mode": "lines",
                    "line": {"color": color, "width": 2, "dash": dash},
                    "visible": index == 0,
                    "meta": name,
                }
            )
    station_menu(
        figure=figure,
        stations=names if stock_point is None else [],
    )
    warmup_line(figure, result)
    return figure


def supply_payload(result: Results) -> dict:
    """Return the data the supply-chain run view draws."""
    figures = {
        "orders": orders_figure(result),
        "inventory": inventory_figure(result),
    }
    # A top stage that produces adds its stations, whose customers are jobs.
    if result.settings.capacities:
        queues = queue_figure(result)
        queues["layout"]["yaxis"]["title"]["text"] = "Jobs"
        for trace in queues["data"]:
            trace["hovertemplate"] = (
                f"%{{x:.2f}} {label(result.settings.time_unit)}"
                "<br>%{y} jobs<extra>%{fullData.name}</extra>"
            )
        figures["queues"] = queues
        figures["utilization"] = utilization_figure(result)
    # orders_figure above raises for a run without a supply chain.
    supply = result.supply
    assert supply is not None
    return {
        "kind": "supply",
        "figures": figures,
        "chain": list(supply.chain),
        "period": supply.period,
        # Record tables go column by column, as in service_payload.
        "stock_points": result.stock_points.to_dict(as_series=False),
        "inventory": result.inventory.to_dict(as_series=False),
        "shipments": result.shipments.to_dict(as_series=False),
        "stations": result.stations.to_dict(as_series=False),
        "jobs": result.customers.to_dict(as_series=False),
        "summary": result.summary.to_dicts()[0],
        # Downloads use the export column order, even for empty tables.
        "columns": {
            "inventory": result.inventory.columns,
            "shipments": result.shipments.columns,
            "jobs": result.customers.columns,
        },
        "percent_columns": [
            name for name, metric in METRICS.items() if metric.kind == "fraction"
        ],
        "duration": result.settings.duration,
        "warmup": result.settings.warmup,
        "time_unit": result.settings.time_unit,
        "seed": result.settings.seed,
    }


def run_payload(result: Results) -> dict:
    """Return one run's data for a run view, the service or supply-chain one."""
    return (
        supply_payload(result) if result.supply is not None else service_payload(result)
    )


@functools.cache
def page_template() -> dict:
    """Return the template plotly_figure gives every figure, as page JSON."""
    text = go.Figure(layout={"template": "plotly_white"}).to_json()
    # Plotly returns None only for a JSON engine it does not know, and it
    # rejects one before that point.
    assert text is not None
    return json.loads(text)["layout"]["template"]


def page_json(payload: object) -> str:
    """Return compact JSON that is safe inside a page's script element.

    Escaping '<' keeps model labels from ending the script element.
    """
    return json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")


@functools.cache
def _read_template(name: str) -> str:
    return Path(__file__).with_name(name).read_text(encoding="utf-8")


def fill_template(name: str, values: dict[str, str]) -> str:
    """Fill a page template's __NAME__ placeholders in one pass.

    One pass means a placeholder-like name inside a value (e.g., in a
    scenario name or in Plotly's code) is never replaced.
    """
    template = _read_template(name)
    return re.sub(
        pattern=r"__([A-Z_]+)__",
        repl=lambda match: values[match.group(1)],
        string=template,
    )


# Plotly's cartesian bundle draws the scatter, bar, and histogram traces the
# pages use at about a third of the full library's size, which the browser
# parses on every page load. tests/test_dashboard.py checks that its version
# matches the installed plotly package and that it holds every trace type
# FlowSim draws. Replace the file when plotly is upgraded, from
# https://cdn.jsdelivr.net/npm/plotly.js-cartesian-dist-min@VERSION/plotly-cartesian.min.js
PLOTLY_BUNDLE = "plotly-cartesian.min.js"


@functools.cache
def _static_page_parts() -> dict[str, str]:
    folder = Path(__file__).parent
    return {
        "STYLE": (folder / "page.css").read_text(encoding="utf-8"),
        "PLOTLY_JS": (folder / PLOTLY_BUNDLE).read_text(encoding="utf-8"),
        "TEMPLATE_JSON": page_json(page_template()),
        "SERVICE_RUN": (folder / "service_run.html").read_text(encoding="utf-8"),
        "SUPPLY_RUN": (folder / "supply_run.html").read_text(encoding="utf-8"),
    }


def page_parts() -> dict[str, str]:
    """Return the style, Plotly, template, and run views that every page holds."""
    return dict(_static_page_parts())


def run_page_html(result: Results) -> str:
    """Return the offline page of one run."""
    with building_page():
        payload = run_payload(result)
    heading = (
        "FlowSim supply chain" if payload["kind"] == "supply" else "FlowSim results"
    )
    return fill_template(
        "run.html",
        {
            **page_parts(),
            "HEADING": heading,
            "RESULT_JSON": page_json(payload),
        },
    )
