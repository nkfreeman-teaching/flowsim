import dataclasses
import json
import math

import numpy as np
import pytest

import flowsim
from flowsim import Model
from flowsim.distributions import Distribution
from flowsim.validation import cumulative_shares, draw_index


def draws(distribution, count=5):
    rng = np.random.default_rng(7)
    return [distribution(rng) for _ in range(count)]


def test_means_and_sds_match_hand_calculations():
    cases = [
        # exponential(mean=4): sd = mean = 4.
        (flowsim.exponential(mean=4), 4, 4),
        # uniform(1, 5): mean (1+5)/2 = 3, sd 4/sqrt(12).
        (flowsim.uniform(low=1, high=5), 3, 4 / math.sqrt(12)),
        # triangular(0, 3, 6): mean 9/3 = 3; (0+9+36-0-0-18)/18 = 1.5.
        (flowsim.triangular(low=0, mode=3, high=6), 3, math.sqrt(1.5)),
        # pert(0, 3, 12): mean (0+12+12)/6 = 4; alpha = 1+4*3/12 = 2,
        # beta = 1+4*9/12 = 4; var = 144 * 8 / (36 * 7) = 32/7.
        (flowsim.pert(low=0, mode=3, high=12), 4, math.sqrt(32 / 7)),
        # normal(10, 2): mean and sd as given.
        (flowsim.normal(mean=10, sd=2), 10, 2),
        # lognormal(4, 2): sigma^2 = ln(1 + 4/16) = ln(1.25); mean and sd are
        # those of the duration itself.
        (flowsim.lognormal(mean=4, sd=2), 4, 2),
        # gamma(2, 3): mean 6, sd sqrt(2) * 3.
        (flowsim.gamma(shape=2, scale=3), 6, 3 * math.sqrt(2)),
        # weibull(shape=1, scale=5) is exponential: mean 5 * Gamma(2) = 5,
        # sd 5 * sqrt(Gamma(3) - 1) = 5.
        (flowsim.weibull(shape=1, scale=5), 5, 5),
        # erlang(k=3, mean=6): sd = 6 / sqrt(3).
        (flowsim.erlang(k=3, mean=6), 6, 6 / math.sqrt(3)),
        # beta(2, 2, low=0, high=4): mean 4 * 2/4 = 2; var 16 * 4/(16*5) = 0.8.
        (flowsim.beta(a=2, b=2, low=0, high=4), 2, math.sqrt(0.8)),
        # empirical([1, 3]): mean 2, population sd 1.
        (flowsim.empirical([1, 3]), 2, 1),
        # poisson(9): mean 9, sd 3.
        (flowsim.poisson(mean=9), 9, 3),
        # discrete([0, 10], [1, 3]): p = 0.25, 0.75; mean 7.5;
        # var 0.25 * 56.25 + 0.75 * 6.25 = 18.75.
        (flowsim.discrete([0, 10], weights=[1, 3]), 7.5, math.sqrt(18.75)),
        # negative_binomial(mean=6, sd=3): mean and sd as given; variance 9
        # exceeds the mean, so n = 36 / (9 - 6) = 12 and p = 6 / 9.
        (flowsim.negative_binomial(mean=6, sd=3), 6, 3),
        # shifted(exponential(mean=4), by=2): mean 4 + 2, sd unchanged at 4.
        (flowsim.shifted(flowsim.exponential(mean=4), by=2), 6, 4),
    ]
    for distribution, mean, sd in cases:
        assert distribution.mean == pytest.approx(mean), distribution
        assert distribution.sd == pytest.approx(sd), distribution
        assert isinstance(distribution, Distribution)
        assert distribution.describe()


