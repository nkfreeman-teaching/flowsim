"""Abandonment after a patience time, checked by hand.

A customer who has not started service when its patience runs out leaves the
network. At equal times, service wins, because abandonment runs after
completions and transfers. Abandoned customers stay out of wait and flow
averages, and the summary reports how many left.
"""

import polars as pl
import pytest

from flowsim import Model
from flowsim.plots import timeline_spans


def call_line(
    patience=3,
    *,
    service_time: float = 5,
    arrivals: int = 3,
) -> Model:
    """Arrivals at 0, 1, and 2 on one server that waiting customers may leave."""
    model = Model()
    callers = model.source(
        name="Callers",
        interarrival=1,
        first_arrival=0,
        limit=arrivals,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=service_time,
        patience=patience,
        abandon_from=None if patience is None else "waiting",
    )
    model.route([callers, desk, model.exit])
    return model


def test_a_customer_leaves_when_patience_runs_out_and_service_wins_ties():
    # Customer 1 is served over [0, 5]. Customer 2 waits from 1 and leaves at
    # 1 + 3 = 4. Customer 3 waits from 2, and its patience ends at 5, the
    # instant the server frees, so it starts at 5 and finishes at 10.
    result = call_line().run(
        duration=20,
        drain=True,
    )
    customers = result.customers.sort("customer_id")
    assert customers.get_column("status").to_list() == [
        "completed",
        "abandoned",
        "completed",
    ]
    assert customers.get_column("abandon_time").to_list() == [None, 4, None]
    assert customers.get_column("exit_time").to_list() == [5, None, 10]
    assert customers.get_column("flow_time").to_list() == [5, None, 8]
    assert customers.get_column("station").to_list() == [None, "Desk", None]
    visits = result.visits.sort("customer_id")
    assert visits.select(
        "service_start",
        "wait_time",
        "abandon_time",
    ).rows() == [(0, 0, None), (None, None, 4), (5, 3, None)]
    # The waiting line drops from 2 to 1 at 4.
    desk = result.states.filter(pl.col("time") == 4)
    assert desk.get_column("waiting").to_list() == [1]
    summary = result.summary.to_dicts()[0]
    assert summary["arrivals"] == 3
    assert summary["completed"] == 2
    assert summary["abandoned"] == 1
    assert summary["remaining"] == 0
    assert summary["rejected"] == 0
    assert summary["measurement_abandoned"] == 1
    assert summary["abandonment_rate"] == pytest.approx(1 / 3)
    # Only completed customers enter the averages: waits 0 and 3, and flow
    # times 5 and 8.
    assert summary["mean_total_wait"] == 1.5
    assert summary["mean_flow_time"] == 6.5
    assert result.stations.get_column("mean_wait").to_list() == [1.5]
    assert result.stations.get_column("wait_observations").to_list() == [2]
    # Presence is [0, 5], [1, 4], and [2, 10], i.e., 16 over a window of 20.
    assert summary["mean_wip"] == pytest.approx(0.8)
    assert result.definitions["Desk"]["abandon_from"] == "waiting"


def test_abandonment_counts_by_its_own_time_and_the_rate_by_arrival():
    # With warm-up at 1.5, only customer 3 arrives in the window, so the rate
    # is 0 of 1. Customer 2's abandonment at 4 still falls in the window.
    summary = (
        call_line()
        .run(
            duration=20,
            warmup=1.5,
            drain=True,
        )
        .summary.to_dicts()[0]
    )
    assert summary["measurement_arrivals"] == 1
    assert summary["measurement_abandoned"] == 1
    assert summary["abandonment_rate"] == 0
    assert summary["cohort_remaining"] == 0


def test_closing_counts_leave_out_customers_who_already_abandoned():
    # At closing time 4.5, customer 1 is in service, customer 2 left at 4, and
    # customer 3 is waiting, so two customers remain and none completed.
    result = call_line().run(duration=4.5)
    summary = result.summary.to_dicts()[0]
    assert summary["abandoned"] == 1
    assert summary["completed_at_close"] == 0
    assert summary["remaining_at_close"] == 2
    assert summary["remaining"] == 2
    assert summary["arrivals"] == (
        summary["completed"]
        + summary["remaining"]
        + summary["rejected"]
        + summary["abandoned"]
    )


