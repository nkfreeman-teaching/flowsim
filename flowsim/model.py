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
from flowsim.policies import OrderUpTo
from flowsim.results import SUPPLIER, Experiment, Results
from flowsim.schedules import validate_schedule
from flowsim.validation import Duration, integer, number

if TYPE_CHECKING:
    from plotly.graph_objects import Figure


@dataclass(
    frozen=True,
    eq=False,
)
class Node:
    """A source, station, exit, demand, or stock point belonging to one model."""

    name: str
    kind: str
    interarrival: Duration | None = None
    # A station's one duration, or a read-only mapping from customer type to
    # duration.
    service_time: Duration | Mapping[str, Duration] | None = None
    # A station's read-only mapping from customer type to rank, where a lower
    # rank is served first, or None for first-come, first-served.
    priority: Mapping[str, float] | None = None
    # A station's patience, as one duration or a read-only mapping from customer
    # type to duration, and the queues a customer may leave when it runs out.
    patience: Duration | Mapping[str, Duration] | None = None
    abandon_from: str | None = None
    capacity: int = 0
    first_arrival: float | None = None
    limit: int | None = None
    # A source's read-only mapping from customer type to probability, or None
    # for customers without a type.
    types: Mapping[str, float] | None = None
    arrival_rates: tuple[tuple[float, float], ...] | None = None
    staffing: tuple[tuple[float, int], ...] | None = None
    shift_end: str | None = None
    buffer: int | None = None
    external_overflow: str | None = None
    time_to_failure: Duration | None = None
    repair_time: Duration | None = None
    failure_clock: str | None = None
    per_period: Duration | None = None
    initial: float | None = None
    lead_time: Duration | None = None
    shortage: str | None = None
    policy: OrderUpTo | None = None
    forecast_from: str | None = None


# Node kinds that customers visit along routes. Demand and stock points belong
# to a supply chain instead, which has no routes.
NETWORK_KINDS = {"source", "station", "exit"}

# One routing rule's destinations and probabilities, in the order given.
Choices = tuple[tuple[str, float], ...]


def _type_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Customer types must be nonempty names, not {value!r}.")
    return value


