"""Small service systems with adjustable capacity."""

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