def test_draws_equal_the_matching_numpy_calls():
    sigma = math.sqrt(math.log(1.25))
    mu = math.log(4) - sigma**2 / 2
    data = [1.0, 2.0, 5.0]
    cases = [
        (flowsim.exponential(mean=4), lambda r: r.exponential(scale=4)),
        (flowsim.uniform(low=1, high=2), lambda r: r.uniform(low=1, high=2)),
        (
            flowsim.triangular(low=1, mode=2, high=6),
            lambda r: r.triangular(left=1, mode=2, right=6),
        ),
        (
            flowsim.pert(low=0, mode=3, high=12),
            lambda r: 0 + 12 * r.beta(a=2, b=4),
        ),
        (flowsim.normal(mean=10, sd=2), lambda r: r.normal(loc=10, scale=2)),
        (
            flowsim.lognormal(mean=4, sd=2),
            lambda r: r.lognormal(mean=mu, sigma=sigma),
        ),
        (flowsim.gamma(shape=2, scale=3), lambda r: r.gamma(shape=2, scale=3)),
        (flowsim.weibull(shape=1.5, scale=10), lambda r: 10 * r.weibull(a=1.5)),
        (flowsim.erlang(k=3, mean=6), lambda r: r.gamma(shape=3, scale=2)),
        (
            flowsim.beta(a=2, b=5, low=1, high=4),
            lambda r: 1 + 3 * r.beta(a=2, b=5),
        ),
        (flowsim.empirical(data), lambda r: data[r.integers(3)]),
        (flowsim.poisson(mean=6), lambda r: float(r.poisson(lam=6))),
        (
            flowsim.discrete([1, 2, 5], weights=[2, 2, 1]),
            lambda r: [1.0, 2.0, 5.0][r.choice(3, p=[0.4, 0.4, 0.2])],
        ),
        (
            flowsim.negative_binomial(mean=6, sd=3),
            lambda r: float(r.negative_binomial(n=12, p=6 / 9)),
        ),
        (
            flowsim.shifted(flowsim.exponential(mean=4), by=2),
            lambda r: 2 + r.exponential(scale=4),
        ),
    ]
    for distribution, by_hand in cases:
        rng = np.random.default_rng(7)
        expected = [by_hand(rng) for _ in range(5)]
        got = draws(distribution)
        assert got == expected, distribution
        assert all(type(value) is float for value in got), distribution


def timed_model(service_time):
    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=lambda rng: rng.exponential(scale=3),
        limit=20,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=service_time,
    )
    model.route([arrivals, desk, model.exit])
    return model


def test_named_distribution_matches_the_hand_written_lambda_under_one_seed():
    named = timed_model(flowsim.exponential(mean=4)).run(
        duration=100,
        seed=3,
        drain=True,
    )
    by_hand = timed_model(lambda rng: rng.exponential(scale=4)).run(
        duration=100,
        seed=3,
        drain=True,
    )
    assert named.customers.equals(by_hand.customers)
    assert named.customers.height == 20


def test_empirical_and_discrete_draw_only_listed_values():
    data = [0.5, 2.0, 7.0]
    assert set(draws(flowsim.empirical(data), 200)) <= set(data)
    assert set(draws(flowsim.discrete([1, 2, 3]), 200)) <= {1.0, 2.0, 3.0}
    assert set(draws(flowsim.discrete([4, 9], weights=[0, 1]), 50)) == {9.0}


def test_repr_and_describe():
    assert repr(flowsim.exponential(mean=4)) == "Exponential(mean=4)"
    assert repr(flowsim.uniform(low=1, high=2)) == "Uniform(low=1, high=2)"
    assert repr(flowsim.gamma(shape=2, scale=3)) == "Gamma(shape=2, scale=3)"
    assert repr(flowsim.erlang(k=3, mean=6)) == "Erlang(k=3, mean=6)"
    assert repr(flowsim.negative_binomial(mean=20, sd=8)) == (
        "NegativeBinomial(mean=20, sd=8)"
    )
    assert repr(flowsim.shifted(flowsim.exponential(mean=4), by=2)) == (
        "Shifted(Exponential(mean=4), by=2)"
    )
    assert "negative" in flowsim.shifted(flowsim.exponential(mean=4), by=-1).describe()
    assert repr(flowsim.empirical([1, 2, 6])) == (
        "Empirical(n=3, mean=3, min=1, max=6)"
    )
    assert flowsim.exponential(mean=4).describe() == (
        "Exponential with mean 4: memoryless gaps, as for random arrivals."
    )
    # Phi(-0.5) = 0.3085 chance of a negative draw.
    assert "0.309" in flowsim.normal(mean=1, sd=2).describe()
    assert "negative" not in flowsim.normal(mean=100, sd=1).describe()


