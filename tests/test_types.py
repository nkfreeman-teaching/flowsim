"""Customer types, typed service times, and typed routes, checked by hand.

A source with types gives each arrival one of them, and stations and routes may
depend on the type. Each type's routes are acyclic, and routes across types may
cycle only through stations with unlimited buffers.
"""

import json
import zlib

import numpy as np
import polars as pl
import pytest

from flowsim import Model
from flowsim.plots import layout_layers
from tests.models import job_shop


def mill_model() -> Model:
    """Type A arrives at 0, 4, and 8, and type B arrives at 1, 5, and 9.

    The Mill takes 1 for A and 2 for B. A then goes to the Lathe and B to
    Paint, each taking 1.
    """
    model = Model()
    first = model.source(
        name="Source A",
        interarrival=4,
        first_arrival=0,
        limit=3,
        types={"A": 1},
    )
    second = model.source(
        name="Source B",
        interarrival=4,
        first_arrival=1,
        limit=3,
        types={"B": 1},
    )
    mill = model.station(
        name="Mill",
        capacity=1,
        service_time={"A": 1, "B": 2},
    )
    lathe = model.station(
        name="Lathe",
        capacity=1,
        service_time=1,
    )
    paint = model.station(
        name="Paint",
        capacity=1,
        service_time=1,
    )
    model.route([first, mill])
    model.route([second, mill])
    model.route(
        [mill, lathe, model.exit],
        types=["A"],
    )
    model.route(
        [mill, paint, model.exit],
        types=["B"],
    )
    return model


def mixed_model(types=None, typed_branch: bool = False) -> Model:
    """Exponential arrivals and a branch after one station."""
    model = Model()
    customers = model.source(
        name="Customers",
        interarrival=lambda rng: rng.exponential(scale=2),
        types=types,
    )
    front = model.station(
        name="Front",
        capacity=2,
        service_time=lambda rng: rng.exponential(scale=3),
    )
    left = model.station(
        name="Left",
        capacity=1,
        service_time=1,
    )
    right = model.station(
        name="Right",
        capacity=1,
        service_time=1,
    )
    model.route([customers, front])
    model.branch(
        origin=front,
        destinations={left: 0.3, right: 0.7},
        types=["A"] if typed_branch else None,
    )
    model.route([left, model.exit])
    model.route([right, model.exit])
    return model


def run_error(model: Model) -> str:
    with pytest.raises(ValueError) as error:
        model.run(duration=10)
    return str(error.value)


def test_typed_service_and_routes_follow_the_hand_schedule():
    # The Mill serves A over [0, 1], B over [1, 3], A over [4, 5], B over
    # [5, 7], A over [8, 9], and B over [9, 11]. Each then takes 1 more at the
    # Lathe or Paint, so exits are 2, 4, 6, 8, 10, and 12.
    result = mill_model().run(
        duration=20,
        drain=True,
    )
    customers = result.customers.sort("customer_id")
    assert customers.get_column("customer_type").to_list() == ["A", "B"] * 3
    assert customers.get_column("exit_time").to_list() == [2, 4, 6, 8, 10, 12]
    mill = result.visits.filter(pl.col("station") == "Mill").sort("service_start")
    assert mill.get_column("service_start").to_list() == [0, 1, 4, 5, 8, 9]
    assert mill.get_column("service_time").to_list() == [1, 2, 1, 2, 1, 2]
    later = result.visits.filter(pl.col("station") != "Mill")
    assert later.select("customer_type", "station").unique().sort(
        "customer_type"
    ).rows() == [("A", "Lathe"), ("B", "Paint")]


def test_type_draws_use_their_own_stream():
    # Types come from the source's stream with purpose 3, one choice per
    # arrival, so NumPy alone gives them, and arrivals, service times, and
    # routing match the same model without types.
    seed = 7
    typed = mixed_model(types={"A": 0.6, "B": 0.4}).run(
        duration=60,
        seed=seed,
    )
    plain = mixed_model().run(
        duration=60,
        seed=seed,
    )
    rng = np.random.default_rng(
        np.random.SeedSequence(
            entropy=seed,
            spawn_key=(zlib.crc32(b"Customers"), 3),
        )
    )
    expected = [
        ["A", "B"][rng.choice(2, p=[0.6, 0.4])] for _ in range(typed.customers.height)
    ]
    assert typed.customers.get_column("customer_type").to_list() == expected
    assert set(expected) == {"A", "B"}
    columns = ["customer_id", "station", "arrival_time", "service_time", "wait_time"]
    assert typed.visits.select(columns).equals(plain.visits.select(columns))
    assert typed.customers.drop("customer_type").equals(
        plain.customers.drop("customer_type")
    )


