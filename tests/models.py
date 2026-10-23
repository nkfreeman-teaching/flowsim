"""Fixed models for tests, separate from the teaching examples.

Editing an example for teaching reasons must not change these models.
"""

from flowsim import Model


def deterministic_queue(capacity: int = 1) -> Model:
    """Three customers arrive at 0, 1, and 2. Each needs two time units."""
    model = Model(time_unit="minutes")
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    service = model.station(
        name="Service",
        capacity=capacity,
        service_time=2,
    )
    model.route([arrivals, service, model.exit])
    return model


def single_station(**options) -> Model:
    """Three customers arrive at 0, 1, and 2. Each needs three time units."""
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=1,
        first_arrival=0,
        limit=3,
    )
    station = model.station(
        name="Service",
        capacity=1,
        service_time=3,
        **options,
    )
    model.route([arrivals, station, model.exit])
    return model


def service_network(service_capacity: int = 2) -> Model:
    """Customers check in, receive service, and leave."""
    model = Model(time_unit="minutes")
    arrivals = model.source(
        name="Customers",
        interarrival=lambda rng: rng.exponential(scale=3),
    )
    check_in = model.station(
        name="Check-in",
        capacity=1,
        service_time=lambda rng: rng.uniform(1, 2),
    )
    service = model.station(
        name="Service",
        capacity=service_capacity,
        service_time=lambda rng: rng.exponential(scale=4),
    )
    model.route([arrivals, check_in, service, model.exit])
    return model


def branching_service() -> Model:
    """After triage, 70% use routine service and 30% use specialist service."""
    model = Model(time_unit="minutes")
    arrivals = model.source(
        name="Customers",
        interarrival=lambda rng: rng.exponential(scale=3),
    )
    triage = model.station(
        name="Triage",
        capacity=1,
        service_time=1,
    )
    routine = model.station(
        name="Routine",
        capacity=2,
        service_time=lambda rng: rng.gamma(
            shape=2,
            scale=2,
        ),
    )
    specialist = model.station(
        name="Specialist",
        capacity=1,
        service_time=lambda rng: rng.uniform(5, 8),
    )
    model.route([arrivals, triage])
    model.branch(triage, {routine: 0.7, specialist: 0.3})
    model.route([routine, model.exit])
    model.route([specialist, model.exit])
    return model


def repairing_machine(failure_clock: str = "available") -> Model:
    model = Model()
    arrivals = model.source(
        name="Parts",
        interarrival=lambda rng: rng.exponential(scale=5),
    )
    machine = model.station(
        name="Machine",
        capacity=2,
        service_time=lambda rng: rng.uniform(4, 8),
        time_to_failure=lambda rng: rng.exponential(scale=30),
        repair_time=lambda rng: rng.uniform(3, 8),
        failure_clock=failure_clock,
    )
    model.route([arrivals, machine, model.exit])
    return model


def combined_line(
    shift_end: str = "finish",
    failure_clock: str = "available",
) -> Model:
    """A staffed, buffered assembly step feeding a finishing step that fails."""
    model = Model()
    arrivals = model.source(
        name="Parts",
        rates=[(0, 0.5), (50, 1), (120, 0.3)],
    )
    assembly = model.station(
        name="Assembly",
        capacity=2,
        service_time=lambda rng: rng.uniform(1, 2),
        staffing=[(0, 1), (50, 2), (120, 1), (200, 2)],
        shift_end=shift_end,
        buffer=3,
        external_overflow="reject",
    )
    finishing = model.station(
        name="Finishing",
        capacity=1,
        service_time=lambda rng: rng.uniform(2, 4),
        buffer=2,
        external_overflow="reject",
        time_to_failure=lambda rng: rng.exponential(scale=35),
        repair_time=lambda rng: rng.uniform(2, 5),
        failure_clock=failure_clock,
    )
    model.route([arrivals, assembly, finishing, model.exit])
    return model


def breaks_after_first_repair() -> Model:
    """An idle machine fails at 1 and is repaired at 2. Its next lifetime raises."""
    lifetimes = iter([1.0])

    def lifetime(rng):
        try:
            return next(lifetimes)
        except StopIteration:
            raise ValueError("No second lifetime.") from None

    model = Model()
    arrivals = model.source(
        name="Parts",
        interarrival=1,
        limit=0,
    )
    machine = model.station(
        name="Machine",
        capacity=1,
        service_time=1,
        time_to_failure=lifetime,
        repair_time=1,
        failure_clock="available",
    )
    model.route([arrivals, machine, model.exit])
    return model
