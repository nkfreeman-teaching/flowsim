"""A saturated machining line and a truck cross-dock, each with a scenario study."""

from pathlib import Path

from flowsim import Model, compare

# Machining line buffer plans, as waiting spaces in front of CNC, Wash,
# Assembly, and Pack. The last two plans hold the same eight spaces in different
# places.
BUFFER_PLANS = {
    "No buffers": (0, 0, 0, 0),
    "Two each": (2, 2, 2, 2),
    "Five before Assembly": (1, 1, 5, 1),
}
SHIFT = 480  # minutes in one production shift
DOCK_DAY = 960  # minutes of truck arrivals at the cross-dock
REPLICATIONS = 20


def machining_line(
    buffers: tuple[int, int, int, int] = (2, 2, 2, 2),
    failures: bool = True,
) -> Model:
    """Saw, two CNC machines, Wash, Assembly, and Pack in series.

    Blanks are released every 2 minutes, faster than the line can work, and
    wait outside the Saw as raw stock. The Saw has no waiting room, so the
    line always has work and its output measures capacity. The CNC machines
    fail while cutting, and Assembly drops to one fitter for lunch.
    """
    model = Model(time_unit="minutes")
    blanks = model.source(
        name="Blanks",
        interarrival=2,
        first_arrival=0,
    )
    saw = model.station(
        name="Saw",
        capacity=1,
        service_time=lambda rng: rng.uniform(2.5, 3.5),
        buffer=0,
        external_overflow="wait",
    )
    # Source overflow rules apply only to the first station, but every finite
    # buffer requires one, so the later stations state "reject".
    breakdowns = (
        {
            "time_to_failure": lambda rng: rng.exponential(scale=90),
            "repair_time": lambda rng: rng.uniform(10, 30),
            "failure_clock": "busy",
        }
        if failures
        else {}
    )
    cnc = model.station(
        name="CNC",
        capacity=2,
        service_time=lambda rng: rng.gamma(
            shape=4,
            scale=1.5,
        ),
        buffer=buffers[0],
        external_overflow="reject",
        **breakdowns,
    )
    wash = model.station(
        name="Wash",
        capacity=1,
        service_time=2.5,
        buffer=buffers[1],
        external_overflow="reject",
    )
    assembly = model.station(
        name="Assembly",
        capacity=2,
        service_time=lambda rng: rng.uniform(5, 8),
        staffing=[(0, 2), (240, 1), (300, 2)],
        shift_end="finish",
        buffer=buffers[2],
        external_overflow="reject",
    )
    pack = model.station(
        name="Pack",
        capacity=1,
        service_time=lambda rng: rng.uniform(2.5, 3.5),
        buffer=buffers[3],
        external_overflow="reject",
    )
    model.route([blanks, saw, cnc, wash, assembly, pack, model.exit])
    return model


def cross_dock(doors: int = 6, yard: int = 8) -> Model:
    """Inbound trucks pass a gate, wait in a yard, unload, and are sorted.

    A full yard holds trucks at the gate, and a busy gate leaves trucks queued
    on the access road. Door crews follow a shift plan, and the sorter fails
    while running. Three quarters of loads go straight to outbound trailers,
    and the rest go to storage. Each truckload stays one job, since FlowSim
    cannot split a load into pallets.
    """
    model = Model(time_unit="minutes")
    trucks = model.source(
        name="Inbound trucks",
        rates=[(0, 1 / 15), (120, 1 / 6), (480, 1 / 10), (720, 1 / 30)],
    )
    gate = model.station(
        name="Gate",
        capacity=2,
        service_time=lambda rng: rng.uniform(2, 5),
        buffer=0,
        external_overflow="wait",
    )
    # Two door crews go home outside the peak, but one always stays, so a
    # drained day can finish.
    off_peak = max(doors - 2, 1)
    unload = model.station(
        name="Unload",
        capacity=doors,
        service_time=lambda rng: rng.gamma(
            shape=6,
            scale=6,
        ),
        staffing=[(0, off_peak), (120, doors), (720, off_peak)],
        shift_end="finish",
        buffer=yard,
        external_overflow="reject",
    )
    sort = model.station(
        name="Sort",
        capacity=1,
        service_time=lambda rng: rng.uniform(4, 6),
        buffer=4,
        external_overflow="reject",
        time_to_failure=lambda rng: rng.exponential(scale=240),
        repair_time=lambda rng: rng.uniform(15, 45),
        failure_clock="busy",
    )
    load = model.station(
        name="Outbound load",
        capacity=4,
        service_time=lambda rng: rng.gamma(
            shape=6,
            scale=5,
        ),
        buffer=6,
        external_overflow="reject",
    )
    putaway = model.station(
        name="Put-away",
        capacity=2,
        service_time=lambda rng: rng.uniform(15, 25),
    )
    model.route([trucks, gate, unload, sort])
    model.branch(sort, {load: 0.75, putaway: 0.25})
    model.route([load, model.exit])
    model.route([putaway, model.exit])
    return model


def line_study(replications: int = REPLICATIONS, seed: int = 7):
    """Compare buffer plans, and the base plan without CNC failures."""
    scenarios = {
        name: machining_line(buffers=buffers) for name, buffers in BUFFER_PLANS.items()
    }
    scenarios["Two each, no CNC failures"] = machining_line(failures=False)
    return compare(
        scenarios=scenarios,
        duration=SHIFT,
        replications=replications,
        seed=seed,
    )


def dock_study(replications: int = REPLICATIONS, seed: int = 11):
    """Compare more dock doors with a larger yard, serving every truck."""
    return compare(
        scenarios={
            "6 doors, yard of 8": cross_dock(),
            "8 doors, yard of 8": cross_dock(doors=8),
            "6 doors, yard of 20": cross_dock(yard=20),
        },
        duration=DOCK_DAY,
        replications=replications,
        seed=seed,
        drain=True,
    )


def main():
    output = Path("output/operations")
    studies = [
        ("machining-line", line_study(), "completed_at_close", "No buffers"),
        ("cross-dock", dock_study(), "mean_flow_time", "6 doors, yard of 8"),
    ]
    for name, comparison, metric, baseline in studies:
        folder = output / name
        comparison.export(
            directory=folder,
            metric=metric,
            baseline=baseline,
        )
        comparison.viewer(
            path=folder / "comparison.html",
            metric=metric,
            baseline=baseline,
        )
        # The baseline scenario's first day, for browsing individual jobs.
        comparison.experiments[baseline].runs[0].viewer(folder / "viewer.html")
        for experiment in comparison.experiments.values():
            for run in experiment.runs:
                totals = run.summary.to_dicts()[0]
                assert totals["arrivals"] == (
                    totals["completed"] + totals["remaining"] + totals["rejected"]
                )
        print(f"\n{name}: {metric}")
        print(comparison.intervals(metric=metric))
        print(
            comparison.differences(
                metric=metric,
                baseline=baseline,
            )
        )
        # Where each scenario's queue sits, i.e., outside the first station or
        # in servers blocked by a full station downstream.
        for location in ["mean_outside_wait", "mean_total_blocked"]:
            print(
                comparison.intervals(metric=location).select(
                    "scenario",
                    "metric",
                    "mean",
                    "lower",
                    "upper",
                )
            )
    machining_line().diagram().write_html(
        file=output / "machining-line" / "network.html",
        include_plotlyjs=True,
    )
    cross_dock().diagram().write_html(
        file=output / "cross-dock" / "network.html",
        include_plotlyjs=True,
    )
    print(f"Reports were written to {output.resolve()}.")


if __name__ == "__main__":
    main()