def test_untyped_customers_have_a_null_type_and_one_type_draws_nothing():
    plain = mixed_model().run(duration=30)
    assert plain.customers.get_column("customer_type").null_count() == (
        plain.customers.height
    )
    assert plain.visits.get_column("customer_type").null_count() == (
        plain.visits.height
    )
    single = mixed_model(types={"A": 1}).run(duration=30)
    assert single.customers.get_column("customer_type").unique().to_list() == ["A"]
    assert single.visits.get_column("customer_type").unique().to_list() == ["A"]


def test_a_typed_branch_draws_like_an_untyped_branch():
    # The branch draws from the Front's routing stream either way.
    typed = mixed_model(
        types={"A": 1},
        typed_branch=True,
    ).run(duration=60)
    plain = mixed_model().run(duration=60)
    assert typed.visits.drop("customer_type").equals(plain.visits.drop("customer_type"))


def test_job_shop_cycles_across_types_with_unlimited_buffers():
    # At 0, A starts on the Mill until 1, and B starts on the Lathe until 3.
    # A reaches the Lathe at 1 and waits until 3, so it leaves at 5. B moves
    # to the free Mill at 3 and leaves at 4.
    result = job_shop().run(
        duration=20,
        drain=True,
    )
    visits = result.visits.sort("customer_type", "arrival_time")
    assert visits.select(
        "customer_type",
        "station",
        "arrival_time",
        "service_start",
        "wait_time",
        "departure_time",
    ).rows() == [
        ("A", "Mill", 0, 0, 0, 1),
        ("A", "Lathe", 1, 3, 2, 5),
        ("B", "Lathe", 0, 0, 0, 3),
        ("B", "Mill", 3, 3, 0, 4),
    ]
    exits = result.customers.sort("customer_type").get_column("exit_time")
    assert exits.to_list() == [5, 4]


def test_a_finite_buffer_on_a_cross_type_cycle_raises():
    with pytest.raises(ValueError, match="'Lathe' has a finite buffer and lies on"):
        job_shop(lathe_buffer=2)
    # A finite buffer off the cycle is allowed.
    model = Model()
    orders = model.source(
        name="Orders",
        interarrival=1,
        types={"A": 0.5, "B": 0.5},
    )
    mill = model.station(
        name="Mill",
        capacity=1,
        service_time=0.2,
    )
    lathe = model.station(
        name="Lathe",
        capacity=1,
        service_time=0.2,
    )
    pack = model.station(
        name="Pack",
        capacity=1,
        service_time=0.2,
        buffer=1,
        external_overflow="wait",
    )
    model.branch(
        origin=orders,
        destinations={mill: 1},
        types=["A"],
    )
    model.branch(
        origin=orders,
        destinations={lathe: 1},
        types=["B"],
    )
    model.route(
        [mill, lathe, pack],
        types=["A"],
    )
    model.route(
        [lathe, mill, pack],
        types=["B"],
    )
    model.route([pack, model.exit])
    result = model.run(duration=10)
    assert result.customers.height > 0


def test_each_types_routes_must_be_acyclic():
    model = Model()
    mill = model.station(
        name="Mill",
        capacity=1,
        service_time=1,
    )
    lathe = model.station(
        name="Lathe",
        capacity=1,
        service_time=1,
    )
    with pytest.raises(ValueError, match="routes for type 'A' form a cycle"):
        model.route(
            [mill, lathe, mill],
            types=["A"],
        )
    model.route(
        [mill, lathe],
        types=["A"],
    )
    with pytest.raises(ValueError, match="routes for type 'A' form a cycle"):
        model.route(
            [lathe, mill],
            types=["A"],
        )
    # A failed edit leaves the model unchanged.
    assert list(model.graph.edges) == [("Mill", "Lathe")]
    with pytest.raises(ValueError, match="acyclic routes only"):
        model.route([lathe, mill, lathe])


def test_routing_rules_for_one_node_cannot_overlap():
    model = Model()
    mill = model.station(
        name="Mill",
        capacity=1,
        service_time=1,
    )
    lathe = model.station(
        name="Lathe",
        capacity=1,
        service_time=1,
    )
    paint = model.station(
        name="Paint",
        capacity=1,
        service_time=1,
    )
    model.route(
        [mill, lathe],
        types=["A"],
    )
    # Repeating the same typed route is allowed.
    model.route(
        [mill, lathe],
        types=["A"],
    )
    with pytest.raises(ValueError, match="different route for type 'A'"):
        model.route(
            [mill, paint],
            types=["A"],
        )
    with pytest.raises(ValueError, match="'Mill' already has a different route\\."):
        model.route([mill, paint])
    with pytest.raises(ValueError, match="'Mill' already has an outgoing route\\."):
        model.branch(
            origin=mill,
            destinations={paint: 1},
        )
    model.branch(
        origin=mill,
        destinations={lathe: 0.5, paint: 0.5},
        types=["B", "C"],
    )
    with pytest.raises(ValueError, match="outgoing route for type 'C'"):
        model.branch(
            origin=mill,
            destinations={paint: 1},
            types=["C"],
        )
    model.route([lathe, paint])
    with pytest.raises(ValueError, match="route for every customer type"):
        model.route(
            [lathe, paint],
            types=["A"],
        )
    assert dict(model.graph["Mill"]["Lathe"]["types"]) == {"A": 1.0, "B": 0.5, "C": 0.5}
    assert dict(model.graph["Mill"]["Paint"]["types"]) == {"B": 0.5, "C": 0.5}
    assert model.graph["Lathe"]["Paint"]["probability"] == 1.0
    assert dict(model.routing["Mill"]) == {
        "A": (("Lathe", 1.0),),
        "B": (("Lathe", 0.5), ("Paint", 0.5)),
        "C": (("Lathe", 0.5), ("Paint", 0.5)),
    }