def lobby(patience, abandon_from: str) -> Model:
    """One server taking 4, a buffer of one, and outside arrivals that wait.

    Calm customers arrive at 0 and 0.5, and a Hasty customer arrives at 1.
    """
    model = Model()
    calm = model.source(
        name="Calm",
        interarrival=0.5,
        first_arrival=0,
        limit=2,
        types={"Calm": 1},
    )
    hasty = model.source(
        name="Hasty",
        interarrival=1,
        first_arrival=1,
        limit=1,
        types={"Hasty": 1},
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=4,
        buffer=1,
        external_overflow="wait",
        patience=patience,
        abandon_from=abandon_from,
    )
    model.route([calm, desk])
    model.route([hasty, desk, model.exit])
    return model


def test_an_outside_arrival_can_abandon_before_admission():
    # Calm 1 starts at 0, and Calm 2 waits inside from 0.5. The Hasty customer
    # waits outside from 1 and leaves at 1 + 1 = 2 without a visit. Calm 2
    # starts at 4.
    result = lobby(
        patience={"Calm": 10, "Hasty": 1},
        abandon_from="waiting_and_outside",
    ).run(
        duration=20,
        drain=True,
    )
    hasty = result.customers.filter(pl.col("customer_type") == "Hasty").to_dicts()[0]
    assert hasty["status"] == "abandoned"
    assert hasty["abandon_time"] == 2
    assert hasty["admitted"] is False
    assert hasty["outside_wait"] is None
    assert result.visits.get_column("customer_type").to_list() == ["Calm", "Calm"]
    assert result.visits.get_column("service_start").to_list() == [0, 4]
    outside = result.states.select(
        "time",
        "outside",
    ).rows()
    assert (1, 1) in outside
    assert (2, 0) in outside
    spans = timeline_spans(result).filter(pl.col("customer_id") == hasty["customer_id"])
    assert spans.select(
        "activity",
        "start",
        "end",
    ).rows() == [("Outside", 1, 2)]
    assert result.summary.to_dicts()[0]["outside_at_close"] == 0


@pytest.mark.parametrize(
    ("abandon_from", "statuses", "starts"),
    [
        # The clock starts outside at 1 and keeps running after admission at
        # 2.5, when customer 2 leaves, so customer 3 leaves at 1 + 2 = 3.
        ("waiting_and_outside", ["completed", "abandoned", "abandoned"], [0]),
        # The clock starts at admission at 2.5, so it would end at 4.5, and the
        # server frees at 4 first.
        ("waiting", ["completed", "abandoned", "completed"], [0, 4]),
    ],
)
def test_the_patience_clock_starts_where_abandonment_is_allowed(
    abandon_from,
    statuses,
    starts,
):
    model = Model()
    callers = model.source(
        name="Callers",
        interarrival=0.5,
        first_arrival=0,
        limit=3,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=4,
        buffer=1,
        external_overflow="wait",
        patience=2,
        abandon_from=abandon_from,
    )
    model.route([callers, desk, model.exit])
    result = model.run(
        duration=20,
        drain=True,
    )
    customers = result.customers.sort("customer_id")
    assert customers.get_column("status").to_list() == statuses
    assert customers.get_column("admission_time").to_list() == [0, 0.5, 2.5]
    assert customers.get_column("outside_wait").to_list() == [0, 0, 1.5]
    assert (
        sorted(result.visits.get_column("service_start").drop_nulls().to_list())
        == starts
    )
    # Customer 3's waiting bar inside runs from admission to leaving or service.
    third = timeline_spans(result).filter(
        (pl.col("customer_id") == 3) & (pl.col("activity") == "Waiting")
    )
    assert third.select(
        "start",
        "end",
    ).rows() == [(2.5, 3 if abandon_from == "waiting_and_outside" else 4)]


