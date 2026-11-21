"""Distribution fitting checked against hand-calculated fits, AIC, and KS."""

import json
import math
import warnings

import numpy as np
import plotly.graph_objects as go
import polars as pl
import pytest
import scipy.stats as st

import flowsim
from flowsim import FAMILIES, Fit, Model, best_fit, fit_all
from flowsim.distributions import exponential, normal, poisson

# The README example's data.
README_DATA = np.random.default_rng(7).gamma(
    shape=4,
    scale=1.5,
    size=200,
)


def test_uniform_fit_and_ks_match_a_hand_calculation():
    # The uniform MLE spans the sample, so loc = 2 and scale = 10 - 2 = 8, i.e.,
    # low = 2 and high = 10. The CDF at 2, 3, 5, 10 is 0, 1/8, 3/8, 1 against
    # empirical steps of 1/4, 1/2, 3/4, 1, so the largest gap is
    # 1/2 - 1/8 = 3/4 - 3/8 = 3/8.
    fits = fit_all(
        data=[2.0, 3.0, 5.0, 10.0],
        families=["uniform"],
    )
    fit = fits.best
    assert fit.family == "uniform"
    assert fit.params == pytest.approx({"low": 2, "high": 10})
    assert fit.ks == pytest.approx(0.375)
    row = fits.table.row(0, named=True)
    assert (row["rank"], row["low"], row["high"]) == (1, 2, 10)


def test_exponential_fit_matches_a_hand_calculation():
    # At location zero the exponential MLE mean is the sample mean, 12 / 4 = 3.
    # The log-likelihood is -n ln(3) - sum(x) / 3 = -4 ln(3) - 4, and one fitted
    # parameter gives AIC = 2 - 2 (-4 ln 3 - 4) = 2 + 8 ln 3 + 8. The CDF
    # 1 - exp(-x/3) at 1, 2, 3, 6 is 0.283, 0.487, 0.632, 0.865 against steps
    # of 1/4 to 1, so the largest gap is 1 - exp(-1/3) - 0 at x = 1.
    fit = fit_all(
        data=[1.0, 2.0, 3.0, 6.0],
        families=["exponential"],
    ).best
    assert fit.distribution == exponential(mean=3)
    assert fit.params == pytest.approx({"mean": 3})
    assert fit.aic == pytest.approx(2 + 8 * math.log(3) + 8)
    assert fit.ks == pytest.approx(1 - math.exp(-1 / 3))
    assert fit.p_negative == 0


def test_poisson_fit_matches_a_hand_calculation():
    # The Poisson MLE mean is the sample mean, 8 / 4 = 2. The log-likelihood is
    # sum(x ln 2 - 2 - ln x!) = 8 ln 2 - 8 - ln(0! 1! 2! 5!) = 8 ln 2 - 8 - ln 240,
    # so AIC = 2 - 16 ln 2 + 16 + 2 ln 240.
    fits = fit_all(
        data=[0, 1, 2, 5],
        families=["poisson"],
        discrete=True,
    )
    fit = fits.best
    assert fit.distribution == poisson(mean=2)
    assert fit.aic == pytest.approx(2 - 16 * math.log(2) + 16 + 2 * math.log(240))
    assert fit.ks is None
    assert fits.table["ks"].to_list() == [None]


def test_aic_counts_only_free_parameters_and_sets_the_rank():
    fits = fit_all(README_DATA)
    table = fits.table
    assert table.columns == [
        "rank",
        "family",
        "description",
        "mean",
        "sd",
        "p_negative",
        "aic",
        "ks",
        "shape",
        "scale",
    ]
    assert set(table["family"]) == set(FAMILIES)
    assert table["rank"].to_list() == [1, 2, 3, 4, 5]
    assert table["aic"].is_sorted()
    # Gamma at location zero fits shape and scale, so k = 2.
    params = st.gamma.fit(README_DATA, floc=0)
    loglik = st.gamma.logpdf(README_DATA, *params).sum()
    gamma_fit = fits.pick("gamma")
    assert gamma_fit.aic == pytest.approx(2 * 2 - 2 * loglik)
    assert gamma_fit.params == pytest.approx({"shape": params[0], "scale": params[2]})
    assert gamma_fit.ks == pytest.approx(
        st.kstest(README_DATA, st.gamma(*params).cdf).statistic
    )
    assert fits.table.equals(fit_all(pl.Series(README_DATA)).table)