def test_run_start_checks_name_the_station_and_the_type():
    def build(types, service_time, route_types=None):
        model = Model()
        orders = model.source(
            name="Orders",
            interarrival=1,
            types=types,
        )
        mill = model.station(
            name="Mill",
            capacity=1,
            service_time=service_time,
        )
        model.route([orders, mill])
        model.route(
            [mill, model.exit],
            types=route_types,
        )
        return model

    cases = [
        (
            {"types": {"A": 0.5, "B": 0.5}, "service_time": {"A": 1}},
            "'Mill' has no service time for type 'B', which can reach it from "
            "'Orders'.",
        ),
        (
            {"types": None, "service_time": {"A": 1}},
            "'Mill' sets service times by customer type, and customers from "
            "'Orders' have no type.",
        ),
        (
            {"types": {"A": 0.5, "B": 0.5}, "service_time": 1, "route_types": ["A"]},
            "'Mill' has no route for type 'B', which can reach it from 'Orders'.",
        ),
        (
            {"types": None, "service_time": 1, "route_types": ["A"]},
            "'Mill' routes by customer type, and customers from 'Orders' have no type.",
        ),
    ]
    for settings, message in cases:
        assert run_error(build(**settings)) == message
    # A type that cannot reach a station needs no service time there.
    build(
        types={"A": 1},
        service_time={"A": 1},
        route_types=["A", "B"],
    ).run(duration=5)


def test_type_arguments_are_validated():
    model = Model()
    station = model.station(
        name="Mill",
        capacity=1,
        service_time=1,
    )
    for types, message in [
        ({"A": 0.5, "B": 0.4}, "sum to one"),
        ({"A": 1, "B": 0}, "Probability of type 'B'"),
        ({}, "types must map"),
        ([("A", 1)], "types must map"),
        ({"": 1}, "nonempty names"),
        ({3: 1}, "nonempty names"),
    ]:
        with pytest.raises(ValueError, match=message):
            model.source(
                name="Orders",
                interarrival=1,
                types=types,
            )
    for service_time, message in [
        ({}, "at least one customer type"),
        ({"A": -1}, "Service time for type 'A'"),
        ({None: 1}, "nonempty names"),
    ]:
        with pytest.raises(ValueError, match=message):
            model.station(
                name="Lathe",
                capacity=1,
                service_time=service_time,
            )
    for types, message in [
        ("A", "nonempty list"),
        ([], "nonempty list"),
        (["A", "A"], "type twice"),
    ]:
        with pytest.raises(ValueError, match=message):
            model.route(
                [station, model.exit],
                types=types,
            )


def test_typed_runs_export_types_and_typed_routes(tmp_path):
    result = mill_model().run(
        duration=20,
        drain=True,
    )
    result.export(tmp_path)
    customers = pl.read_csv(tmp_path / "customers.csv")
    visits = pl.read_csv(tmp_path / "visits.csv")
    assert customers.columns[:3] == ["customer_id", "source", "customer_type"]
    assert visits.get_column("customer_type").to_list() == (
        result.visits.get_column("customer_type").to_list()
    )
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["definitions"]["Source A"]["types"] == {"A": 1.0}
    assert metadata["definitions"]["Mill"]["types"] is None
    assert metadata["routes"][:3] == [
        {"from": "Source A", "to": "Mill", "probability": 1.0},
        {"from": "Source B", "to": "Mill", "probability": 1.0},
        {"from": "Mill", "to": "Lathe", "types": {"A": 1.0}},
    ]


def test_typed_models_pool_replications_and_draw_cycles():
    model = job_shop()
    experiment = model.experiment(
        duration=20,
        replications=2,
        drain=True,
    )
    assert experiment.summary.height == 2
    assert layout_layers(model) == [
        ["A orders", "B orders"],
        ["Mill", "Lathe"],
        ["Exit"],
    ]
    figure = model.diagram()
    labels = [annotation.text for annotation in figure.layout.annotations]
    assert sorted(text for text in labels if text) == ["A", "A", "A", "B", "B", "B"]