def test_a_drained_station_without_staff_finishes_once_waiting_customers_leave():
    # Arrivals at 0, 1, and 2 take 2 each. The server finishes customer 1 at 2
    # and customer 2 at 4, after its shift ends at 3. Customer 3 waits from 2
    # with no future staffing and leaves at 2 + 4 = 6, which ends the run.
    def staffed(patience):
        model = Model()
        callers = model.source(
            name="Callers",
            interarrival=1,
            first_arrival=0,
            limit=3,
        )
        desk = model.station(
            name="Desk",
            capacity=1,
            service_time=2,
            staffing=[(0, 1), (3, 0)],
            shift_end="finish",
            patience=patience,
            abandon_from=None if patience is None else "waiting",
        )
        model.route([callers, desk, model.exit])
        return model

    result = staffed(4).run(
        duration=3,
        drain=True,
    )
    assert result.end_time == 6
    summary = result.summary.to_dicts()[0]
    assert summary["completed"] == 2
    assert summary["abandoned"] == 1
    assert summary["overtime"] == 3
    with pytest.raises(RuntimeError, match="Cannot drain station 'Desk'"):
        staffed(None).run(
            duration=3,
            drain=True,
        )


def test_patience_that_never_runs_out_changes_no_other_draw():
    def build(patience) -> Model:
        model = Model()
        customers = model.source(
            name="Customers",
            interarrival=lambda rng: rng.exponential(scale=1),
        )
        desk = model.station(
            name="Desk",
            capacity=2,
            service_time=lambda rng: rng.exponential(scale=1.8),
            patience=patience,
            abandon_from=None if patience is None else "waiting",
        )
        model.route([customers, desk, model.exit])
        return model

    plain = build(None).run(
        duration=200,
        seed=4,
    )
    patient = build(lambda rng: 1e9 + rng.exponential(scale=1)).run(
        duration=200,
        seed=4,
    )
    assert plain.visits.height > 150
    assert patient.visits.equals(plain.visits)
    impatient = build(lambda rng: rng.exponential(scale=2)).run(
        duration=200,
        seed=4,
    )
    summary = impatient.summary.to_dicts()[0]
    assert summary["abandoned"] > 0
    assert summary["arrivals"] == (
        summary["completed"]
        + summary["remaining"]
        + summary["rejected"]
        + summary["abandoned"]
    )
    experiment = build(lambda rng: rng.exponential(scale=2)).experiment(
        duration=100,
        replications=3,
    )
    interval = experiment.intervals("abandonment_rate").to_dicts()[0]
    assert interval["observed_runs"] == 3
    assert 0 < interval["mean"] < 1


def test_run_start_checks_patience_for_every_type_that_arrives():
    with pytest.raises(ValueError, match="'Desk' has no patience for type 'Hasty'"):
        lobby(
            patience={"Calm": 10},
            abandon_from="waiting",
        ).run(duration=10)
    with pytest.raises(
        ValueError,
        match="'Desk' sets patience by customer type, and customers from 'Callers' have no type",
    ):
        call_line(patience={"A": 1}).run(duration=10)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"patience": 3}, "Patience requires abandon_from='waiting'"),
        (
            {"patience": 3, "abandon_from": "outside"},
            "Patience requires abandon_from='waiting'",
        ),
        ({"abandon_from": "waiting"}, "abandon_from requires patience"),
        (
            {"patience": 3, "abandon_from": "waiting_and_outside"},
            "requires a finite buffer with external_overflow='wait'",
        ),
        (
            {
                "patience": 3,
                "abandon_from": "waiting_and_outside",
                "buffer": 1,
                "external_overflow": "reject",
            },
            "requires a finite buffer with external_overflow='wait'",
        ),
        (
            {"patience": -1, "abandon_from": "waiting"},
            "Patience must be finite and at least zero",
        ),
        (
            {"patience": {}, "abandon_from": "waiting"},
            "A patience mapping needs at least one customer type",
        ),
        (
            {"patience": {"A": -1}, "abandon_from": "waiting"},
            "Patience for type 'A'",
        ),
    ],
)
def test_patience_arguments_are_validated(arguments, message):
    with pytest.raises(ValueError, match=message):
        Model().station(
            name="Desk",
            capacity=1,
            service_time=1,
            **arguments,
        )
