"""Hand-checked ordering rules for the private event scheduler."""

import pytest

from flowsim.scheduler import NORMAL, SHIFT_PRIORITY, Scheduler
from tests.models import breaks_after_first_repair


def logger(log: list, label: str):
    return lambda event: log.append((label, event.scheduler.now))


def test_equal_times_run_by_priority_then_queue_order():
    scheduler = Scheduler()
    log = []
    late = scheduler.timeout(0, priority=NORMAL + 1)
    late.callbacks.append(logger(log, "after NORMAL"))
    first, second = scheduler.event(), scheduler.event()
    first.callbacks.append(logger(log, "created first"))
    second.callbacks.append(logger(log, "created second"))
    # Queue order, not creation order, breaks the tie between NORMAL events.
    second.succeed()
    first.succeed()
    scheduler.run(until=1)
    assert log == [
        ("created second", 0),
        ("created first", 0),
        ("after NORMAL", 0),
    ]


def test_shift_priority_precedes_normal_events_queued_earlier():
    scheduler = Scheduler()
    log = []
    completion = scheduler.timeout(1)
    completion.callbacks.append(logger(log, "completion"))
    shift = scheduler.timeout(1, priority=SHIFT_PRIORITY)
    shift.callbacks.append(logger(log, "shift change"))
    scheduler.run(until=2)
    assert log == [("shift change", 1), ("completion", 1)]


def test_process_start_precedes_queued_events_at_the_same_time():
    scheduler = Scheduler()
    log = []

    def process():
        log.append(("process start", scheduler.now))
        yield scheduler.timeout(0)

    starter = scheduler.timeout(1)
    starter.callbacks.append(lambda event: scheduler.process(process()))
    starter.callbacks.append(logger(log, "starter"))
    queued = scheduler.timeout(1)
    queued.callbacks.append(logger(log, "queued"))
    scheduler.run(until=2)
    assert log == [("starter", 1), ("process start", 1), ("queued", 1)]


def test_yielding_a_processed_event_continues_without_waiting():
    scheduler = Scheduler()
    log = []
    done = scheduler.event()
    done.succeed()

    def process():
        yield scheduler.timeout(1)
        log.append(("after timeout", scheduler.now))
        yield done
        log.append(("after processed event", scheduler.now))

    scheduler.process(process())
    scheduler.run(until=0.5)
    # The marker is queued for time 1 after the process's timeout. Continuing
    # past the processed event without waiting puts both logs before it.
    marker = scheduler.timeout(0.5)
    marker.callbacks.append(logger(log, "marker"))
    scheduler.run(until=2)
    assert log == [
        ("after timeout", 1),
        ("after processed event", 1),
        ("marker", 1),
    ]


def test_any_of_lists_events_processed_before_it():
    scheduler = Scheduler()
    timeout = scheduler.timeout(1)
    changed = scheduler.event()
    first = scheduler.any_of([timeout, changed])
    # The change is queued after the condition, so it is not in the value.
    trigger = scheduler.timeout(1)
    trigger.callbacks.append(lambda event: changed.succeed())
    scheduler.run(until=2)
    assert first.value == [timeout]

    scheduler = Scheduler()
    changed = scheduler.event()
    trigger = scheduler.timeout(1)
    trigger.callbacks.append(lambda event: changed.succeed())
    timeout = scheduler.timeout(1)
    second = scheduler.any_of([timeout, changed])
    # The change is queued before the condition, so both are in the value.
    scheduler.run(until=2)
    assert second.value == [timeout, changed]


def test_any_of_leaves_the_losing_timeout_without_callbacks():
    scheduler = Scheduler()
    timeout = scheduler.timeout(5)
    changed = scheduler.event()
    condition = scheduler.any_of([timeout, changed])
    trigger = scheduler.timeout(1)
    trigger.callbacks.append(lambda event: changed.succeed())
    scheduler.run(until=2)
    assert condition.value == [changed]
    assert timeout.callbacks == []


def test_run_until_a_time_leaves_events_at_that_time():
    scheduler = Scheduler()
    log = []
    boundary = scheduler.timeout(2)
    boundary.callbacks.append(logger(log, "boundary"))
    scheduler.run(until=2)
    assert scheduler.now == 2
    assert log == []
    with pytest.raises(ValueError, match="Cannot run until"):
        scheduler.run(until=2)
    finished = scheduler.event()
    finished.succeed()
    scheduler.run(until=finished)
    assert log == [("boundary", 2)]


def test_run_until_an_event_fails_when_the_queue_empties():
    scheduler = Scheduler()
    with pytest.raises(RuntimeError, match="No scheduled events remain"):
        scheduler.run(until=scheduler.event())


def test_invalid_triggers_raise():
    scheduler = Scheduler()
    event = scheduler.event()
    event.succeed()
    with pytest.raises(RuntimeError, match="only once"):
        event.succeed()
    with pytest.raises(ValueError, match="Negative delay"):
        scheduler.timeout(-1)


def test_process_error_waits_for_its_turn_and_keeps_its_identity():
    errors = []

    def failing(scheduler):
        yield scheduler.timeout(1)
        errors.append(KeyError("sampler"))
        raise errors[-1]

    scheduler = Scheduler()
    finished = scheduler.event()
    closer = scheduler.timeout(1)
    closer.callbacks.append(lambda event: finished.succeed())
    scheduler.process(failing(scheduler))
    # The finished event is queued before the error, so the run stops cleanly.
    scheduler.run(until=finished)

    scheduler = Scheduler()
    scheduler.process(failing(scheduler))
    with pytest.raises(KeyError) as raised:
        scheduler.run(until=5)
    assert raised.value is errors[-1]


def test_interrupts_stop_the_run_at_once():
    def exiting(scheduler):
        yield scheduler.timeout(1)
        raise SystemExit("stop")

    scheduler = Scheduler()
    finished = scheduler.event()
    closer = scheduler.timeout(1)
    closer.callbacks.append(lambda event: finished.succeed())
    scheduler.process(exiting(scheduler))
    # Unlike an ordinary error, SystemExit does not wait for its turn.
    with pytest.raises(SystemExit):
        scheduler.run(until=finished)


def test_model_error_after_the_last_event_is_not_raised():
    # The machine fails at 1 and is repaired at 2. Closing at 2 queues the
    # finished event before the repair asks for its next lifetime.
    result = breaks_after_first_repair().run(duration=2, drain=True)
    assert result.failures.get_column("failure_time").to_list() == [1]
    assert result.failures.get_column("repair_end").to_list() == [2]
    assert result.end_time == 2
    with pytest.raises(ValueError, match="No second lifetime"):
        breaks_after_first_repair().run(duration=3)
