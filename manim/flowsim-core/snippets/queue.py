from examples.models import deterministic_queue

model = deterministic_queue(capacity=1)
results = model.run(duration=7, seed=42)

customers = results.customers.select(
    "customer_id",
    "arrival_time",
    "exit_time",
    "flow_time",
    "total_wait",
)
visits = results.visits.select(
    "customer_id",
    "station",
    "service_start",
    "service_end",
    "server_id",
)
stations = results.stations.select(
    "station",
    "capacity",
    "mean_wait",
    "mean_queue",
    "utilization",
)
summary = results.summary.select(
    "arrivals",
    "completed",
    "mean_flow_time",
    "throughput",
)

results.viewer("output/queue/viewer.html")
results.export("output/queue")
