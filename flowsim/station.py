"""Private server identities, finite admissions, shifts, and repair processes."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import TYPE_CHECKING

import numpy as np

from flowsim.records import (
    Phase,
    Status,
    _Activity,
    _Customer,
    _Failure,
    _State,
    _Visit,
)
from flowsim.scheduler import ABANDON_PRIORITY, SHIFT_PRIORITY, Event
from flowsim.validation import sample

if TYPE_CHECKING:
    from flowsim.engine import _Run
    from flowsim.model import Node

# A customer held by a server takes its status from the server's phase.
PHASE_STATUS = {
    Phase.PROCESSING: Status.IN_SERVICE,
    Phase.BLOCKED: Status.BLOCKED,
    Phase.PAUSED: Status.PAUSED,
}


# Tickets compare by identity, so removing one from a line removes that ticket.
@dataclass(eq=False, slots=True)
class _Ticket:
    customer: _Customer
    admitted: Event | None
    finished: Event
    external: bool
    visit: _Visit | None = None
    server: _Server | None = None
    patience_started: bool = False
    abandoned: bool = False


class _Server:
    """One server's schedule, repair state, current customer, and phase.

    A server is scheduled while the staffing level covers its identifier, down
    during a repair, and holds at most one ticket. Its phase is idle without a
    ticket, processing while available, paused while unavailable during
    service, and blocked while its finished customer waits for room downstream.
    Dedicated work_changed and failure_changed events succeed only when their
    respective running predicates actually flip, avoiding spurious wakeups.
    """

    __slots__ = (
        "station",
        "run",
        "id",
        "scheduled",
        "down",
        "ticket",
        "phase",
        "activity",
        "work_changed",
        "failure_changed",
        "finish_on_shift_end",
        "failure_on_available",
        "_bit",
        "_available",
        "_idle",
        "_failure_running",
        "failure_rng",
        "repair_rng",
    )

    def __init__(self, station: _Station, identifier: int, seeds):
        self.station = station
        self.run = station.run
        self.id = identifier
        self.scheduled = identifier <= station.scheduled_level
        self.down = False
        self.ticket: _Ticket | None = None
        self.phase = Phase.IDLE
        self.activity: _Activity | None = None
        self.work_changed = self.run.scheduler.event()
        self.failure_changed = self.run.scheduler.event()
        self.finish_on_shift_end = station.node.shift_end == "finish"
        self.failure_on_available = station.node.failure_clock == "available"
        self._bit = 1 << (identifier - 1)
        self._available = self.scheduled
        self._idle = self.scheduled
        self._failure_running = self._available if self.failure_on_available else False
        if self.scheduled:
            station._scheduled += 1
            station._available += 1
            station._idle_mask |= self._bit
        self.failure_rng = np.random.default_rng(seeds[0])
        self.repair_rng = np.random.default_rng(seeds[1])
        if station.node.time_to_failure is not None:
            self.run.scheduler.process(self.failures())

    @property
    def available(self) -> bool:
        return self._available

    @property
    def idle(self) -> bool:
        return self._idle

    def _pulse_work(self) -> None:
        # An event nobody waits on moves neither the clock nor event order.
        if not self.work_changed.callbacks:
            return
        prior = self.work_changed
        self.work_changed = self.run.scheduler.event()
        prior.succeed()

    def _pulse_failure(self) -> None:
        if not self.failure_changed.callbacks:
            return
        prior = self.failure_changed
        self.failure_changed = self.run.scheduler.event()
        prior.succeed()

    def _sync_flags(self) -> None:
        avail = not self.down and (
            self.scheduled or (self.ticket is not None and self.finish_on_shift_end)
        )
        if avail != self._available:
            self.station._available += 1 if avail else -1
            self._available = avail
        idle = self.scheduled and not self.down and self.ticket is None
        if idle != self._idle:
            self._idle = idle
            self.station._idle_mask ^= self._bit
        failure_running = (
            avail if self.failure_on_available else (self.phase == Phase.PROCESSING)
        )
        if failure_running != self._failure_running:
            self._failure_running = failure_running
            self._pulse_failure()

    def set_phase(self, phase: Phase) -> None:
        old = self.phase
        if old == phase:
            return
        station = self.station
        if old == Phase.PROCESSING:
            station._processing -= 1
        elif old == Phase.BLOCKED:
            station._blocked -= 1
        elif old == Phase.PAUSED:
            station._paused -= 1
        if phase == Phase.PROCESSING:
            station._processing += 1
        elif phase == Phase.BLOCKED:
            station._blocked += 1
        elif phase == Phase.PAUSED:
            station._paused += 1
        self.phase = phase
        if self.run.keep_records:
            now = float(self.run.scheduler.now)
            if self.activity is not None:
                self.activity.end = now
                activities = self.run.activities
                if (
                    self.activity.end == self.activity.start
                    and activities[-1] is self.activity
                ):
                    activities.pop()
            self.activity = None
            if self.ticket is not None and phase != Phase.IDLE:
                self.activity = _Activity(
                    customer_id=self.ticket.customer.customer_id,
                    station=station.node.name,
                    server_id=self.id,
                    state=phase,
                    start=now,
                )
                self.run.activities.append(self.activity)
                self.ticket.customer.status = PHASE_STATUS[phase]
        elif self.ticket is not None and phase != Phase.IDLE:
            self.ticket.customer.status = PHASE_STATUS[phase]
        if (old == Phase.PROCESSING) != (phase == Phase.PROCESSING):
            self._pulse_work()
        self._sync_flags()

    def sync_phase(self) -> None:
        if self.ticket is None:
            self.set_phase(Phase.IDLE)
        elif self.ticket.finished.triggered:
            self.set_phase(Phase.BLOCKED)
        elif self._available:
            self.set_phase(Phase.PROCESSING)
        else:
            self.set_phase(Phase.PAUSED)

    def count_down(
        self,
        remaining: float,
        running: Callable[[], bool],
        *,
        for_failure: bool = False,
    ):
        """Spend a duration only while a condition holds, waking on changes."""
        scheduler = self.run.scheduler
        while remaining > 0:
            changed = self.failure_changed if for_failure else self.work_changed
            if not running():
                yield changed
                continue
            # The scheduler queues the timeout at now + remaining, so it lands
            # exactly at this deadline.
            deadline = scheduler.now + remaining
            timeout = scheduler.timeout(remaining)
            result = yield scheduler.any_of([timeout, changed])
            # A deadline at most one representable time after now is now.
            # Otherwise 0.1 + 0.2 lands just after a shift change at 0.3, and the
            # remainder pauses work that ends at the shift change by hand.
            if timeout in result or deadline <= math.nextafter(scheduler.now, math.inf):
                return
            remaining = deadline - scheduler.now

    def failures(self):
        node = self.station.node
        # __init__ starts this process only for a station with failures, and
        # Model.station requires repair_time alongside time_to_failure.
        time_to_failure = node.time_to_failure
        repair_time = node.repair_time
        assert time_to_failure is not None and repair_time is not None
        ttf_label = f"Time to failure at {node.name!r}, server {self.id}"
        repair_label = f"Repair time at {node.name!r}, server {self.id}"
        while True:
            cycle_start = self.run.scheduler.now
            lifetime = sample(
                distribution=time_to_failure,
                rng=self.failure_rng,
                label=ttf_label,
                positive=True,
            )
            yield from self.count_down(
                remaining=lifetime,
                running=lambda: (
                    self._available
                    if self.failure_on_available
                    else self.phase == Phase.PROCESSING
                ),
                for_failure=True,
            )
            self.down = True
            self.station._down += 1
            self._sync_flags()
            self.sync_phase()
            self.run.observe(node.name)
            repair = sample(
                distribution=repair_time,
                rng=self.repair_rng,
                label=repair_label,
            )
            row = None
            if self.run.keep_records:
                row = _Failure(
                    station=node.name,
                    server_id=self.id,
                    failure_time=float(self.run.scheduler.now),
                    time_to_failure=lifetime,
                    repair_time=repair,
                )
                self.run.failures.append(row)
            yield self.run.scheduler.timeout(repair)
            if row is not None:
                row.repair_end = float(self.run.scheduler.now)
            self.down = False
            self.station._down -= 1
            self._sync_flags()
            self.sync_phase()
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


def _duration_labels(
    distribution: object,
    prefix: str,
    station_name: str,
) -> str | dict[str, str]:
    where = f"at {station_name!r}"
    if isinstance(distribution, Mapping):
        return {kind: f"{prefix} for type {kind!r} {where}" for kind in distribution}
    return f"{prefix} {where}"


class _Station:
    """One station's servers, waiting line, admission queue, and shifts.

    The waiting line holds admitted tickets up to the buffer, first-come,
    first-served, or by rank and then joining order at a ranked station. The
    pending queue holds tickets not yet admitted, from outside arrivals and
    blocked upstream transfers alike, in request order.
    Dispatch first gives waiting tickets to idle servers, then admits pending
    tickets while there is room. With patience, a customer who has not started
    service when it runs out leaves the network.
    """

    def __init__(self, run: _Run, node: Node, seed: np.random.SeedSequence):
        self.run = run
        self.node = node
        self.scheduled_level = (
            node.capacity if node.staffing is None else node.staffing[0][1]
        )
        self.waiting: deque[_Ticket] = deque()
        self._waiting_heap: list[tuple[float, int, _Ticket]] = []
        self._wait_seq = 0
        self._waiting_count = 0
        self.drain_check_pending = False
        self.pending: deque[_Ticket] = deque()
        self._pending_count = 0
        # Outside arrivals in the pending queue, as opposed to blocked transfers.
        self.outside = 0
        # O(1) server-state counters maintained by _Server transitions.
        self._busy = 0
        self._processing = 0
        self._blocked = 0
        self._paused = 0
        self._down = 0
        self._scheduled = 0
        self._available = 0
        self._idle_mask = 0
        # Plain stations without failures anywhere in the run can yield direct
        # service timeouts instead of wrapping every visit in count_down/AnyOf.
        self.plain_service = node.staffing is None and not run.has_failures
        self._service_labels = _duration_labels(
            node.service_time,
            "Service time",
            node.name,
        )
        self._patience_labels = (
            None
            if node.patience is None
            else _duration_labels(node.patience, "Patience", node.name)
        )
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
                scheduled = server.id <= level
                if scheduled != server.scheduled:
                    server.scheduled = scheduled
                    self._scheduled += 1 if scheduled else -1
                    server._sync_flags()
                    server.sync_phase()
            self.dispatch()
            self.run.observe(self.node.name)

    def state(self, time: float) -> _State:
        """Return the station's cached server and queue counts in O(1)."""
        return _State(
            station=self.node.name,
            time=time,
            waiting=self._waiting_count,
            busy=self._busy,
            processing=self._processing,
            blocked=self._blocked,
            paused=self._paused,
            down=self._down,
            scheduled=self._scheduled,
            available=self._available,
            idle=self._idle_mask.bit_count(),
            outside=self.outside,
        )

    def room(self) -> bool:
        if self._idle_mask and self._waiting_count == 0:
            return True
        return self.node.buffer is None or self._waiting_count < self.node.buffer

    def _push_waiting(self, ticket: _Ticket) -> None:
        self._waiting_count += 1
        ranks = self.node.priority
        if ranks is None:
            self.waiting.append(ticket)
        else:
            kind = ticket.customer.customer_type
            assert kind is not None
            heappush(self._waiting_heap, (ranks[kind], self._wait_seq, ticket))
            self._wait_seq += 1

    def _pop_waiting(self) -> _Ticket:
        if self.node.priority is None:
            while True:
                ticket = self.waiting.popleft()
                if not ticket.abandoned:
                    self._waiting_count -= 1
                    return ticket
        while True:
            _, _, ticket = heappop(self._waiting_heap)
            if not ticket.abandoned:
                self._waiting_count -= 1
                return ticket

    def _pop_pending(self) -> _Ticket:
        while True:
            ticket = self.pending.popleft()
            if not ticket.abandoned:
                self._pending_count -= 1
                return ticket

    def admit(self, customer: _Customer, *, external: bool) -> _Ticket | None:
        if self._pending_count == 0 and self.room():
            ticket = _Ticket(
                customer=customer,
                admitted=None if external else self.run.scheduler.event(),
                finished=self.run.scheduler.event(),
                external=external,
            )
            self.place(ticket)
            self.dispatch()
            return ticket
        if external and self.node.external_overflow == "reject":
            customer.status = Status.REJECTED
            customer.station = self.node.name
            return None
        ticket = _Ticket(
            customer=customer,
            admitted=self.run.scheduler.event(),
            finished=self.run.scheduler.event(),
            external=external,
        )
        self.pending.append(ticket)
        self._pending_count += 1
        if external:
            self.outside += 1
            customer.status = Status.OUTSIDE
            customer.station = self.node.name
            if self.node.abandon_from == "waiting_and_outside":
                self.start_patience(ticket)
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
        service_time = self.draw(
            distribution=self.node.service_time,
            labels=self._service_labels,
            customer=customer,
            rng=self.run.streams[self.node.name].durations,
        )
        if customer.quantity is not None:
            # A production station's service time is per unit, drawn once per job.
            service_time *= customer.quantity
        ticket.visit = _Visit(
            customer_id=customer.customer_id,
            source=customer.source,
            customer_type=customer.customer_type,
            station=self.node.name,
            arrival_time=now,
            service_time=service_time,
        )
        self.run.visits.append(ticket.visit)
        customer.station = self.node.name
        customer.status = Status.WAITING
        self._push_waiting(ticket)
        if self.node.patience is not None and not ticket.patience_started:
            self.start_patience(ticket)
        if ticket.admitted is not None:
            ticket.admitted.succeed()

    def draw(
        self,
        distribution,
        labels: str | dict[str, str],
        customer: _Customer,
        rng: np.random.Generator,
    ) -> float:
        """Sample a station duration, looking up the customer's type in a mapping."""
        if isinstance(distribution, Mapping):
            # Model.validate checks that every type reaching the station has one.
            kind = customer.customer_type
            assert kind is not None
            distribution = distribution[kind]
            assert isinstance(labels, dict)
            label = labels[kind]
        else:
            assert isinstance(labels, str)
            label = labels
        return sample(
            distribution=distribution,
            rng=rng,
            label=label,
        )

    def start_patience(self, ticket: _Ticket) -> None:
        ticket.patience_started = True
        assert self._patience_labels is not None
        delay = self.draw(
            distribution=self.node.patience,
            labels=self._patience_labels,
            customer=ticket.customer,
            rng=self.run.streams[self.node.name].patience,
        )
        self.run.scheduler.process(self.patience(ticket, delay))

    def patience(self, ticket: _Ticket, delay: float):
        # Abandonment runs after completions and transfers at the same time,
        # so a server that frees at this instant takes the customer first.
        yield self.run.scheduler.timeout(
            delay,
            priority=ABANDON_PRIORITY,
        )
        if ticket.server is not None or ticket.abandoned:
            return
        ticket.abandoned = True
        now = float(self.run.scheduler.now)
        if ticket.visit is None:
            # Only outside arrivals start the clock before admission.
            self._pending_count -= 1
            self.outside -= 1
        else:
            self._waiting_count -= 1
            ticket.visit.abandon_time = now
        ticket.customer.status = Status.ABANDONED
        ticket.customer.abandon_time = now
        self.run.release_wip()
        self.run.complete_active()
        self.dispatch()

    def dispatch(self) -> None:
        while True:
            if self._idle_mask and self._waiting_count:
                lsb = self._idle_mask & -self._idle_mask
                idle = self.servers[lsb.bit_length() - 1]
                ticket = self._pop_waiting()
                ticket.server = idle
                idle.ticket = ticket
                self._busy += 1
                visit = ticket.visit
                assert visit is not None  # place() records the visit.
                visit.server_id = idle.id
                visit.service_start = float(self.run.scheduler.now)
                visit.wait_time = self.run.scheduler.now - visit.arrival_time
                ticket.customer.total_wait += visit.wait_time
                idle._sync_flags()
                idle.sync_phase()
                self.run.scheduler.process(self.work(ticket))
                continue
            if self._pending_count and self.room():
                ticket = self._pop_pending()
                self.outside -= ticket.external
                self.place(ticket)
                continue
            break
        self.check_drain()
        self.run.observe(self.node.name)

    def work(self, ticket: _Ticket):
        # dispatch() assigns the server and place() records the visit.
        server = ticket.server
        visit = ticket.visit
        assert server is not None and visit is not None
        if self.plain_service:
            if visit.service_time > 0:
                yield self.run.scheduler.timeout(visit.service_time)
        else:
            yield from server.count_down(
                remaining=visit.service_time,
                running=lambda: server.phase == Phase.PROCESSING,
            )
        visit.service_end = float(self.run.scheduler.now)
        ticket.finished.succeed()
        server.sync_phase()
        self.run.observe(self.node.name)

    def release(self, ticket: _Ticket) -> None:
        # Only a ticket whose service finished in work() is released.
        server = ticket.server
        visit = ticket.visit
        assert server is not None and visit is not None
        assert visit.service_end is not None
        visit.departure_time = float(self.run.scheduler.now)
        visit.blocked_time = self.run.scheduler.now - visit.service_end
        ticket.customer.total_blocked += visit.blocked_time
        server.ticket = None
        self._busy -= 1
        server._sync_flags()
        server.sync_phase()
        self.dispatch()

    def check_drain(self) -> None:
        """After closing, test whether a drained run can still finish."""
        if self.run.closed and self.run.drain and not self.drain_check_pending:
            self.drain_check_pending = True
            self.run.scheduler.process(self.settled_drain_check())

    def staffed_later(self, level: int) -> bool:
        """Return whether a later shift change schedules at least this level."""
        return self.node.staffing is not None and any(
            time > self.run.scheduler.now and scheduled >= level
            for time, scheduled in self.node.staffing
        )

    def settled_drain_check(self):
        # Shift changes and completions at this instant can restore staffing
        # or finish paused work, so judge the state after they all run.
        yield self.run.settled()
        self.drain_check_pending = False
        future = (
            self.node.staffing is None
            or self.scheduled_level > 0
            or self.staffed_later(1)
        )
        paused = self.node.shift_end != "finish" and self._paused > 0
        # With patience, every waiting customer leaves in time, and each one
        # who leaves frees room for a pending ticket, so only pending tickets
        # behind an empty line wait forever. Outside arrivals that can abandon
        # leave too.
        leaving = self.node.patience is not None
        held = self._pending_count
        if self.node.abandon_from == "waiting_and_outside":
            held -= self.outside
        stuck = (self._waiting_count > 0 and not leaving) or (
            held > 0 and not (self._waiting_count > 0 and leaving)
        )
        if not future and (stuck or paused):
            raise RuntimeError(
                f"Cannot drain station {self.node.name!r}. Unfinished work has no future staffing."
            )
        for server in self.servers:
            if (
                server.phase == Phase.PAUSED
                and not server.scheduled
                and self.node.shift_end == "pause"
                and not self.staffed_later(server.id)
            ):
                raise RuntimeError(
                    f"Cannot drain station {self.node.name!r}. Server {server.id} "
                    "has paused work and no future staffing."
                )