def test_the_readme_example_winner_cannot_draw_a_negative_value():
    fits = fit_all(README_DATA)
    assert fits.best.family == "gamma"
    assert fits.best.p_negative <= 1e-6
    # Every family fitted at location zero has no mass below zero.
    for fit in fits:
        if fit.family != "normal":
            assert fit.p_negative == 0
    # With a free location, the lognormal starts below zero, so best skips it.
    shifted = fit_all(
        README_DATA,
        shifted=True,
    )
    lognormal = shifted.pick("lognormal")
    assert lognormal.params["by"] < 0
    assert lognormal.p_negative > 1e-6
    assert shifted.best.family != "lognormal"
    assert shifted.best.p_negative <= 1e-6


def test_best_skips_a_normal_fit_that_can_draw_negative_values():
    # Normal data with mean 3 and sd 1: the normal ranks first by AIC, but a
    # draw falls below zero with chance near Phi(-3) = 0.0013.
    data = np.random.default_rng(1).normal(
        loc=3,
        scale=1,
        size=100,
    )
    fits = fit_all(data)
    first = fits.pick(1)
    assert first.family == "normal"
    assert first.p_negative > 1e-6
    assert fits.best is fits.pick(2)
    with pytest.raises(ValueError, match=r"empirical\(data\)"):
        best_fit(
            data,
            families=["normal"],
        )


@pytest.mark.parametrize(
    ("family", "draw", "size", "minimum"),
    [
        # Measured: 33 of 40 seeds pick gamma, 31 of 40 pick exponential.
        ("gamma", lambda rng, n: rng.gamma(shape=4, scale=1.5, size=n), 200, 25),
        ("exponential", lambda rng, n: rng.exponential(scale=2, size=n), 100, 25),
    ],
)
def test_seeded_samples_recover_their_family(family, draw, size, minimum):
    wins = sum(
        best_fit(draw(np.random.default_rng(seed), size)).family == family
        for seed in range(40)
    )
    assert wins >= minimum


