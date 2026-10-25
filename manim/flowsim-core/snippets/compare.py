from examples.models import service_network
from flowsim import compare

comparison = compare(
    scenarios={
        "One server": service_network(service_capacity=1),
        "Two servers": service_network(service_capacity=2),
        "Three servers": service_network(service_capacity=3),
    },
    duration=480,
    replications=20,
    seed=42,
    drain=True,
)
means = comparison.intervals().select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
paired = comparison.differences(baseline="Two servers").select(
    "scenario",
    "baseline",
    "mean",
    "lower",
    "upper",
)
comparison.viewer(
    path="output/staffing/comparison.html",
    baseline="Two servers",
)