def test_bad_parameters_name_the_constructor():
    bad_calls = [
        ("exponential", lambda: flowsim.exponential(mean=-1)),
        ("uniform", lambda: flowsim.uniform(low=2, high=1)),
        ("triangular", lambda: flowsim.triangular(low=1, mode=0, high=2)),
        ("pert", lambda: flowsim.pert(low=1, mode=5, high=2)),
        ("normal", lambda: flowsim.normal(mean=1, sd=0)),
        ("lognormal", lambda: flowsim.lognormal(mean=0, sd=1)),
        ("gamma", lambda: flowsim.gamma(shape=0, scale=1)),
        ("weibull", lambda: flowsim.weibull(shape=1, scale=-1)),
        ("erlang", lambda: flowsim.erlang(k=2.5, mean=1)),
        ("erlang", lambda: flowsim.erlang(k=True, mean=1)),
        ("beta", lambda: flowsim.beta(a=1, b=1, low=-1, high=1)),
        ("empirical", lambda: flowsim.empirical([])),
        ("empirical", lambda: flowsim.empirical([1, -2])),
        ("poisson", lambda: flowsim.poisson(mean=float("nan"))),
        ("discrete", lambda: flowsim.discrete([1, 2], weights=[0, 0])),
        ("discrete", lambda: flowsim.discrete([1, 2], weights=[1])),
        # sd**2 = 4 equals the mean, which is Poisson, not negative binomial.
        ("negative_binomial", lambda: flowsim.negative_binomial(mean=4, sd=2)),
        ("shifted", lambda: flowsim.shifted(lambda rng: 1.0, by=1)),
        ("shifted", lambda: flowsim.shifted(flowsim.poisson(mean=2), by=None)),
    ]
    for name, call in bad_calls:
        with pytest.raises(ValueError, match=f"^{name} needs"):
            call()
    with pytest.raises(ValueError, match=r"e\.g\. exponential\(mean=4\), not mean=-1"):
        flowsim.exponential(mean=-1)
    with pytest.raises(TypeError):
        flowsim.exponential(4)


def test_wrong_sampler_shapes_fail_clearly():
    with pytest.raises(ValueError, match="function of one argument"):
        timed_model(lambda: 2)
    with pytest.raises(ValueError, match="drop size="):
        timed_model(lambda rng: rng.exponential(scale=2, size=1)).run(
            duration=10,
            seed=1,
        )