def _type_mix(types: object) -> Mapping[str, float]:
    if not isinstance(types, Mapping) or not types:
        raise ValueError("types must map each customer type to its probability.")
    probabilities = {
        _type_name(kind): number(
            value=probability,
            label=f"Probability of type {kind!r}",
            positive=True,
        )
        for kind, probability in types.items()
    }
    if not math.isclose(
        a=sum(probabilities.values()),
        b=1.0,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ValueError("Type probabilities must sum to one.")
    return MappingProxyType(probabilities)


def _typed_durations(times: Mapping, label: str) -> Mapping[str, Duration]:
    """Check a mapping from customer type to duration, labeled like "Service time"."""
    if not times:
        raise ValueError(f"A {label.lower()} mapping needs at least one customer type.")
    durations = {}
    for kind, duration in times.items():
        name = _type_name(kind)
        if not callable(duration):
            number(duration, f"{label} for type {name!r}")
        durations[name] = duration
    return MappingProxyType(durations)


def _ranks(priority: object) -> Mapping[str, float]:
    if not isinstance(priority, Mapping) or not priority:
        raise ValueError("priority must map each customer type to its rank.")
    return MappingProxyType(
        {
            _type_name(kind): number(rank, f"Rank of type {kind!r}")
            for kind, rank in priority.items()
        }
    )


def _route_types(types: object) -> tuple[str | None, ...]:
    """Return the rule keys for a route or branch, where None means every type."""
    if types is None:
        return (None,)
    if isinstance(types, str) or not isinstance(types, Sequence) or not types:
        raise ValueError("types must be a nonempty list of customer types.")
    names = tuple(_type_name(kind) for kind in types)
    if len(set(names)) != len(names):
        raise ValueError("A route cannot list a customer type twice.")
    return names


def _rule(table: Mapping[str | None, Choices], kind: str | None) -> Choices | None:
    """Return the rule a customer of this type follows from one node."""
    return table[None] if None in table else table.get(kind)


@dataclass(
    frozen=True,
    eq=False,
)
class SupplyChain:
    """Consumer demand and the stock points that order up the chain from it."""

    demand: Node
    stock_points: tuple[Node, ...]
    period: float


class Model:
    """A network of service stations, first-come, first-served unless ranked.

    Each customer type's routes are acyclic. Routes across types may form a
    cycle only through stations with unlimited buffers.
    """

    def __init__(self, time_unit: str = "minutes"):
        if not isinstance(time_unit, str) or not time_unit.strip():
            raise ValueError("time_unit must be a nonempty label.")
        self.time_unit = time_unit.strip()
        self._nodes: dict[str, Node] = {}
        self._graph = nx.DiGraph()
        # Each origin's routing rules by customer type, where the key None holds
        # one rule for every type.
        self._routing: dict[str, dict[str | None, Choices]] = {}
        self._supply: SupplyChain | None = None
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
        """Return a frozen copy of the routes across every customer type.

        An edge from an untyped route or branch holds its probability. An edge
        from a typed one instead holds types, a mapping from each customer type
        that may take the edge to its probability.
        """
        return nx.freeze(self._graph.copy())

    @property
    def routing(self) -> Mapping[str, Mapping[str | None, Choices]]:
        """Return each node's destinations and probabilities by customer type.

        The key None holds a node's one route for every type.
        """
        return MappingProxyType(
            {
                origin: MappingProxyType(dict(table))
                for origin, table in self._routing.items()
            }
        )

    @property
    def supply_chain(self) -> SupplyChain | None:
        """Return the supply chain, or None for a service network."""
        return self._supply

    def _add(self, node: Node) -> Node:
        if not isinstance(node.name, str) or not node.name.strip():
            raise ValueError("Each node needs a nonempty name.")
        if node.name in self._nodes:
            raise ValueError(f"The name {node.name!r} already exists in this model.")
        if node.kind in {"source", "station"} and self._supply is not None:
            raise ValueError(_ONE_KIND)
        self._nodes[node.name] = node
        if node.kind in NETWORK_KINDS:
            self._graph.add_node(node.name)
        return node

    def _has_network(self) -> bool:
        return any(node.kind in {"source", "station"} for node in self._nodes.values())

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
        types: Mapping[str, Real] | None = None,
    ) -> Node:
        """Create arrivals, with the first arrival sampled unless specified.

        types maps each customer type to the probability that an arrival has it.
        Without types, customers have no type.
        """
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
                types=None if types is None else _type_mix(types),
                arrival_rates=arrival_rates,
            )
        )

    def station(
        self,
        name: str,
        capacity: int,
        service_time: Duration | Mapping[str, Duration],
        *,
        staffing: Sequence[tuple[float, float]] | None = None,
        shift_end: str | None = None,
        buffer: int | None = None,
        external_overflow: str | None = None,
        time_to_failure: Duration | None = None,
        repair_time: Duration | None = None,
        failure_clock: str | None = None,
        priority: Mapping[str, Real] | None = None,
        patience: Duration | Mapping[str, Duration] | None = None,
        abandon_from: str | None = None,
    ) -> Node:
        """Create servers, with optional schedules, waiting limits, and failures.

        service_time is one duration, or a mapping from customer type to the
        duration for that type. priority maps each customer type to a rank. A
        lower rank leaves the waiting line first, and equal ranks keep the order
        customers joined it. Service is never interrupted.

        patience is one duration, or a mapping from customer type to duration,
        after which a customer who has not started service leaves the network.
        abandon_from='waiting' starts the clock when the customer enters the
        waiting line. 'waiting_and_outside' also starts it when an outside
        arrival joins the queue outside a full buffer, and the clock keeps
        running after admission.
        """
        count = integer(capacity, "Station capacity")
        if isinstance(service_time, Mapping):
            service_time = _typed_durations(service_time, "Service time")
        elif not callable(service_time):
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
        if patience is not None:
            if abandon_from not in {"waiting", "waiting_and_outside"}:
                raise ValueError(
                    "Patience requires abandon_from='waiting' or 'waiting_and_outside'."
                )
            if abandon_from == "waiting_and_outside" and external_overflow != "wait":
                raise ValueError(
                    "abandon_from='waiting_and_outside' requires a finite buffer "
                    "with external_overflow='wait'."
                )
            if isinstance(patience, Mapping):
                patience = _typed_durations(patience, "Patience")
            elif not callable(patience):
                number(patience, "Patience")
        elif abandon_from is not None:
            raise ValueError("abandon_from requires patience.")
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
                priority=None if priority is None else _ranks(priority),
                patience=patience,
                abandon_from=abandon_from,
            )
        )

    def demand(self, name: str, per_period: Duration) -> Node:
        """Create consumer demand, a quantity drawn once per review period."""
        if not callable(per_period):
            number(per_period, "Demand per period")
        return self._add(
            Node(
                name=name,
                kind="demand",
                per_period=per_period,
            )
        )

    def stock_point(
        self,
        name: str,
        *,
        initial: Real,
        lead_time: Duration,
        shortage: str,
        policy: OrderUpTo,
        forecast_from: str,
    ) -> Node:
        """Create a stock point that fills orders from stock and reorders each period.

        lead_time is the delay from its supplier's shipment to its own receipt.
        Every argument is a behavioral choice, so none has a default.
        """
        stock = number(initial, "Initial stock")
        if not isinstance(policy, OrderUpTo):
            raise ValueError("policy must come from flowsim.order_up_to.")
        if callable(lead_time):
            if policy.cover is None:
                raise ValueError(
                    "A sampled lead time needs an explicit cover in order_up_to, "
                    "since FlowSim does not estimate the lead time's mean."
                )
        else:
            number(
                value=lead_time,
                label="Lead time",
                positive=True,
            )
            if policy.cover is not None:
                raise ValueError(
                    "With a constant lead time, cover is lead_time / period. Give "
                    "cover only for a sampled lead time."
                )
        if shortage not in {"backorder", "lost"}:
            raise ValueError("shortage must be 'backorder' or 'lost'.")
        if forecast_from not in {"orders", "end_demand"}:
            raise ValueError("forecast_from must be 'orders' or 'end_demand'.")
        return self._add(
            Node(
                name=name,
                kind="stock_point",
                initial=stock,
                lead_time=lead_time,
                shortage=shortage,
                policy=policy,
                forecast_from=forecast_from,
            )
        )

    def supply(self, chain: Sequence[Node], *, period: Real) -> None:
        """Link demand to stock points, each ordering from the next in the list.

        The last stock point orders from a supplier with unlimited stock that
        ships in the same period. Every stage reviews once per period.
        """
        if self._supply is not None:
            raise ValueError("This model already has a supply chain.")
        if self._has_network():
            raise ValueError(_ONE_KIND)
        if len(chain) < 2:
            raise ValueError(
                "A supply chain needs demand and at least one stock point."
            )
        for node in chain:
            self._owned(node)
        if any(node.name == SUPPLIER for node in chain):
            raise ValueError(
                f"The name {SUPPLIER!r} is reserved for the unlimited top supplier."
            )
        if len({node.name for node in chain}) != len(chain):
            raise ValueError("A supply chain cannot list a node twice.")
        demand, *stock_points = chain
        if demand.kind != "demand":
            raise ValueError("A supply chain starts with demand from model.demand.")
        if any(node.kind != "stock_point" for node in stock_points):
            raise ValueError("After demand, a supply chain lists only stock points.")
        length = number(
            value=period,
            label="Review period",
            positive=True,
        )
        for node in stock_points:
            if callable(node.lead_time):
                continue
            periods = round(node.lead_time / length)
            if periods < 1 or not math.isclose(
                a=periods * length,
                b=node.lead_time,
                rel_tol=1e-9,
                abs_tol=0,
            ):
                raise ValueError(
                    f"The constant lead time at {node.name!r} must be a whole number "
                    "of review periods, since receipts happen at reviews."
                )
        self._supply = SupplyChain(
            demand=demand,
            stock_points=tuple(stock_points),
            period=length,
        )

    def route(
        self,
        nodes: Sequence[Node],
        *,
        types: Sequence[str] | None = None,
    ) -> None:
        """Connect a sequence, without replacing an existing route.

        With types, only customers of those types follow it.
        """
        if len(nodes) < 2:
            raise ValueError("A route needs at least two nodes.")
        for node in nodes:
            self._owned(node)
        keys = _route_types(types)
        edges = list(zip(nodes[:-1], nodes[1:]))
        for origin, destination in edges:
            self._check_edge(origin, destination)
        if len({node.name for node in nodes}) != len(nodes):
            self._cycle_error(keys[0])
        rules = []
        for origin, destination in edges:
            choices = ((destination.name, 1.0),)
            for key in keys:
                # Repeating a node's existing route is allowed.
                if self._routing.get(origin.name, {}).get(key) == choices:
                    continue
                self._check_free(
                    origin=origin,
                    key=key,
                    message=(
                        f"{origin.name!r} already has a different route"
                        + ("." if key is None else f" for type {key!r}.")
                    ),
                )
                rules.append((origin.name, key, choices))
        self._commit(rules)

    def _check_edge(self, origin: Node, destination: Node) -> None:
        if origin.kind == "exit":
            raise ValueError("The exit cannot have an outgoing route.")
        if destination.kind == "source":
            raise ValueError("A source cannot receive routed customers.")

    def branch(
        self,
        origin: Node,
        destinations: Mapping[Node, float],
        *,
        types: Sequence[str] | None = None,
    ) -> None:
        """Choose one destination per customer using fixed probabilities.

        With types, only customers of those types follow it.
        """
        self._owned(origin)
        if not destinations:
            raise ValueError("A branch needs at least one destination.")
        keys = _route_types(types)
        for key in keys:
            self._check_free(
                origin=origin,
                key=key,
                message=(
                    f"{origin.name!r} already has an outgoing route"
                    + ("." if key is None else f" for type {key!r}.")
                ),
            )
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
        choices = tuple(
            (destination.name, probability)
            for destination, probability in zip(destinations, probabilities)
        )
        self._commit([(origin.name, key, choices) for key in keys])

    def _check_free(self, origin: Node, key: str | None, message: str) -> None:
        """Reject a rule that would overlap one of the origin's existing rules."""
        current = self._routing.get(origin.name, {})
        if (key is None and current) or key in current:
            raise ValueError(message)
        if key is not None and None in current:
            raise ValueError(
                f"{origin.name!r} already has a route for every customer type."
            )

    def _cycle_error(self, key: str | None) -> None:
        if key is None:
            raise ValueError("FlowSim supports acyclic routes only.")
        raise ValueError(
            f"The routes for type {key!r} form a cycle. Each customer type's "
            "routes must be acyclic."
        )

    def _commit(self, rules: list[tuple[str, str | None, Choices]]) -> None:
        """Validate new routing rules as one edit, then add them to the model."""
        routing = {origin: dict(table) for origin, table in self._routing.items()}
        graph = self._graph.copy()
        for origin, key, choices in rules:
            routing.setdefault(origin, {})[key] = choices
            for destination, probability in choices:
                if key is None:
                    graph.add_edge(
                        u_of_edge=origin,
                        v_of_edge=destination,
                        probability=probability,
                    )
                    continue
                if graph.has_edge(origin, destination):
                    types = dict(graph[origin][destination]["types"])
                else:
                    types = {}
                types[key] = probability
                graph.add_edge(
                    u_of_edge=origin,
                    v_of_edge=destination,
                    types=MappingProxyType(types),
                )
        # Check the untyped routes, then each type's routes in first-use order.
        keys = dict.fromkeys(
            [None, *(key for table in routing.values() for key in table)]
        )
        for key in keys:
            followed = nx.DiGraph()
            for origin, table in routing.items():
                rule = table.get(None) if key is None else _rule(table, key)
                for destination, _ in rule or ():
                    followed.add_edge(origin, destination)
            if not nx.is_directed_acyclic_graph(followed):
                self._cycle_error(key)
        # A cycle of finite buffers can deadlock, with each blocked server
        # waiting for room at the next station on the cycle.
        cyclic = {
            name
            for component in nx.strongly_connected_components(graph)
            if len(component) > 1
            for name in component
        }
        for node in self._nodes.values():
            if node.name in cyclic and node.buffer is not None:
                raise ValueError(
                    f"{node.name!r} has a finite buffer and lies on a cycle of "
                    "routes across customer types. Blocked servers on such a "
                    "cycle can wait on each other forever, so its stations need "
                    "unlimited buffers."
                )
        self._routing = routing
        self._graph = graph

    def validate(self) -> None:
        """Reject disconnected stations and routes that cannot reach the exit."""
        chain = () if self._supply is None else self._supply.stock_points
        for node in self._nodes.values():
            unlinked_stock = node.kind == "stock_point" and node not in chain
            unlinked_demand = node.kind == "demand" and (
                self._supply is None or node is not self._supply.demand
            )
            if unlinked_stock or unlinked_demand:
                raise ValueError(f"{node.name!r} is not in a supply chain.")
        if self._supply is not None:
            return
        sources = [node for node in self._nodes.values() if node.kind == "source"]
        if not sources:
            raise ValueError(
                "The model needs at least one arrival source or a supply chain."
            )
        reachable = set()
        for source in sources:
            reachable.add(source.name)
            reachable.update(nx.descendants(self._graph, source.name))
        for node in self._nodes.values():
            if node.kind not in NETWORK_KINDS:
                continue
            if node.name not in reachable:
                raise ValueError(f"{node.name!r} is unreachable from every source.")
            if node is not self.exit and not nx.has_path(
                G=self._graph,
                source=node.name,
                target=self.exit.name,
            ):
                raise ValueError(f"{node.name!r} needs a route to the exit.")
        for source in sources:
            self._check_types(source)

    def _check_types(self, source: Node) -> None:
        """Follow each of a source's types and check durations, ranks, and routes.

        Routes may be added after stations, so these checks wait for a run.
        """
        for kind in (None,) if source.types is None else source.types:
            reached = set()
            stack = [source.name]
            while stack:
                name = stack.pop()
                if name in reached or name == self.exit.name:
                    continue
                reached.add(name)
                node = self._nodes[name]
                typed = isinstance(node.service_time, Mapping)
                if typed and kind is None:
                    raise ValueError(
                        f"{name!r} sets service times by customer type, and "
                        f"customers from {source.name!r} have no type."
                    )
                if typed and kind not in node.service_time:
                    raise ValueError(
                        f"{name!r} has no service time for type {kind!r}, which "
                        f"can reach it from {source.name!r}."
                    )
                if isinstance(node.patience, Mapping) and kind is None:
                    raise ValueError(
                        f"{name!r} sets patience by customer type, and customers "
                        f"from {source.name!r} have no type."
                    )
                if isinstance(node.patience, Mapping) and kind not in node.patience:
                    raise ValueError(
                        f"{name!r} has no patience for type {kind!r}, which can "
                        f"reach it from {source.name!r}."
                    )
                if node.priority is not None and kind is None:
                    raise ValueError(
                        f"{name!r} ranks customers by type, and customers from "
                        f"{source.name!r} have no type."
                    )
                if node.priority is not None and kind not in node.priority:
                    raise ValueError(
                        f"{name!r} has no rank for type {kind!r}, which can "
                        f"reach it from {source.name!r}."
                    )
                rule = _rule(self._routing[name], kind)
                if rule is None and kind is None:
                    raise ValueError(
                        f"{name!r} routes by customer type, and customers from "
                        f"{source.name!r} have no type."
                    )
                if rule is None:
                    raise ValueError(
                        f"{name!r} has no route for type {kind!r}, which can "
                        f"reach it from {source.name!r}."
                    )
                stack.extend(destination for destination, _ in rule)

    def diagram(self) -> Figure:
        self.validate()
        if self._supply is not None:
            raise ValueError(
                "diagram draws service routes, and a supply chain has none."
            )
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
        if drain and self._supply is not None:
            raise ValueError(
                "drain serves customers after closing, and a supply chain has none."
            )
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


_ONE_KIND = (
    "A model holds either a service network or a supply chain, not both, until "
    "stock points can release work to stations."
)
