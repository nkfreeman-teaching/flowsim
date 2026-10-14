"""Translate network definitions into private SimPy processes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import simpy

from flowsim.model import Node, sample
from flowsim.schedules import next_arrival
from flowsim.station import _Station

if TYPE_CHECKING:
    from flowsim.model import Model
    from flowsim.results import Results

# SimPy processes events at equal times by priority, then by creation order.
# Shift changes, completions, transfers, failures, and repairs use SimPy's
# NORMAL priority (1). Arrivals wait until those events settle, and drain
# checks run last, after every other event at the same time.
ARRIVAL_PRIORITY = 2
SETTLED_PRIORITY = 3


class _Wake(simpy.Event):
    """A timeout with a chosen priority, initialized like simpy.Timeout."""

    def __init__(self, env: simpy.Environment, delay: float, priority: int):
        super().__init__(env)
        self._ok = True
        self._value = None
        env.schedule(self, priority, delay)


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
        self.env = simpy.Environment()
        self.customers: list[dict] = []
        self.visits: list[dict] = []
        self.histories: dict[str, list[dict]] = {}
        self.activities: list[dict] = []
        self.failures: list[dict] = []
        self.closed = False
        self.active_customers = 0
        self.finished = self.env.event()
        self.streams: dict[str, tuple[np.random.Generator, np.random.Generator]] = {}
        names = sorted(model._nodes)
        root = np.random.SeedSequence(seed)
        # Each node has a duration stream and a routing stream. A third set of
        # children seeds server failure and repair streams. The spawn order
        # fixes every stream for a given seed and set of node names.
        seeds = root.spawn(2 * len(names))
        for index, name in enumerate(names):
            self.streams[name] = (
                np.random.default_rng(seeds[2 * index]),
                np.random.default_rng(seeds[2 * index + 1]),
            )
        server_seeds = root.spawn(len(names))
        self.stations: dict[str, _Station] = {}
        for index, name in enumerate(names):
            node = model._nodes[name]
            if node.kind == "station":
                self.histories[name] = []
                self.stations[name] = _Station(
                    run=self,
                    node=node,
                    seed=server_seeds[index],
                )
                self.observe(name)

    def settled(self) -> _Wake:
        """Wake after every other event at the current time."""
        return _Wake(self.env, 0, SETTLED_PRIORITY)

    def observe(self, name: str) -> None:
        """Record the state after a change, retaining the last state at ties."""
        row = {
            "station": name,
            "time": float(self.env.now),
            **self.stations[name].state(),
        }
        history = self.histories[name]
        if history and history[-1]["time"] == row["time"]:
            history[-1] = row
        else:
            history.append(row)

    def next_node(self, name: str) -> Node:
        destinations = list(self.model._graph.successors(name))
        if len(destinations) == 1:
            return self.model._nodes[destinations[0]]
        probabilities = [
            self.model._graph[name][destination]["probability"]
            for destination in destinations
        ]
        # Normalize floating-point roundoff after the model's sum-to-one check.
        probabilities = np.asarray(probabilities, dtype=float)
        probabilities /= probabilities.sum()
        index = self.streams[name][1].choice(len(destinations), p=probabilities)
        return self.model._nodes[destinations[index]]

    def next_arrival_time(self, node: Node, rng: np.random.Generator) -> float | None:
        now = float(self.env.now)
        if node.arrival_rates is not None:
            return next_arrival(
                points=node.arrival_rates,
                now=now,
                horizon=self.duration,
                rng=rng,
            )
        arrival = now + sample(
            distribution=node.duration,
            rng=rng,
            label=f"Interarrival time at {node.name!r}",
            positive=True,
        )
        if arrival <= now:
            raise ValueError(
                f"Interarrival time at {node.name!r} is too small for the "
                f"simulation clock to advance from {now!r}."
            )
        return arrival

    def source(self, node: Node):
        rng = self.streams[node.name][0]
        if node.limit == 0:
            return
        arrival = node.first_arrival
        if arrival is None:
            arrival = self.next_arrival_time(node, rng)
        produced = 0
        while (
            arrival is not None
            and arrival < self.duration
            and (node.limit is None or produced < node.limit)
        ):
            yield _Wake(self.env, arrival - self.env.now, ARRIVAL_PRIORITY)
            customer = {
                "customer_id": len(self.customers) + 1,
                "source": node.name,
                "arrival_time": float(self.env.now),
                "exit_time": None,
                "flow_time": None,
                "total_wait": 0.0,
                "total_blocked": 0.0,
                "admitted": False,
                "admission_time": None,
                "outside_wait": None,
                "status": "arriving",
                "station": None,
            }
            self.customers.append(customer)
            self.active_customers += 1
            self.env.process(self.customer(customer, node))
            produced += 1
            if node.limit is not None and produced >= node.limit:
                return
            arrival = self.next_arrival_time(node, rng)

    def customer(self, customer: dict, source: Node):
        node = self.next_node(source.name)
        if node.kind == "exit":
            customer["admitted"] = True
            customer["admission_time"] = float(self.env.now)
            customer["outside_wait"] = 0.0
        else:
            station = self.stations[node.name]
            ticket = station.admit(customer, external=True)
            if ticket is None:
                self.complete_active()
                return
            yield ticket.admitted
            while True:
                yield ticket.finished
                destination = self.next_node(node.name)
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
        customer["exit_time"] = float(self.env.now)
        customer["flow_time"] = self.env.now - customer["arrival_time"]
        customer["status"] = "completed"
        customer["station"] = None
        self.complete_active()

    def complete_active(self) -> None:
        self.active_customers -= 1
        if self.closed and self.active_customers == 0 and not self.finished.triggered:
            self.finished.succeed()

    def execute(self) -> Results:
        from flowsim.results import Results

        for node in self.model._nodes.values():
            if node.kind == "source":
                self.env.process(self.source(node))
        self.env.run(until=self.duration)
        self.closed = True
        closing_states = {}
        for name in self.histories:
            self.observe(name)
            closing_states[name] = self.histories[name][-1].copy()
        if self.drain:
            if self.active_customers == 0:
                self.finished.succeed()
            for station in self.stations.values():
                station.check_drain()
            # Stop at the final customer, excluding future shift changes,
            # recurring failures, and unused interrupted-service timeouts.
            self.env.run(until=self.finished)
            for name in self.histories:
                self.observe(name)
        states = [row for history in self.histories.values() for row in history]
        # A phase that starts and ends at the same instant carries no time.
        activities = [
            row
            for row in self.activities
            if row["end"] is None or row["end"] > row["start"]
        ]
        return Results(
            customers=self.customers,
            visits=self.visits,
            states=states,
            activities=activities,
            failures=self.failures,
            definitions={
                name: {
                    "arrival_rates": node.arrival_rates,
                    "staffing": node.staffing,
                    "shift_end": node.shift_end,
                    "buffer": node.buffer,
                    "external_overflow": node.external_overflow,
                    "failure_clock": node.failure_clock,
                    "failures_enabled": node.time_to_failure is not None,
                }
                for name, node in self.model._nodes.items()
            },
            capacities={
                name: station.node.capacity for name, station in self.stations.items()
            },
            duration=self.duration,
            end_time=float(self.env.now),
            drain=self.drain,
            closing_states=closing_states,
            warmup=self.warmup,
            time_unit=self.model.time_unit,
            seed=self.seed,
            graph=self.model._graph,
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