def test_distributions_are_frozen():
    distribution = flowsim.exponential(mean=4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        distribution.mean = 5


def test_export_metadata_records_distributions(tmp_path):
    named = timed_model(flowsim.exponential(mean=4)).run(
        duration=20,
        seed=1,
    )
    named.export(tmp_path / "named")
    metadata = json.loads((tmp_path / "named" / "metadata.json").read_text())
    desk = metadata["definitions"]["Desk"]
    assert desk["service_time"] == {"name": "exponential", "mean": 4.0}
    assert desk["reconstructible"] is True
    # The source's interarrival is a lambda, so only that node is flagged.
    assert metadata["definitions"]["Customers"]["interarrival"] == "<function>"
    assert metadata["definitions"]["Customers"]["reconstructible"] is False

    model = Model()
    arrivals = model.source(
        name="Customers",
        interarrival=flowsim.exponential(mean=3),
        limit=5,
    )
    desk = model.station(
        name="Desk",
        capacity=1,
        service_time=flowsim.exponential(mean=4),
    )
    model.route([arrivals, desk, model.exit])
    model.run(
        duration=20,
        seed=1,
    ).export(tmp_path / "pure")
    definitions = json.loads((tmp_path / "pure" / "metadata.json").read_text())[
        "definitions"
    ]
    assert definitions["Desk"]["service_time"] == {"name": "exponential", "mean": 4.0}
    assert definitions["Desk"]["reconstructible"] is True
    assert definitions["Customers"]["interarrival"] == {
        "name": "exponential",
        "mean": 3.0,
    }
    assert definitions["Customers"]["limit"] == 5

    lam = timed_model(lambda rng: rng.exponential(scale=4)).run(
        duration=20,
        seed=1,
    )
    assert lam._definitions["Desk"]["service_time"] == "<function>"
    assert lam._definitions["Desk"]["reconstructible"] is False


@pytest.mark.parametrize(
    "distribution",
    [
        flowsim.exponential(mean=4.123456789),
        flowsim.uniform(low=1, high=2),
        flowsim.triangular(low=1, mode=2, high=6),
        flowsim.pert(low=1, mode=2, high=6),
        flowsim.normal(mean=10, sd=2),
        flowsim.lognormal(mean=4, sd=2),
        flowsim.gamma(shape=2, scale=3),
        flowsim.weibull(shape=1.5, scale=10),
        flowsim.erlang(k=3, mean=6),
        flowsim.beta(a=2, b=5, low=1, high=4),
        flowsim.empirical([0, 1, 3, 4]),
        flowsim.poisson(mean=20),
        flowsim.discrete([1, 2, 5], weights=[2, 2, 1]),
        flowsim.negative_binomial(mean=20, sd=8),
        flowsim.shifted(flowsim.gamma(shape=2, scale=3), by=1.5),
        flowsim.shifted(flowsim.discrete([1, 2], weights=[1, 3]), by=-0.25),
    ],
)
def test_spec_rebuilds_the_same_distribution_through_json(distribution):
    spec = json.loads(json.dumps(distribution.spec()))
    name = spec.pop("name")
    assert getattr(flowsim, name)(**spec) == distribution


def test_specs_keep_what_reprs_round_away():
    # Same n, mean, min, and max, so the reprs match, but different data.
    first = flowsim.empirical([0, 1, 3, 4])
    second = flowsim.empirical([0, 2, 2, 4])
    assert repr(first) == repr(second)
    assert first.spec() != second.spec()


def test_triangular_sd_survives_a_large_shift():
    # The sd of triangular(0, 1, 2) is sqrt((0 + 1 + 4 - 0 - 0 - 2) / 18)
    # = sqrt(1/6), and shifting every point leaves it unchanged.
    shifted = flowsim.triangular(low=1e8, mode=1e8 + 1, high=1e8 + 2)
    assert shifted.sd == pytest.approx(math.sqrt(1 / 6))


def test_lognormal_keeps_a_small_coefficient_of_variation():
    # A draw passes the generator the sigma of the duration's logarithm, so a
    # generator that records it checks the conversion through the public call.
    class Recorder:
        def lognormal(self, mean, sigma):
            self.sigma = sigma
            return 1.0

    # sd / mean = 1e-9, so sigma^2 = log1p(1e-18), i.e., sigma is about 1e-9.
    # Computed as log(1 + 1e-18), sigma would be 0 and every draw identical.
    rng = Recorder()
    flowsim.lognormal(mean=1, sd=1e-9)(rng)
    assert rng.sigma == pytest.approx(1e-9)
    # sd / mean = 1, so sigma = sqrt(log 2), however small the scale.
    flowsim.lognormal(mean=1e-200, sd=1e-200)(rng)
    assert rng.sigma == pytest.approx(math.sqrt(math.log(2)))


def test_huge_equal_weights_normalize_to_equal_probabilities():
    assert flowsim.discrete([1, 2], weights=[1e308, 1e308]).probabilities == (
        0.5,
        0.5,
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda: flowsim.empirical([True, False, True]),
        lambda: flowsim.empirical([1.0, True]),
        lambda: flowsim.discrete([True, False]),
        lambda: flowsim.discrete([1, 2], weights=np.array([True, False])),
    ],
)
def test_booleans_are_not_numbers_for_sequence_constructors(build):
    with pytest.raises(ValueError, match="not True or False"):
        build()


