"""Forecasts and ordering policies for stock points, independent of the engine.

A stock point reviews once per period, after that period's demand. Its target
is cover times the forecast plus safety stock, and it orders the shortfall of
its inventory position below the target, never a negative quantity.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Real

from flowsim.validation import integer, number


@dataclass(frozen=True)
class MovingAverage:
    """Forecast one period's demand as the mean of the last window observations."""

    window: int

    def forecast(self, history: Sequence[float]) -> float:
        # Before window periods have passed, the mean uses every observation so
        # far. A review always follows at least one observation.
        recent = history[-self.window :]
        return sum(recent) / len(recent)


@dataclass(frozen=True)
class OrderUpTo:
    """Raise the inventory position to cover * forecast + safety stock."""

    forecast: MovingAverage
    safety_factor: float
    cover: float | None = None

    def target(self, history: Sequence[float], cover: float) -> tuple[float, float]:
        """Return the forecast and the target for a known cover in periods.

        Safety stock is safety_factor * sqrt(cover) times the sample standard
        deviation (n - 1 divisor) of the demands in the forecast window. It is
        zero until the window is full, since a deviation from two or three early
        observations can set a target far above steady demand.
        """
        forecast = self.forecast.forecast(history)
        safety = 0.0
        recent = history[-self.forecast.window :]
        if self.safety_factor > 0 and len(recent) == self.forecast.window:
            mean = sum(recent) / len(recent)
            variance = sum((value - mean) ** 2 for value in recent) / (len(recent) - 1)
            safety = self.safety_factor * math.sqrt(cover) * math.sqrt(variance)
        return forecast, cover * forecast + safety


def moving_average(*, window: int) -> MovingAverage:
    return MovingAverage(
        integer(
            value=window,
            label="Moving-average window",
            minimum=1,
        )
    )


def order_up_to(
    *,
    forecast: MovingAverage,
    safety_factor: Real,
    cover: Real | None = None,
) -> OrderUpTo:
    """Define an order-up-to policy.

    cover is the number of periods of forecast demand the target covers. Leave
    it out for a constant lead time, where cover is lead_time / period, and give
    it for a sampled lead time, whose mean FlowSim does not estimate.
    """
    if not isinstance(forecast, MovingAverage):
        raise ValueError("forecast must come from flowsim.moving_average.")
    factor = number(safety_factor, "Safety factor")
    if factor > 0 and forecast.window < 2:
        raise ValueError(
            "Safety stock uses the spread of the forecast window, so a positive "
            "safety factor needs a moving-average window of at least 2."
        )
    periods = (
        None
        if cover is None
        else number(
            value=cover,
            label="Cover",
            positive=True,
        )
    )
    return OrderUpTo(
        forecast=forecast,
        safety_factor=factor,
        cover=periods,
    )
