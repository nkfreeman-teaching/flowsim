"""Scheduled service and production models with explicit behavioral choices."""

from pathlib import Path

from flowsim import Model


def peak_service(shift_end: str = "finish") -> Model:
    model = Model()
    arrivals = model.source(
        name="Customers",
        rates=[(0, 0.2), (90, 0.6), (300, 0.2)],
    )
    service = model.station(
        name="Service",
        capacity=3,
        service_time=lambda rng: rng.exponential(scale=4),
        staffing=[(0, 1), (90, 3), (180, 0), (210, 3), (300, 1), (480, 3)],
        shift_end=shift_end,
    )
    model.route([arrivals, service, model.exit])
    return model


def buffered_line(buffer: int = 0) -> Model:
    model = Model()
    arrivals = model.source(
        name="Parts",
        interarrival=2,
        first_arrival=0,
        limit=20,
    )
    upstream = model.station(
        name="Assembly",
        capacity=1,
        service_time=1,
        buffer=2,
        external_overflow="reject",
    )
    downstream = model.station(
        name="Finishing",
        capacity=1,
        service_time=3,
        buffer=buffer,
        external_overflow="reject",
    )
    model.route([arrivals, upstream, downstream, model.exit])
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


def main():
    examples = [
        ("peak-service", peak_service(), 480),
        ("buffered-line", buffered_line(), 40),
        ("repairing-machine", repairing_machine(), 240),
        ("combined-line", combined_line(), 180),
    ]
    for name, model, duration in examples:
        result = model.run(
            duration=duration,
            seed=42,
            drain=True,
        )
        output = Path("output/extensions") / name
        result.export(output)
        result.viewer(output / "viewer.html")
        model.diagram().write_html(
            file=output / "network.html",
            include_plotlyjs=True,
        )
        totals = result.summary.to_dicts()[0]
        assert totals["arrivals"] == totals["completed"] + totals["rejected"]
        assert totals["remaining"] == 0
        print(f"\n{name}")
        print(f"Customers: {result.customers.shape}, schema: {result.customers.schema}")
        print(
            f"Visits: {result.visits.shape}, activities: {result.activities.shape}, failures: {result.failures.shape}"
        )
        print(totals)
        print(result.stations.to_dicts())
        print(result.customers.head(n=2).to_dicts())
        print(result.failures.head(n=2).to_dicts())


if __name__ == "__main__":
    main()