def test_a_family_whose_fit_fails_is_reported(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("bad start")

    monkeypatch.setattr(st.expon, "fit", fail)
    fits = fit_all(
        data=[1.0, 2.0, 4.0, 7.0],
        families=["exponential", "uniform"],
    )
    assert [fit.family for fit in fits] == ["uniform"]
    assert fits.failed.rows() == [("exponential", "RuntimeError: bad start")]
    assert "Did not fit: exponential (RuntimeError: bad start)" in repr(fits)
    with pytest.raises(ValueError, match="No family.*bad start"):
        fit_all(
            data=[1.0, 2.0, 4.0, 7.0],
            families=["exponential"],
        )


def test_a_programming_error_in_a_family_fit_is_raised(monkeypatch):
    # Only errors a fit raises on bad data mark a family as failed, so a bug
    # such as a wrong argument type is not hidden in the failed list.
    def broken(*args, **kwargs):
        raise TypeError("unexpected keyword")

    monkeypatch.setattr(st.expon, "fit", broken)
    with pytest.raises(TypeError, match="unexpected keyword"):
        fit_all(
            data=[1.0, 2.0, 4.0, 7.0],
            families=["exponential", "uniform"],
        )


@pytest.mark.parametrize(
    "data",
    [
        ["1.5", "2.5", "4"],
        [True, False, True],
        pl.Series(["1.5", "2.5", "4"]),
        pl.Series([True, False, True]),
        [1.5, "2.5", 4.0],
        [True, 2.0, 4.0],
        (1.5, np.True_, 4.0),
    ],
)
def test_text_and_boolean_fitting_data_is_refused(data):
    with pytest.raises(ValueError, match="not text or booleans"):
        fit_all(data)


@pytest.mark.parametrize(
    "data",
    [
        [[1.0, 2.0], [3.0]],
        [1.0, {"a": 1}, 3.0],
    ],
)
def test_fitting_data_that_is_not_a_flat_sequence_of_numbers_is_refused(data):
    # NumPy cannot form an array from ragged lists, and a dict is not a number.
    with pytest.raises(ValueError, match="must be a sequence of numbers"):
        fit_all(data)


def test_zero_values_warn_and_fail_the_families_that_start_at_zero():
    with pytest.warns(
        UserWarning,
        match=r"values look rounded; record finer times or use empirical\(data\)",
    ):
        fits = fit_all([0.0, 1.2, 2.5, 3.1, 4.7, 0.8])
    failed = dict(fits.failed.rows())
    assert set(failed) == {"gamma", "lognormal", "weibull"}
    assert all("zero" in reason for reason in failed.values())
    assert [fit.family for fit in fits] == ["exponential", "normal"]
    with pytest.raises(ValueError, match="lognormal did not fit"):
        fits.pick("lognormal")


def test_ties_warn_but_distinct_values_do_not():
    # Two of ten values (20%) equal another value.
    with pytest.warns(UserWarning, match="values look rounded"):
        fit_all([1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fit_all(README_DATA)


@pytest.mark.parametrize("fitter", [fit_all, best_fit])
def test_the_rounding_warning_points_at_the_calling_line(fitter):
    with pytest.warns(UserWarning, match="values look rounded") as caught:
        fitter([1.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])
    assert caught[0].filename == __file__


def test_pick_by_name_and_rank():
    fits = fit_all(README_DATA)
    assert len(fits) == 5
    assert fits.pick("gamma") is fits.best
    assert fits.pick(1) is fits.best
    assert list(fits)[1] is fits.pick(2)
    assert best_fit(README_DATA).distribution == fits.best.distribution
    assert isinstance(fits.best, Fit)
    with pytest.raises(ValueError, match="No fit named 'beta'.*gamma, lognormal"):
        fits.pick("beta")
    for bad in (0, 6, True, 1.0):
        with pytest.raises(ValueError, match="rank from 1 to 5"):
            fits.pick(bad)


def test_fits_display_without_refitting():
    fits = fit_all(README_DATA)
    text = repr(fits)
    assert text.startswith("Fits to 200 durations: mean 5.509")
    assert "Gamma(shape=4.39, scale=1.26)" in text
    assert "(skipped by .best)" in text
    assert "fits.pick(" in text
    assert "<table>" in fits._repr_html_()
    assert repr(fits.best) == "Gamma(shape=4.39, scale=1.26)  AIC=926.3  KS=0.053"
    figure = fits.plot()
    assert isinstance(figure, go.Figure)
    # Data histogram and empirical CDF, plus a density and a CDF per fit.
    assert len(figure.data) == 2 + 2 * len(fits)


def run_with(service_time, seed=8):
    model = Model()
    source = model.source(
        name="Jobs",
        interarrival=lambda rng: rng.exponential(scale=6),
        limit=30,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=service_time,
    )
    model.route([source, station, model.exit])
    return model.run(
        duration=300,
        seed=seed,
        drain=True,
    )


@pytest.mark.parametrize("shifted", [False, True])
def test_a_fit_drives_a_station_exactly_like_its_distribution(shifted, tmp_path):
    fit = best_fit(
        README_DATA,
        shifted=shifted,
    )
    fitted = run_with(fit)
    assert fitted.visits.height == 30
    assert fitted.visits.equals(run_with(fit.distribution).visits)
    assert not fitted.visits.equals(run_with(fit, seed=9).visits)
    fitted.export(tmp_path)
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    machine = metadata["definitions"]["Machine"]
    assert machine["service_time"] == fit.distribution.spec()
    assert machine["reconstructible"] is True
    spec = dict(machine["service_time"])
    assert getattr(flowsim, spec.pop("name"))(**spec) == fit.distribution


def test_counts_recover_poisson_and_prefer_negative_binomial_when_overdispersed():
    # Measured: Poisson data pick Poisson in 39 of 40 seeds, and negative
    # binomial data with variance 18 > mean 6 pick it in 40 of 40.
    poisson_wins = sum(
        fit_all(
            np.random.default_rng(seed).poisson(lam=6, size=100),
            discrete=True,
        ).best.family
        == "poisson"
        for seed in range(40)
    )
    assert poisson_wins >= 30
    counts = np.random.default_rng(1).negative_binomial(
        n=3,
        p=0.4,
        size=300,
    )
    fits = fit_all(
        counts,
        discrete=True,
    )
    assert fits.best.family == "negative_binomial"
    # The negative binomial MLE also sets the mean to the sample mean.
    assert fits.best.mean == pytest.approx(counts.mean())
    assert fits.best.sd**2 > fits.best.mean
    assert "Fits to 300 counts" in repr(fits)


def test_counts_without_extra_variance_report_the_negative_binomial_as_failed():
    # Mean 4 and variance 4/7 (dividing by n), so there is no overdispersion.
    fits = fit_all(
        [3, 4, 5, 4, 3, 5, 4],
        discrete=True,
    )
    assert [fit.family for fit in fits] == ["poisson"]
    ((family, reason),) = fits.failed.rows()
    assert family == "negative_binomial"
    assert "not above their mean" in reason


@pytest.mark.parametrize(
    "data",
    [[1.0], [1.0, float("nan")], [[1.0, 2.0], [3.0, 4.0]], [1.0, -2.0], ["a", "b"]],
)
def test_fitting_data_is_validated(data):
    with pytest.raises(ValueError, match="Fitting data"):
        fit_all(data)


def test_count_data_must_be_whole_numbers():
    with pytest.raises(ValueError, match="whole-number counts"):
        fit_all(
            [1.5, 2.0],
            discrete=True,
        )
    with pytest.raises(ValueError, match="shifted=True"):
        fit_all(
            [1, 2],
            shifted=True,
            discrete=True,
        )


@pytest.mark.parametrize(
    ("families", "message"),
    [
        ("normal", r'a list of family names, e\.g\. \["normal"\], not one string'),
        ([], "must name at least one distribution"),
        (["normal", "poisson"], r"Unknown families \['poisson'\].*discrete=True"),
        (["not_a_family"], r"Unknown families \['not_a_family'\] for durations"),
        (["norm"], r"Unknown families \['norm'\] for durations"),
    ],
)
def test_family_names_are_validated(families, message):
    with pytest.raises(ValueError, match=message):
        fit_all(
            data=[1.0, 2.0, 3.0],
            families=families,
        )


def test_count_family_names_are_validated():
    with pytest.raises(ValueError, match="Unknown families.*counts"):
        fit_all(
            data=[1, 2, 3],
            families=["gamma"],
            discrete=True,
        )


def test_a_negative_draw_stops_the_run():
    model = Model()
    source = model.source(
        name="Jobs",
        interarrival=10,
        first_arrival=0,
        limit=1,
    )
    station = model.station(
        name="Machine",
        capacity=1,
        service_time=normal(
            mean=-5,
            sd=0.001,
        ),
    )
    model.route([source, station, model.exit])
    with pytest.raises(ValueError, match="at least zero"):
        model.run(
            duration=30,
            seed=1,
        )


def test_free_endpoint_fits_below_zero_are_kept_as_shifted_distributions():
    # Seed 1 exponential data give a triangular fit whose start is below zero.
    data = np.random.default_rng(1).exponential(
        scale=2,
        size=100,
    )
    fits = fit_all(
        data,
        families=["triangular", "beta", "uniform"],
    )
    assert fits.failed.height == 0
    triangle = fits.pick("triangular")
    assert triangle.params["by"] < 0
    # The shifted fit is the same distribution SciPy fitted, so their means,
    # sds, and chances of a negative draw agree.
    assert triangle.mean == pytest.approx(triangle._frozen.mean())
    assert triangle.sd == pytest.approx(triangle._frozen.std())
    assert triangle.p_negative == pytest.approx(triangle._frozen.cdf(0))
    assert triangle.p_negative > 0


def test_negative_binomial_matches_a_direct_likelihood_maximization():
    counts = (
        np.random.default_rng(1)
        .negative_binomial(
            n=5,
            p=5 / 55,
            size=200,
        )
        .astype(float)
    )
    fit = fit_all(
        counts,
        discrete=True,
    ).pick("negative_binomial")
    mean = counts.mean()

    def loglik(size):
        return st.nbinom.logpmf(counts, size, size / (size + mean)).sum()

    # The fitted size r gives variance mean + mean^2 / r, and a small step
    # either way lowers the log-likelihood.
    size = mean**2 / (fit.sd**2 - mean)
    best = loglik(size)
    assert fit.aic == pytest.approx(4 - 2 * best)
    assert best >= loglik(size * 1.001)
    assert best >= loglik(size / 1.001)


def test_count_plot_grid_stays_bounded_for_huge_counts():
    figure = fit_all(
        [100_000_000.0, 100_000_003.0, 100_000_010.0],
        discrete=True,
    ).plot()
    assert max(len(trace.x) for trace in figure.data) <= 1000


def test_shifted_fits_pinned_at_the_smallest_observation_fail():
    # A free location makes the lognormal and Weibull likelihoods grow without
    # bound as the location reaches 1, so those fits are listed as failed. The
    # shifted exponential's maximum is location 1 and scale mean - 1 = 1.5, so
    # its log-likelihood is -4 ln 1.5 - 6 / 1.5 and its AIC is 4 minus twice
    # that, 15.2437, below normal's 16.24 and gamma's 18.24.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fits = fit_all([1, 2, 3, 4], shifted=True)
    failed = dict(fits.failed.iter_rows())
    assert set(failed) == {"lognormal", "weibull"}
    assert all("smallest observation" in reason for reason in failed.values())
    assert fits.best.family == "exponential"
    assert fits.best.aic == pytest.approx(4 + 2 * (4 * math.log(1.5) + 4))
    assert fits.best.mean == pytest.approx(2.5)


def test_constant_durations_give_a_fits_table():
    # Equal values push the Weibull shape to about 3e9, whose sd once failed.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = fit_all([1.0, 1.0, 1.0]).table
    assert table.get_column("sd").is_finite().all()


def test_constant_durations_with_shifted_fail_cleanly():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ValueError, match="No family produced a valid fit"):
            fit_all([1.0, 1.0, 1.0], shifted=True)


def test_continuous_fit_plot_concentrates_grid_on_offset_data():
    figure = fit_all([1000.0, 1001.0, 1002.0, 1003.0, 1001.5]).plot()
    pdf_trace = figure.data[1]
    in_range = sum(999.0 <= x <= 1004.0 for x in pdf_trace.x)
    assert in_range > 200
