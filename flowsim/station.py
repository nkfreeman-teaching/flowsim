"""Private server identities, finite admissions, shifts, and repair processes."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from flowsim.model import Node, sample
from flowsim.results import (
    Phase,
    Status,
    _Activity,
    _Customer,
    _Failure,
    _Visit,
)
from flowsim.scheduler import SHIFT_PRIORITY, Event

if TYPE_CHECKING:
    from flowsim.engine import _Run

# A customer held by a server takes its status from the server's phase.
PHASE_STATUS = {
    Phase.PROCESSING: Status.IN_SERVICE,
    Phase.BLOCKED: Status.BLOCKED,
    Phase.PAUSED: Status.PAUSED,
}


@dataclass
class _Ticket:
    customer: _Customer
    admitted: Event
    finished: Event
    external: bool
    visit: _Visit | None = None
    server: _Server | None = None


class _Server:
    def __init__(self, station: _Station, identifier: int, seeds):
        self.station = station
        self.run = station.run
        self.id = identifier
        self.scheduled = identifier <= station.scheduled_level
        self.down = False
        self.ticket: _Ticket | None = None
        self.phase = Phase.IDLE
        self.activity: _Activity | None = None
        self.changed = self.run.scheduler.event()
        self.failure_rng = np.random.default_rng(seeds[0])
        self.repair_rng = np.random.default_rng(seeds[1])
        if station.node.time_to_failure is not None:
            self.run.scheduler.process(self.failures())

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
        self.changed = self.run.scheduler.event()
        prior.succeed()

    def set_phase(self, phase: Phase) -> None:
        if self.phase == phase:
            return
        now = float(self.run.scheduler.now)
        if self.activity is not None:
            self.activity.end = now
        self.phase = phase
        self.activity = None
        if self.ticket is not None and phase != Phase.IDLE:
            self.activity = _Activity(
                customer_id=self.ticket.customer.customer_id,
                station=self.station.node.name,
                server_id=self.id,
                state=phase,
                start=now,
            )
            self.run.activities.append(self.activity)
            self.ticket.customer.status = PHASE_STATUS[phase]
        self.pulse()

    def sync_phase(self) -> None:
        if self.ticket is None:
            self.set_phase(Phase.IDLE)
        elif self.ticket.finished.triggered:
            self.set_phase(Phase.BLOCKED)
        elif self.available:
            self.set_phase(Phase.PROCESSING)
        else:
            self.set_phase(Phase.PAUSED)

    def count_down(self, remaining: float, running: Callable[[], bool]):
        """Spend a duration only while a condition holds, waking on changes."""
        scheduler = self.run.scheduler
        while remaining > 0:
            if not running():
                yield self.changed
                continue
            # The scheduler queues the timeout at now + remaining, so it lands
            # exactly at this deadline.
            deadline = scheduler.now + remaining
            timeout = scheduler.timeout(remaining)
            result = yield scheduler.any_of([timeout, self.changed])
            # A deadline at most one representable time after now is now.
            # Otherwise 0.1 + 0.2 lands just after a shift change at 0.3, and the
            # remainder pauses work that ends at the shift change by hand.
            if timeout in result or deadline <= math.nextafter(scheduler.now, math.inf):
                return
            remaining = deadline - scheduler.now

    def failures(self):
        node = self.station.node
        while True:
            cycle_start = self.run.scheduler.now
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
                    else self.phase == Phase.PROCESSING
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
            row = _Failure(
                station=node.name,
                server_id=self.id,
                failure_time=float(self.run.scheduler.now),
                time_to_failure=lifetime,
                repair_time=repair,
            )
            self.run.failures.append(row)
            yield self.run.scheduler.timeout(repair)
            row.repair_end = float(self.run.scheduler.now)
            self.down = False
            self.sync_phase()
            self.pulse()
            self.station.dispatch()
            self.run.observe(node.name)
            # A cycle that leaves the clock unchanged repeats forever. From time
            # 0, a cycle too small to move the clock at the duration creeps
            # forward in steps that cannot reach it.
            duration = self.run.duration
            if (
                self.run.scheduler.now == cycle_start
                or duration + (lifetime + repair) == duration
            ):
                raise ValueError(
                    f"Time to failure {lifetime!r} and repair time {repair!r} at "
                    f"{node.name!r}, server {self.id}, are too small for the "
                    f"simulation clock to advance in a run of duration {duration!r}."
                )


class _Station:
    def __init__(self, run: _Run, node: Node, seed: np.random.SeedSequence):
        self.run = run
        self.node = node
        self.scheduled_level = (
            node.capacity if node.staffing is None else node.staffing[0][1]
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
            # Shift changes precede completions and arrivals at equal times.
            events = [
                (run.scheduler.timeout(time, priority=SHIFT_PRIORITY), level)
                for time, level in node.staffing[1:]
            ]
            run.scheduler.process(self.shifts(events))

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
            "processing": sum(
                server.phase == Phase.PROCESSING for server in self.servers
            ),
            "blocked": sum(server.phase == Phase.BLOCKED for server in self.servers),
            "paused": sum(server.phase == Phase.PAUSED for server in self.servers),
            "down": sum(server.down for server in self.servers),
            "scheduled": sum(server.scheduled for server in self.servers),
            "available": sum(server.available for server in self.servers),
            "outside": sum(ticket.external for ticket in self.pending),
        }

    def room(self) -> bool:
        if any(server.idle for server in self.servers) and not self.waiting:
            return True
        return self.node.buffer is None or len(self.waiting) < self.node.buffer

    def admit(self, customer: _Customer, *, external: bool) -> _Ticket | None:
        ticket = _Ticket(
            customer=customer,
            admitted=self.run.scheduler.event(),
            finished=self.run.scheduler.event(),
            external=external,
        )
        if not self.pending and self.room():
            self.place(ticket)
            self.dispatch()
        elif external and self.node.external_overflow == "reject":
            customer.status = Status.REJECTED
            customer.station = self.node.name
            return None
        else:
            self.pending.append(ticket)
            if external:
                customer.status = Status.OUTSIDE
                customer.station = self.node.name
            self.check_drain()
        self.run.observe(self.node.name)
        return ticket

    def place(self, ticket: _Ticket) -> None:
        now = float(self.run.scheduler.now)
        customer = ticket.customer
        if ticket.external:
            customer.admitted = True
            customer.admission_time = now
            customer.outside_wait = now - customer.arrival_time
            customer.total_wait += customer.outside_wait
        ticket.visit = _Visit(
            customer_id=customer.customer_id,
            source=customer.source,
            station=self.node.name,
            arrival_time=now,
            service_time=sample(
                distribution=self.node.service_time,
                rng=self.run.streams[self.node.name].durations,
                label=f"Service time at {self.node.name!r}",
            ),
        )
        self.run.visits.append(ticket.visit)
        customer.station = self.node.name
        customer.status = Status.WAITING
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
                visit.server_id = idle.id
                visit.service_start = float(self.run.scheduler.now)
                visit.wait_time = self.run.scheduler.now - visit.arrival_time
                ticket.customer.total_wait += visit.wait_time
                idle.sync_phase()
                self.run.scheduler.process(self.work(ticket))
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
            remaining=ticket.visit.service_time,
            running=lambda: server.phase == Phase.PROCESSING,
        )
        ticket.visit.service_end = float(self.run.scheduler.now)
        ticket.finished.succeed()
        server.sync_phase()
        self.run.observe(self.node.name)

    def release(self, ticket: _Ticket) -> None:
        ticket.visit.departure_time = float(self.run.scheduler.now)
        ticket.visit.blocked_time = self.run.scheduler.now - ticket.visit.service_end
        ticket.customer.total_blocked += ticket.visit.blocked_time
        ticket.server.ticket = None
        ticket.server.sync_phase()
        ticket.server.pulse()
        self.dispatch()

    def check_drain(self) -> None:
        """After closing, test whether a drained run can still finish."""
        if self.run.closed and self.run.drain and not self.drain_check_pending:
            self.drain_check_pending = True
            self.run.scheduler.process(self.settled_drain_check())

    def settled_drain_check(self):
        # Shift changes and completions at this instant can restore staffing
        # or finish paused work, so judge the state after they all run.
        yield self.run.settled()
        self.drain_check_pending = False
        future = (
            self.node.staffing is None
            or self.scheduled_level > 0
            or any(
                time > self.run.scheduler.now and level > 0
                for time, level in self.node.staffing
            )
        )
        paused = self.node.shift_end != "finish" and any(
            server.phase == Phase.PAUSED for server in self.servers
        )
        if not future and (self.waiting or self.pending or paused):
            raise RuntimeError(
                f"Cannot drain station {self.node.name!r}. Unfinished work has no future staffing."
            )
        for server in self.servers:
            if (
                server.phase == Phase.PAUSED
                and not server.scheduled
                and self.node.shift_end == "pause"
                and not any(
                    time > self.run.scheduler.now and level >= server.id
                    for time, level in self.node.staffing
                )
            ):
                raise RuntimeError(
                    f"Cannot drain station {self.node.name!r}. Server {server.id} "
                    "has paused work and no future staffing."
                )
