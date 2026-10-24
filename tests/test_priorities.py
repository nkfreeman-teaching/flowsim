"""Ranked waiting lines, checked by hand.

A station with a priority serves the lowest rank in its waiting line first, and
equal ranks keep the order customers joined. The pending queue outside a finite
buffer keeps request order, and service is never interrupted.
"""

import polars as pl
import pytest

from flowsim import Model


def triage_model(
    routine: list[float],
    critical: float,
    *,
    buffer: int | None = None,
    priority=None,
) -> Model:
    """Routine customers arrive at evenly spaced times and one Critical customer later.

    One server takes 2 for every type.
    """
    if priority is None:
        priority = {"Critical": 1, "Routine": 2}
    model = Model()
    routine_source = model.source(
        name="Routine",
        interarrival=routine[1] - routine[0],
        first_arrival=routine[0],
        limit=len(routine),
        types={"Routine": 1},
    )
    critical_source = model.source(
        name="Critical",
        interarrival=1,
        first_arrival=critical,
        limit=1,
        types={"Critical": 1},
    )
    triage = model.station(
        name="Triage",
        capacity=1,
        service_time=2,
        buffer=buffer,
        external_overflow=None if buffer is None else "wait",
        priority=priority,
    )
    model.route([routine_source, triage])
    model.route([critical_source, triage, model.exit])
    return model


def service_order(model: Model) -> list[tuple[str, float, float]]:
    result = model.run(
        duration=20,
        drain=True,
    )
    return (
        result.visits.sort("service_start")
        .select(
            "customer_type",
            "service_start",
            "wait_time",
        )
        .rows()
    )


def test_a_lower_rank_leaves_the_waiting_line_first():
    # The server takes Routine (arrived 0) at 0. Routine (0.5) and Critical (1)
    # then wait, and Critical goes next at 2 although it arrived later. The
    # second Routine starts at 4. First-come, first-served would give waits of
    # 0, 1.5, and 3 instead.
    assert service_order(
        triage_model(
            routine=[0, 0.5],
            critical=1,
        )
    ) == [
        ("Routine", 0, 0),
        ("Critical", 2, 1),
        ("Routine", 4, 3.5),
    ]
    assert service_order(
        triage_model(
            routine=[0, 0.5],
            critical=1,
            priority={"Critical": 1, "Routine": 1},
        )
    ) == [
        ("Routine", 0, 0),
        ("Routine", 2, 1.5),
        ("Critical", 4, 3),
    ]


def test_ranks_order_only_the_inside_line():
    # Routine customers arrive at 0, 0.1, and 0.2 and Critical at 0.3. With a
    # buffer of 1, the first starts at 0, the second waits inside, and the third
    # and Critical wait outside in that order. Each completion at 2, 4, and 6
    # starts the inside customer and admits the next outside one, so Critical
    # is last.
    finite = service_order(
        triage_model(
            routine=[0, 0.1, 0.2],
            critical=0.3,
            buffer=1,
        )
    )
    assert [(kind, start) for kind, start, _ in finite] == [
        ("Routine", 0),
        ("Routine", 2),
        ("Routine", 4),
        ("Critical", 6),
    ]
    # With an unlimited buffer, all three wait inside by 0.3, so Critical goes
    # at 2 and the Routine customers keep their arrival order.
    unlimited = service_order(
        triage_model(
            routine=[0, 0.1, 0.2],
            critical=0.3,
        )
    )
    assert [(kind, start) for kind, start, _ in unlimited] == [
        ("Routine", 0),
        ("Critical", 2),
        ("Routine", 4),
        ("Routine", 6),
    ]
    assert unlimited[1][2] == pytest.approx(1.7)
    assert unlimited[3][2] == pytest.approx(5.8)


def test_equal_ranks_match_first_come_first_served_on_a_seeded_run():
    def build(priority) -> Model:
        model = Model()
        customers = model.source(
            name="Customers",
            interarrival=lambda rng: rng.exponential(scale=1),
            types={"A": 0.5, "B": 0.5},
        )
        desk = model.station(
            name="Desk",
            capacity=2,
            service_time=lambda rng: rng.exponential(scale=1.8),
            priority=priority,
        )
        model.route([customers, desk, model.exit])
        return model

    plain = build(None).run(
        duration=200,
        seed=4,
    )
    ranked = build({"A": 3, "B": 3}).run(
        duration=200,
        seed=4,
    )
    assert plain.visits.height > 150
    assert ranked.visits.equals(plain.visits)
    assert ranked.definitions["Desk"]["priority"] == {"A": 3, "B": 3}
    assert plain.definitions["Desk"]["priority"] is None
    # Ranking A ahead of B shortens A's mean wait on the same arrivals.
    favored = build({"A": 1, "B": 2}).run(
        duration=200,
        seed=4,
    )
    waits = (
        favored.visits.group_by("customer_type")
        .agg(pl.col("wait_time").mean())
        .sort("customer_type")
        .get_column("wait_time")
        .to_list()
    )
    assert waits[0] < waits[1]


def test_run_start_checks_ranks_for_every_type_that_arrives():
    model = triage_model(
        routine=[0, 0.5],
        critical=1,
        priority={"Critical": 1},
    )
    with pytest.raises(ValueError, match="'Triage' has no rank for type 'Routine'"):
        model.run(duration=10)
    model = Model()
    customers = model.source(
        name="Customers",
        interarrival=1,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=1,
        priority={"A": 1},
    )
    model.route([customers, desk, model.exit])
    with pytest.raises(
        ValueError,
        match="'Desk' ranks customers by type, and customers from 'Customers' have no type",
    ):
        model.run(duration=10)


@pytest.mark.parametrize(
    ("priority", "message"),
    [
        (1, "priority must map each customer type to its rank"),
        ({}, "priority must map each customer type to its rank"),
        ({"A": -1}, "Rank of type 'A' must be finite and at least zero"),
        ({"A": True}, "Rank of type 'A' must be a finite number"),
        ({" ": 1}, "Customer types must be nonempty names"),
    ],
)
def test_priority_arguments_are_validated(priority, message):
    with pytest.raises(ValueError, match=message):
        Model().station(
            name="Desk",
            capacity=1,
            service_time=1,
            priority=priority,
        )
