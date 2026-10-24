from examples.models import service_network

experiment = service_network().experiment(
    duration=480,
    replications=20,
    seed=42,
    drain=True,
)
waits = experiment.intervals("mean_wait").select(
    "station",
    "runs",
    "mean",
    "lower",
    "upper",
)
