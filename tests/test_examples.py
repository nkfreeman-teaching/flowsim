"""Check that the teaching examples run and keep their stated rules."""

import numpy as np
import polars as pl
import pytest

from examples import extensions, models
from examples.service_day import staffing_exercise


@pytest.mark.parametrize(
    "build",
    [
        models.deterministic_queue,
        models.service_network,
        models.branching_service,
        extensions.peak_service,
        extensions.buffered_line,
        extensions.repairing_machine,
        extensions.combined_line,
    ],
)
def test_example_models_run(build):
    result = build().run(
        duration=60,
        seed=1,
        drain=True,
    )
    assert result.summary.get_column("remaining").item() == 0


def test_worked_exercise_preserves_customer_accounting_and_target_rule():
    comparison, decision = staffing_exercise(replications=3)
    assert decision.height == 3
    for row in decision.to_dicts():
        runs = comparison.experiments[row["scenario"]].summary
        qualifying = runs.filter(pl.col("overtime") <= 30).height
        assert row["days_finished_on_time"] == qualifying
        assert row["meets_targets"] == (
            row["mean_wait_minutes"] <= 5 and qualifying >= 3
        )
        assert runs.get_column("remaining").to_list() == [0, 0, 0]
        assert np.all(
            runs.get_column("arrivals").to_numpy()
            == runs.get_column("completed").to_numpy()
        )
