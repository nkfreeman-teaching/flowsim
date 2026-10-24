"""Translate network definitions into private scheduler processes."""

from __future__ import annotations

import math
import zlib
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, replace
from typing import TYPE_CHECKING

import numpy as np

from flowsim.results import (
    SUPPLIER,
    Results,
    Status,
    _Activity,
    _Customer,
    _Failure,
    _Inventory,
    _Shipment,
    _State,
    _Visit,
)
from flowsim.scheduler import Event, Scheduler
from flowsim.schedules import next_arrival
from flowsim.station import _Station
from flowsim.validation import sample

if TYPE_CHECKING:
    from flowsim.model import Model, Node

# The scheduler processes events at equal times by priority, then in the order
# they were queued. Shift changes come first (the scheduler's SHIFT_PRIORITY, 1).
# Completions, transfers, failures, and repairs use NORMAL (2) and run in the
# order they were scheduled. Arrivals wait until those events settle. Stock-point
# reviews come after arrivals, and drain checks run last, after every other
# event at the same time.
ARRIVAL_PRIORITY = 3
REVIEW_PRIORITY = 4
SETTLED_PRIORITY = 5

# Each node's seeds use its name's CRC-32 and one of these purposes as the spawn
# key. Server failure and repair seeds are spawned from the SERVER_STREAMS seed.
DURATION_STREAM = 0
ROUTING_STREAM = 1
SERVER_STREAMS = 2
TYPE_STREAM = 3


@dataclass(
    frozen=True,
    slots=True,
)
class _Streams:
    """A node's generators for its durations, routing choices, and types.

    A source draws interarrival times from durations and its customers' types
    from types, and a station draws service times from durations.
    """

    durations: np.random.Generator
    routing: np.random.Generator
    types: np.random.Generator


@dataclass(
    frozen=True,
    slots=True,
)
class _Route:
    """A node's destinations and, when it branches, their probabilities."""

    destinations: tuple[Node, ...]
    probabilities: np.ndarray | None


@dataclass(slots=True)
class _Stock:
    """A stock point's running state during one run.

    The pipeline holds shipments on the way as (receipt period, record) pairs in
    sending order, so receipts come off its front.
    """

    node: Node
    cover: float
    rng: np.random.Generator
    on_hand: float
    backorders: float = 0.0
    on_order: float = 0.0
    history: list[float] = field(default_factory=list)
    pipeline: deque[tuple[int, _Shipment]] = field(default_factory=deque)


class _Same:
    """Compare a sampling function by identity inside a definition key."""

    __slots__ = ("value",)

    def __init__(self, value: object):
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Same) and other.value is self.value


