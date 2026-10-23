"""Private server identities, finite admissions, shifts, and repair processes."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from flowsim.model import Node, sample
from flowsim.scheduler import Event

if TYPE_CHECKING:
    from flowsim.engine import _Run


@dataclass
class _Ticket:
    customer: dict
    admitted: Event
    finished: Event
    external: bool
    visit: dict | None = None
    server: _Server | None = None


class _Server:
    def __init__(self, station: _Station, identifier: int, seeds):
        self.station = station
        self.run = station.run
        self.id = identifier
        self.scheduled = identifier <= station.scheduled_level
        self.down = False
        self.ticket: _Ticket | None = None
        self.phase = "idle"
        self.activity: dict | None = None
        self.changed = self.run.env.event()
        self.failure_rng = np.random.default_rng(seeds[0])
        self.repair_rng = np.random.default_rng(seeds[1])
        if station.node.time_to_failure is not None:
            self.run.env.process(self.failures())

    @property
    def available(self) -> bool:
        return not self.down and (
            self.scheduled
            or (self.ticket is not None and self.station.node.shift_end == "finish")
        )

    @property
    def idle(self) -> bool:
        return self.scheduled and not self.down and self.ticket is None

    def pulse(self) -> None:
        prior = self.changed
        self.changed = self.run.env.event()
        prior.succeed()

    def set_phase(self, phase: str) -> None:
        if self.phase == phase:
            return
        now = float(self.run.env.now)
        if self.activity is not None:
            self.activity["end"] = now
        self.phase = phase
        self.activity = None
        if self.ticket is not None and phase != "idle":
            self.activity = {
                "customer_id": self.ticket.customer["customer_id"],
                "station": self.station.node.name,
                "server_id": self.id,
                "state": phase,
                "start": now,
                "end": None,
            }
            self.run.activities.append(self.activity)
            self.ticket.customer["status"] = (
                "in_service" if phase == "processing" else phase
            )
        self.pulse()

    def sync_phase(self) -> None:
        if self.ticket is None:
            self.set_phase("idle")
        elif self.ticket.finished.triggered:
            self.set_phase("blocked")
        elif self.available:
            self.set_phase("processing")
        else:
            self.set_phase("paused")

    def count_down(self, remaining: float, running: Callable[[], bool]):
        """Spend a duration only while a condition holds, waking on changes."""
        env = self.run.env
        while remaining > 0:
            if not running():
                yield self.changed
                continue
            started = env.now
            timeout = env.timeout(remaining)
            result = yield env.any_of([timeout, self.changed])
            remaining = (
                0.0 if timeout in result else max(0.0, remaining - (env.now - started))
            )

    def failures(self):
        node = self.station.node
        while True:
            lifetime = sample(
                distribution=node.time_to_failure,
                rng=self.failure_rng,
                label=f"Time to failure at {node.name!r}, server {self.id}",
                positive=True,
            )
            yield from self.count_down(
                remaining=lifetime,
                running=lambda: (
                    self.available
                    if node.failure_clock == "available"
                    else self.phase == "processing"
                ),
            )
            self.down = True
            self.sync_phase()
            self.pulse()
            self.run.observe(node.name)
            repair = sample(
                distribution=node.repair_time,
                rng=self.repair_rng,
                label=f"Repair time at {node.name!r}, server {self.id}",
            )
            row = {
                "station": node.name,
                "server_id": self.id,
                "failure_time": float(self.run.env.now),
                "time_to_failure": lifetime,
                "repair_time": repair,
                "repair_end": None,
            }
            self.run.failures.append(row)
            yield self.run.env.timeout(repair)
            row["repair_end"] = float(self.run.env.now)
            self.down = False
            self.sync_phase()
            self.pulse()
            self.station.dispatch()
            self.run.observe(node.name)


class _Station:
    def __init__(self, run: _Run, node: Node, seed: np.random.SeedSequence):
        self.run = run
        self.node = node
        self.scheduled_level = (
            node.capacity if node.staffing is None else int(node.staffing[0][1])
        )
        self.waiting: deque[_Ticket] = deque()
        self.drain_check_pending = False
        self.pending: deque[_Ticket] = deque()
        seeds = seed.spawn(2 * node.capacity)
        self.servers = [
            _Server(
                station=self,
                identifier=index + 1,
                seeds=seeds[2 * index : 2 * index + 2],
            )
            for index in range(node.capacity)
        ]
        if node.staffing is not None:
            # Queue every shift boundary before customer timeouts, giving shift
            # changes precedence over arrivals and completions at equal times.
            events = [
                (run.env.timeout(time), int(level)) for time, level in node.staffing[1:]
            ]
            run.env.process(self.shifts(events))

    def shifts(self, events):
        for event, level in events:
            yield event
            self.scheduled_level = level
            for server in self.servers:
                server.scheduled = server.id <= level
                server.sync_phase()
                server.pulse()
            self.dispatch()
            self.run.observe(self.node.name)

    def state(self) -> dict:
        return {
            "waiting": len(self.waiting),
            "busy": sum(server.ticket is not None for server in self.servers),
            "processing": sum(server.phase == "processing" for server in self.servers),
            "blocked": sum(server.phase == "blocked" for server in self.servers),
            "paused": sum(server.phase == "paused" for server in self.servers),
            "down": sum(server.down for server in self.servers),
            "scheduled": sum(server.scheduled for server in self.servers),
            "available": sum(server.available for server in self.servers),
            "outside": sum(ticket.external for ticket in self.pending),
        }

    def room(self) -> bool:
        if any(server.idle for server in self.servers) and not self.waiting:
            return True
        return self.node.buffer is None or len(self.waiting) < self.node.buffer

    def admit(self, customer: dict, *, external: bool) -> _Ticket | None:
        ticket = _Ticket(
            customer=customer,
            admitted=self.run.env.event(),
            finished=self.run.env.event(),
            external=external,
        )
        if not self.pending and self.room():
            self.place(ticket)
            self.dispatch()
        elif external and self.node.external_overflow == "reject":
            customer["status"] = "rejected"
            customer["station"] = self.node.name
            return None
        else:
            self.pending.append(ticket)
            if external:
                customer["status"] = "outside"
                customer["station"] = self.node.name
            self.check_drain()
        self.run.observe(self.node.name)
        return ticket

    def place(self, ticket: _Ticket) -> None:
        now = float(self.run.env.now)
        customer = ticket.customer
        if ticket.external:
            customer["admitted"] = True
            customer["admission_time"] = now
            customer["outside_wait"] = now - customer["arrival_time"]
            customer["total_wait"] += customer["outside_wait"]
        ticket.visit = {
            "customer_id": customer["customer_id"],
            "source": customer["source"],
            "station": self.node.name,
            "arrival_time": now,
            "service_start": None,
            "service_end": None,
            "departure_time": None,
            "wait_time": None,
            "blocked_time": None,
            "server_id": None,
            "service_time": sample(
                distribution=self.node.duration,
                rng=self.run.streams[self.node.name][0],
                label=f"Service time at {self.node.name!r}",
            ),
        }
        self.run.visits.append(ticket.visit)
        customer["station"] = self.node.name
        customer["status"] = "waiting"
        self.waiting.append(ticket)
        ticket.admitted.succeed()

    def dispatch(self) -> None:
        while True:
            idle = next((server for server in self.servers if server.idle), None)
            if idle is not None and self.waiting:
                ticket = self.waiting.popleft()
                ticket.server = idle
                idle.ticket = ticket
                visit = ticket.visit
                visit["server_id"] = idle.id
                visit["service_start"] = float(self.run.env.now)
                visit["wait_time"] = self.run.env.now - visit["arrival_time"]
                ticket.customer["total_wait"] += visit["wait_time"]
                idle.sync_phase()
                self.run.env.process(self.work(ticket))
                continue
            if self.pending and self.room():
                self.place(self.pending.popleft())
                continue
            break
        self.check_drain()
        self.run.observe(self.node.name)

    def work(self, ticket: _Ticket):
        server = ticket.server
        yield from server.count_down(
            remaining=ticket.visit["service_time"],
            running=lambda: server.phase == "processing",
        )
        ticket.visit["service_end"] = float(self.run.env.now)
        ticket.finished.succeed()
        server.sync_phase()
        self.run.observe(self.node.name)

    def release(self, ticket: _Ticket) -> None:
        ticket.visit["departure_time"] = float(self.run.env.now)
        ticket.visit["blocked_time"] = self.run.env.now - ticket.visit["service_end"]
        ticket.customer["total_blocked"] += ticket.visit["blocked_time"]
        ticket.server.ticket = None
        ticket.server.sync_phase()
        ticket.server.pulse()
        self.dispatch()

    def check_drain(self) -> None:
        """After closing, test whether a drained run can still finish."""
        if self.run.closed and self.run.drain and not self.drain_check_pending:
            self.drain_check_pending = True
            self.run.env.process(self.settled_drain_check())

    def settled_drain_check(self):
        # Shift changes and completions at this instant can restore staffing
        # or finish paused work, so judge the state after they all run.
        yield self.run.settled()
        self.drain_check_pending = False
        future = (
            self.node.staffing is None
            or self.scheduled_level > 0
            or any(
                time > self.run.env.now and level > 0
                for time, level in self.node.staffing
            )
        )
        paused = self.node.shift_end != "finish" and any(
            server.phase == "paused" for server in self.servers
        )
        if not future and (self.waiting or self.pending or paused):
            raise RuntimeError(
                f"Cannot drain station {self.node.name!r}. Unfinished work has no future staffing."
            )
        for server in self.servers:
            if (
                server.phase == "paused"
                and not server.scheduled
                and self.node.shift_end == "pause"
                and not any(
                    time > self.run.env.now and level >= server.id
                    for time, level in self.node.staffing
                )
            ):
                raise RuntimeError(
                    f"Cannot drain station {self.node.name!r}. Server {server.id} "
                    "has paused work and no future staffing."
                )