def test_a_shift_of_a_custom_distribution_exports_as_a_function(tmp_path):
    class Constant(Distribution):
        mean = 1.0
        sd = 0.0

        def __call__(self, rng):
            return 1.0

        def describe(self):
            return "Always one."

    spec = timed_model(flowsim.shifted(Constant(), by=1)).run(
        duration=20,
        seed=1,
    )
    assert spec._definitions["Desk"]["service_time"] == "<function>"
    assert spec._definitions["Desk"]["reconstructible"] is False


@pytest.mark.parametrize(
    ("shape", "sd"),
    [
        # Rayleigh: sd = scale * sqrt(1 - pi / 4).
        (2, 10 * math.sqrt(1 - math.pi / 4)),
        # Gamma(5) - Gamma(3)^2 = 24 - 4, so sd = 10 * sqrt(20).
        (0.5, 10 * math.sqrt(20)),
        # A large shape approaches sd = scale * pi / (sqrt(6) * shape), where
        # subtracting the two gamma values gave a negative variance.
        (1e8, 10 * math.pi / (math.sqrt(6) * 1e8)),
        # x = 1e-170, so x^2 underflows; the sd once came out as zero.
        (1e170, 10 * math.pi / (math.sqrt(6) * 1e170)),
    ],
)
def test_weibull_sd_matches_hand_values(shape, sd):
    assert flowsim.weibull(shape=shape, scale=10).sd == pytest.approx(sd, rel=1e-7)


@pytest.mark.parametrize(
    "probabilities",
    [
        [0.5, 0.5],
        [0.3, 0.7],
        [0.1, 0.2, 0.3, 0.4],
        [1 / 3, 1 / 3, 1 / 3],
        [1e-9, 0.5, 0.5 - 1e-9],
    ],
)
def test_draw_index_gives_the_index_that_numpy_choice_gives(probabilities):
    # Routing, type, and discrete draws search cumulative shares instead of
    # calling Generator.choice. A NumPy release that changes choice fails here
    # before it changes a seeded run.
    shares = cumulative_shares(probabilities)
    ours = np.random.default_rng(11)
    theirs = np.random.default_rng(11)
    for _ in range(2000):
        assert draw_index(shares, ours) == theirs.choice(
            len(probabilities),
            p=probabilities,
        )
    assert ours.random() == theirs.random()


def test_distribution_cv_scv_sample_and_from_scv():
    dist = flowsim.gamma(
        shape=4,
        scale=1.5,
    )
    assert dist.cv == pytest.approx(0.5)
    assert dist.scv == pytest.approx(0.25)
    assert flowsim.from_scv(mean=6, scv=0.25) == dist
    assert flowsim.from_scv(mean=6, scv=0) == 6.0
    assert isinstance(flowsim.from_scv(mean=6, scv=0), float)
    one = dist.sample(seed=7)
    assert isinstance(one, float)
    arr = dist.sample(5, seed=7)
    assert isinstance(arr, np.ndarray)
    assert arr.shape == (5,)
    assert arr[0] == one
    grid = dist.sample((2, 3), seed=7)
    assert grid.shape == (2, 3)
    with pytest.raises(ValueError, match="not both"):
        dist.sample(
            2,
            seed=1,
            rng=np.random.default_rng(1),
        )
    with pytest.raises(ValueError, match="from_scv"):
        flowsim.from_scv(mean=4, scv=-0.1)