class _Run:
    def __init__(
        self,
        model: Model,
        duration: float,
        warmup: float,
        seed: int,
        drain: bool,
    ):
        self.model = model
        self.duration = duration
        self.warmup = warmup
        self.seed = seed
        self.drain = drain
        self.scheduler = Scheduler()
        self.customers: list[_Customer] = []
        self.visits: list[_Visit] = []
        self.histories: dict[str, list[_State]] = {}
        self.activities: list[_Activity] = []
        self.failures: list[_Failure] = []
        self.inventory: list[_Inventory] = []
        self.shipments: list[_Shipment] = []
        self.closed = False
        self.active_customers = 0
        self.finished = self.scheduler.event()
        self.streams: dict[str, _Streams] = {}
        nodes = model.nodes
        names = list(nodes)
        keys: dict[str, int] = {}
        owners: dict[int, str] = {}
        for name in names:
            key = zlib.crc32(name.encode())
            if key in owners:
                raise ValueError(
                    f"Node names {owners[key]!r} and {name!r} share a random-stream "
                    "key. Rename one of them."
                )
            owners[key] = name
            keys[name] = key

        def node_seed(name: str, purpose: int) -> np.random.SeedSequence:
            # A node's streams depend only on the seed and its own name, so
            # adding or removing another node leaves its draws unchanged.
            return np.random.SeedSequence(
                entropy=seed,
                spawn_key=(keys[name], purpose),
            )

        for name in names:
            self.streams[name] = _Streams(
                durations=np.random.default_rng(node_seed(name, DURATION_STREAM)),
                routing=np.random.default_rng(node_seed(name, ROUTING_STREAM)),
                types=np.random.default_rng(node_seed(name, TYPE_STREAM)),
            )
        # Routes are fixed for the run, so each node's choices are built once,
        # keyed by customer type, where None is a route for every type.
        self.routes: dict[str, dict[str | None, _Route]] = {}
        for name, table in model.routing.items():
            self.routes[name] = {}
            for kind, choices in table.items():
                probabilities = None
                if len(choices) > 1:
                    probabilities = np.asarray(
                        [probability for _, probability in choices],
                        dtype=float,
                    )
                    # Normalize floating-point roundoff after the model's
                    # sum-to-one check.
                    probabilities /= probabilities.sum()
                self.routes[name][kind] = _Route(
                    destinations=tuple(
                        nodes[destination] for destination, _ in choices
                    ),
                    probabilities=probabilities,
                )
        self.stations: dict[str, _Station] = {}
        for name in names:
            node = nodes[name]
            if node.kind == "station":
                self.histories[name] = []
                self.stations[name] = _Station(
                    run=self,
                    node=node,
                    seed=node_seed(name, SERVER_STREAMS),
                )
                self.observe(name)
        chain = model.supply_chain
        # The chain runs from the retailer, nearest demand, up to the top stage.
        # A constant lead time is a whole number of periods, which Model.supply
        # checks, so rounding removes floating-point remainders from its cover.
        self.stocks = [
            _Stock(
                node=node,
                cover=(
                    round(node.lead_time / chain.period)
                    if node.policy.cover is None
                    else node.policy.cover
                ),
                rng=self.streams[node.name].durations,
                on_hand=node.initial,
            )
            for node in ([] if chain is None else chain.stock_points)
        ]

    def settled(self) -> Event:
        """Wake after every other event at the current time."""
        return self.scheduler.timeout(0, priority=SETTLED_PRIORITY)

    def observe(self, name: str) -> None:
        """Record the state after a change, retaining the last state at ties."""
        row = _State(
            station=name,
            time=float(self.scheduler.now),
            **self.stations[name].state(),
        )
        history = self.histories[name]
        if history and history[-1].time == row.time:
            history[-1] = row
        else:
            history.append(row)

    def definition(self) -> tuple:
        """Return a key that only runs of the same model definition share.

        Sampling functions match only when they are the same object, so two
        separately built models with their own lambdas never match.
        """

        def key(value: object) -> object:
            if callable(value):
                return _Same(value)
            if isinstance(value, Mapping):
                return tuple((name, key(item)) for name, item in value.items())
            return value

        nodes = tuple(
            tuple(key(getattr(node, field.name)) for field in fields(node))
            for node in self.model.nodes.values()
        )
        routes = tuple(
            (origin, kind, choices)
            for origin, table in self.model.routing.items()
            for kind, choices in table.items()
        )
        chain = self.model.supply_chain
        supply = (
            None
            if chain is None
            else (
                chain.demand.name,
                tuple(node.name for node in chain.stock_points),
                chain.period,
            )
        )
        return (self.model.time_unit, nodes, routes, supply)

    def next_node(self, name: str, customer: _Customer) -> Node:
        # Model.validate checks that each type reaching a node has a route.
        table = self.routes[name]
        route = table[None] if None in table else table[customer.customer_type]
        if route.probabilities is None:
            return route.destinations[0]
        index = self.streams[name].routing.choice(
            len(route.destinations),
            p=route.probabilities,
        )
        return route.destinations[index]

    def next_arrival_time(self, node: Node, rng: np.random.Generator) -> float | None:
        now = float(self.scheduler.now)
        if node.arrival_rates is not None:
            return next_arrival(
                points=node.arrival_rates,
                now=now,
                horizon=self.duration,
                rng=rng,
            )
        gap = sample(
            distribution=node.interarrival,
            rng=rng,
            label=f"Interarrival time at {node.name!r}",
            positive=True,
        )
        arrival = now + gap
        # From time 0, a gap too small to move the clock at the duration
        # creeps forward in steps that cannot reach it.
        if arrival <= now or self.duration + gap == self.duration:
            raise ValueError(
                f"Interarrival time {gap!r} at {node.name!r} is too small for the "
                f"simulation clock to advance in a run of duration {self.duration!r}."
            )
        return arrival

    def source(self, node: Node):
        rng = self.streams[node.name].durations
        kinds = None if node.types is None else list(node.types)
        weights = None
        if kinds is not None and len(kinds) > 1:
            weights = np.asarray(list(node.types.values()), dtype=float)
            weights /= weights.sum()
        if node.limit == 0:
            return
        arrival = node.first_arrival
        if arrival is None:
            arrival = self.next_arrival_time(node, rng)
        produced = 0
        # The limit is checked after each arrival, before sampling another gap.
        while arrival is not None and arrival < self.duration:
            yield self.scheduler.timeout(
                arrival - self.scheduler.now,
                priority=ARRIVAL_PRIORITY,
            )
            # A source with one type draws nothing for it.
            kind = None
            if weights is not None:
                kind = kinds[
                    self.streams[node.name].types.choice(len(kinds), p=weights)
                ]
            elif kinds is not None:
                kind = kinds[0]
            customer = _Customer(
                customer_id=len(self.customers) + 1,
                source=node.name,
                customer_type=kind,
                arrival_time=float(self.scheduler.now),
            )
            self.customers.append(customer)
            self.active_customers += 1
            self.scheduler.process(self.customer(customer, node))
            produced += 1
            if node.limit is not None and produced >= node.limit:
                return
            arrival = self.next_arrival_time(node, rng)

    def customer(self, customer: _Customer, source: Node):
        node = self.next_node(source.name, customer)
        if node.kind == "exit":
            customer.admitted = True
            customer.admission_time = float(self.scheduler.now)
            customer.outside_wait = 0.0
        else:
            station = self.stations[node.name]
            ticket = station.admit(customer, external=True)
            if ticket is None:
                self.complete_active()
                return
            yield ticket.admitted
            while True:
                yield ticket.finished
                destination = self.next_node(node.name, customer)
                if destination.kind == "exit":
                    station.release(ticket)
                    break
                downstream = self.stations[destination.name]
                next_ticket = downstream.admit(customer, external=False)
                yield next_ticket.admitted
                station.release(ticket)
                node = destination
                station = downstream
                ticket = next_ticket
        customer.exit_time = float(self.scheduler.now)
        customer.flow_time = self.scheduler.now - customer.arrival_time
        customer.status = Status.COMPLETED
        customer.station = None
        self.complete_active()

    def complete_active(self) -> None:
        self.active_customers -= 1
        if self.closed and self.active_customers == 0 and not self.finished.triggered:
            self.finished.succeed()

    def supply(self):
        """Review every stock point once per period, from the retailer upward."""
        chain = self.model.supply_chain
        period = 0
        while period * chain.period < self.duration:
            yield self.scheduler.timeout(
                period * chain.period - self.scheduler.now,
                priority=REVIEW_PRIORITY,
            )
            self.review(period)
            period += 1

    def review(self, period: int) -> None:
        """Run one period's receipts, fills, and orders at every stage.

        Each stage fills the order its downstream stage placed in this period,
        so a stage's incoming orders are the retailer's consumer demand or the
        order quantity just set below it.
        """
        chain = self.model.supply_chain
        time = period * chain.period
        consumers = sample(
            distribution=chain.demand.per_period,
            rng=self.streams[chain.demand.name].durations,
            label=f"Demand at {chain.demand.name!r}",
        )
        incoming = consumers
        for index, stock in enumerate(self.stocks):
            downstream = self.stocks[index - 1] if index else None
            received = 0.0
            while stock.pipeline and stock.pipeline[0][0] <= period:
                _, shipment = stock.pipeline.popleft()
                shipment.arrival_time = time
                received += shipment.quantity
            stock.on_hand += received
            stock.on_order -= received
            # Backorders are older than this period's orders, so they ship first.
            late = min(stock.on_hand, stock.backorders)
            filled = min(stock.on_hand - late, incoming)
            stock.on_hand -= late + filled
            stock.backorders -= late
            lost = 0.0
            if stock.node.shortage == "backorder":
                stock.backorders += incoming - filled
            else:
                lost = incoming - filled
                # The downstream stage will never receive a lost order.
                if downstream is not None:
                    downstream.on_order -= lost
            if downstream is not None and late + filled > 0:
                self.ship(
                    sender=stock.node.name,
                    receiver=downstream,
                    quantity=late + filled,
                    period=period,
                )
            stock.history.append(
                consumers if stock.node.forecast_from == "end_demand" else incoming
            )
            forecast, target = stock.node.policy.target(stock.history, stock.cover)
            position = stock.on_hand + stock.on_order - stock.backorders
            order = max(0.0, target - position)
            stock.on_order += order
            self.inventory.append(
                _Inventory(
                    stock_point=stock.node.name,
                    period=period,
                    time=time,
                    received=received,
                    demand=incoming,
                    filled=filled,
                    shipped=late + filled,
                    lost=lost,
                    on_hand=stock.on_hand,
                    backorders=stock.backorders,
                    on_order=stock.on_order,
                    position=position + order,
                    forecast=forecast,
                    target=target,
                    order_quantity=order,
                )
            )
            incoming = order
        if incoming > 0:
            self.ship(
                sender=SUPPLIER,
                receiver=self.stocks[-1],
                quantity=incoming,
                period=period,
            )

    def ship(self, sender: str, receiver: _Stock, quantity: float, period: int) -> None:
        """Send a shipment that the receiver adds to stock at a later review.

        A shipment arrives at the first review at or after its lead time, at
        least one period later, and never before an earlier shipment to the same
        receiver.
        """
        node = receiver.node
        length = self.model.supply_chain.period
        if callable(node.lead_time):
            lead_time = sample(
                distribution=node.lead_time,
                rng=receiver.rng,
                label=f"Lead time at {node.name!r}",
                positive=True,
            )
            # The tolerance keeps a lead time of exactly k periods, computed in
            # floating point, from rounding up to k + 1.
            periods = max(1, math.ceil(lead_time / length - 1e-9))
        else:
            lead_time = node.lead_time
            periods = round(lead_time / length)
        due = period + periods
        if receiver.pipeline:
            due = max(due, receiver.pipeline[-1][0])
        shipment = _Shipment(
            sender=sender,
            receiver=node.name,
            quantity=quantity,
            ship_time=period * length,
            lead_time=lead_time,
        )
        self.shipments.append(shipment)
        receiver.pipeline.append((due, shipment))

    def supply_settings(self) -> dict | None:
        chain = self.model.supply_chain
        if chain is None:
            return None
        return {
            "chain": [chain.demand.name, *[node.name for node in chain.stock_points]],
            "period": chain.period,
            "stock_points": {
                stock.node.name: {
                    "initial": stock.node.initial,
                    "lead_time": (
                        "sampled"
                        if callable(stock.node.lead_time)
                        else stock.node.lead_time
                    ),
                    "cover": stock.cover,
                    "shortage": stock.node.shortage,
                    "forecast_from": stock.node.forecast_from,
                    "window": stock.node.policy.forecast.window,
                    "safety_factor": stock.node.policy.safety_factor,
                }
                for stock in self.stocks
            },
        }

    def execute(self) -> Results:
        for node in self.model.nodes.values():
            if node.kind == "source":
                self.scheduler.process(self.source(node))
        if self.stocks:
            self.scheduler.process(self.supply())
        self.scheduler.run(until=self.duration)
        self.closed = True
        closing_states = {}
        for name in self.histories:
            self.observe(name)
            closing_states[name] = replace(self.histories[name][-1])
        if self.drain:
            if self.active_customers == 0:
                self.finished.succeed()
            for station in self.stations.values():
                station.check_drain()
            # Stop at the final customer, excluding future shift changes,
            # recurring failures, and unused interrupted-service timeouts.
            self.scheduler.run(until=self.finished)
            for name in self.histories:
                self.observe(name)
        states = [row for history in self.histories.values() for row in history]
        # A phase that starts and ends at the same instant carries no time.
        activities = [
            row for row in self.activities if row.end is None or row.end > row.start
        ]
        return Results(
            customers=self.customers,
            visits=self.visits,
            states=states,
            activities=activities,
            failures=self.failures,
            inventory=self.inventory,
            shipments=self.shipments,
            supply=self.supply_settings(),
            definitions={
                name: {
                    "types": None if node.types is None else dict(node.types),
                    "arrival_rates": node.arrival_rates,
                    "staffing": node.staffing,
                    "shift_end": node.shift_end,
                    "buffer": node.buffer,
                    "external_overflow": node.external_overflow,
                    "failure_clock": node.failure_clock,
                    "failures_enabled": node.time_to_failure is not None,
                }
                for name, node in self.model.nodes.items()
                if node.kind in {"source", "station", "exit"}
            },
            capacities={
                name: station.node.capacity for name, station in self.stations.items()
            },
            duration=self.duration,
            end_time=float(self.scheduler.now),
            drain=self.drain,
            closing_states=closing_states,
            warmup=self.warmup,
            time_unit=self.model.time_unit,
            seed=self.seed,
            graph=self.model.graph,
            definition=self.definition(),
        )


def simulate(
    model: Model,
    duration: float,
    warmup: float,
    seed: int,
    drain: bool,
) -> Results:
    return _Run(
        model=model,
        duration=duration,
        warmup=warmup,
        seed=seed,
        drain=drain,
    ).execute()
