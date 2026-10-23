"""Student-facing model definitions, independent of notebook software."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

from flowsim.engine import simulate
from flowsim.plots import network_diagram
from flowsim.results import Experiment, Results
from flowsim.schedules import validate_schedule
from flowsim.validation import Duration, integer, number

if TYPE_CHECKING:
    from plotly.graph_objects import Figure


@dataclass(
    frozen=True,
    eq=False,
)
class Node:
    """A source, station, or exit belonging to one model."""

    name: str
    kind: str
    interarrival: Duration | None = None
    service_time: Duration | None = None
    capacity: int = 0
    first_arrival: float | None = None
    limit: int | None = None
    arrival_rates: tuple[tuple[float, float], ...] | None = None
    staffing: tuple[tuple[float, int], ...] | None = None
    shift_end: str | None = None
    buffer: int | None = None
    external_overflow: str | None = None
    time_to_failure: Duration | None = None
    repair_time: Duration | None = None
    failure_clock: str | None = None


class Model:
    """An acyclic network of first-come, first-served service stations."""

    def __init__(self, time_unit: str = "minutes"):
        if not isinstance(time_unit, str) or not time_unit.strip():
            raise ValueError("time_unit must be a nonempty label.")
        self.time_unit = time_unit.strip()
        self._nodes: dict[str, Node] = {}
        self._graph = nx.DiGraph()
        self.exit = self._add(
            Node(
                name="Exit",
                kind="exit",
            )
        )

    @property
    def nodes(self) -> Mapping[str, Node]:
        """Return a read-only view of the nodes by name, in definition order."""
        return MappingProxyType(self._nodes)

    @property
    def graph(self) -> nx.DiGraph:
        """Return a frozen copy of the routes, with each edge's probability."""
        return nx.freeze(self._graph.copy())

    def _add(self, node: Node) -> Node:
        if not isinstance(node.name, str) or not node.name.strip():
            raise ValueError("Each node needs a nonempty name.")
        if node.name in self._nodes:
            raise ValueError(f"The name {node.name!r} already exists in this model.")
        self._nodes[node.name] = node
        self._graph.add_node(node.name)
        return node

    def _owned(self, node: Node) -> None:
        if not isinstance(node, Node) or self._nodes.get(node.name) is not node:
            raise ValueError("Routes must use nodes created by this model.")

    def source(
        self,
        name: str,
        interarrival: Duration | None = None,
        *,
        first_arrival: Real | None = None,
        limit: int | None = None,
        rates: Sequence[tuple[float, float]] | None = None,
    ) -> Node:
        """Create arrivals, with the first arrival sampled unless specified."""
        if (interarrival is None) == (rates is None):
            raise ValueError("Provide either interarrival or rates, but not both.")
        arrival_rates = None
        if rates is not None:
            arrival_rates = validate_schedule(
                points=rates,
                label="Arrival rate schedule",
            )
        elif not callable(interarrival):
            number(
                value=interarrival,
                label="Interarrival time",
                positive=True,
            )
        first = (
            None
            if first_arrival is None
            else number(first_arrival, "First arrival time")
        )
        count = (
            None
            if limit is None
            else integer(
                value=limit,
                label="Arrival limit",
                minimum=0,
            )
        )
        return self._add(
            Node(
                name=name,
                kind="source",
                interarrival=interarrival,
                first_arrival=first,
                limit=count,
                arrival_rates=arrival_rates,
            )
        )

    def station(
        self,
        name: str,
        capacity: int,
        service_time: Duration,
        *,
        staffing: Sequence[tuple[float, float]] | None = None,
        shift_end: str | None = None,
        buffer: int | None = None,
        external_overflow: str | None = None,
        time_to_failure: Duration | None = None,
        repair_time: Duration | None = None,
        failure_clock: str | None = None,
    ) -> Node:
        """Create servers, with optional schedules, waiting limits, and failures."""
        count = integer(capacity, "Station capacity")
        if not callable(service_time):
            number(service_time, "Service time")
        staff = None
        if staffing is not None:
            if shift_end not in {"finish", "pause"}:
                raise ValueError(
                    "Scheduled staffing requires shift_end='finish' or 'pause'."
                )
            staff = validate_schedule(
                points=staffing,
                label="Staffing schedule",
                counts=True,
                maximum=count,
            )
        elif shift_end is not None:
            raise ValueError("shift_end requires a staffing schedule.")
        waiting_limit = None
        if buffer is not None:
            waiting_limit = integer(
                value=buffer,
                label="Buffer capacity",
                minimum=0,
            )
            if external_overflow not in {"reject", "wait"}:
                raise ValueError(
                    "A finite buffer requires external_overflow='reject' or 'wait'."
                )
        elif external_overflow is not None:
            raise ValueError("external_overflow requires a finite buffer.")
        if (time_to_failure is None) != (repair_time is None):
            raise ValueError("Provide both time_to_failure and repair_time.")
        if time_to_failure is not None:
            if failure_clock not in {"available", "busy"}:
                raise ValueError(
                    "Failures require failure_clock='available' or 'busy'."
                )
            if not callable(time_to_failure):
                number(
                    value=time_to_failure,
                    label="Time to failure",
                    positive=True,
                )
            if not callable(repair_time):
                number(repair_time, "Repair time")
        elif failure_clock is not None:
            raise ValueError("failure_clock requires time_to_failure and repair_time.")
        return self._add(
            Node(
                name=name,
                kind="station",
                service_time=service_time,
                capacity=count,
                staffing=staff,
                shift_end=shift_end,
                buffer=waiting_limit,
                external_overflow=external_overflow,
                time_to_failure=time_to_failure,
                repair_time=repair_time,
                failure_clock=failure_clock,
            )
        )

    def route(self, nodes: Sequence[Node]) -> None:
        """Connect a sequence, without replacing an existing route."""
        if len(nodes) < 2:
            raise ValueError("A route needs at least two nodes.")
        for node in nodes:
            self._owned(node)
        edges = list(zip(nodes[:-1], nodes[1:]))
        for origin, destination in edges:
            self._check_edge(origin, destination)
            current = list(self._graph.successors(origin.name))
            if current and (
                current != [destination.name]
                or self._graph[origin.name][destination.name]["probability"] != 1
            ):
                raise ValueError(f"{origin.name!r} already has a different route.")
        # Validate the complete edit before modifying the model.
        proposal = self._graph.copy()
        proposal.add_edges_from([(a.name, b.name) for a, b in edges])
        if not nx.is_directed_acyclic_graph(proposal):
            raise ValueError("FlowSim supports acyclic routes only.")
        for origin, destination in edges:
            self._graph.add_edge(
                u_of_edge=origin.name,
                v_of_edge=destination.name,
                probability=1.0,
            )

    def _check_edge(self, origin: Node, destination: Node) -> None:
        if origin.kind == "exit":
            raise ValueError("The exit cannot have an outgoing route.")
        if destination.kind == "source":
            raise ValueError("A source cannot receive routed customers.")

    def branch(self, origin: Node, destinations: Mapping[Node, float]) -> None:
        """Choose one destination per customer using fixed probabilities."""
        self._owned(origin)
        if not destinations:
            raise ValueError("A branch needs at least one destination.")
        if self._graph.out_degree(origin.name):
            raise ValueError(f"{origin.name!r} already has an outgoing route.")
        probabilities = []
        for destination, probability in destinations.items():
            self._owned(destination)
            self._check_edge(origin, destination)
            probabilities.append(
                number(
                    value=probability,
                    label="Probability",
                    positive=True,
                )
            )
        if not math.isclose(
            a=sum(probabilities),
            b=1.0,
            rel_tol=0,
            abs_tol=1e-12,
        ):
            raise ValueError("Branch probabilities must sum to one.")
        proposal = self._graph.copy()
        proposal.add_edges_from([(origin.name, node.name) for node in destinations])
        if not nx.is_directed_acyclic_graph(proposal):
            raise ValueError("FlowSim supports acyclic routes only.")
        for destination, probability in zip(destinations, probabilities):
            self._graph.add_edge(
                u_of_edge=origin.name,
                v_of_edge=destination.name,
                probability=probability,
            )

    def validate(self) -> None:
        """Reject disconnected stations and routes that cannot reach the exit."""
        sources = [node for node in self._nodes.values() if node.kind == "source"]
        if not sources:
            raise ValueError("The model needs at least one arrival source.")
        reachable = set()
        for source in sources:
            reachable.add(source.name)
            reachable.update(nx.descendants(self._graph, source.name))
        for node in self._nodes.values():
            if node.name not in reachable:
                raise ValueError(f"{node.name!r} is unreachable from every source.")
            if node is not self.exit and not nx.has_path(
                G=self._graph,
                source=node.name,
                target=self.exit.name,
            ):
                raise ValueError(f"{node.name!r} needs a route to the exit.")

    def diagram(self) -> Figure:
        self.validate()
        return network_diagram(self)

    def run(
        self,
        duration: Real,
        seed: int = 42,
        *,
        warmup: Real = 0,
        drain: bool = False,
    ) -> Results:
        """Close arrivals at duration, optionally serving everyone to completion."""
        self.validate()
        horizon = number(
            value=duration,
            label="Run duration",
            positive=True,
        )
        start = number(warmup, "Warm-up duration")
        if start >= horizon:
            raise ValueError("Warm-up duration must be shorter than run duration.")
        if not isinstance(drain, bool):
            raise ValueError("drain must be True or False.")
        return simulate(
            model=self,
            duration=horizon,
            warmup=start,
            drain=drain,
            seed=integer(
                value=seed,
                label="Seed",
                minimum=0,
            ),
        )

    def experiment(
        self,
        duration: Real,
        replications: int = 20,
        seed: int = 42,
        *,
        warmup: Real = 0,
        drain: bool = False,
    ) -> Experiment:
        """Run independent replications and retain each run's raw results."""
        count = integer(
            value=replications,
            label="Replications",
            minimum=2,
        )
        seeds = np.random.SeedSequence(
            integer(
                value=seed,
                label="Seed",
                minimum=0,
            )
        ).spawn(count)
        runs = [
            self.run(
                duration=duration,
                seed=int(child.generate_state(1)[0]),
                warmup=warmup,
                drain=drain,
            )
            for child in seeds
        ]
        return Experiment(runs)
