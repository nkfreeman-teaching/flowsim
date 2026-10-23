# FlowSim

FlowSim is a Python package for classroom simulations of service networks, i.e.,
systems in which customers or jobs arrive, wait for servers at one or more
stations, and leave. A model is a set of arrival sources, stations with parallel
servers, and routes between them. A small built-in scheduler orders the events,
and student code uses ordinary Python calls and NumPy duration samplers. Results
are Polars tables, Plotly figures, CSV exports, and an offline HTML viewer. A
Marimo lesson in `examples/lesson.py` is an optional classroom client, and the
package itself has no Marimo dependency.

## Getting started

FlowSim uses [Pixi](https://pixi.sh) to manage its environment. Clone the
repository and install the locked environment from its root:

```bash
git clone https://github.com/nkfreeman-teaching/flowsim
cd flowsim
pixi install
```

The repository defines these tasks:

| Task | What it does |
| --- | --- |
| `pixi run demo` | Runs the hand-calculated queue, two-stage network, and triage network in `examples/models.py`, then compares one, two, and three servers across 12 replications. Writes viewers, flowcharts, and CSV files under `output/`. |
| `pixi run exercise` | Runs the worked staffing exercise (see Classroom exercise) and writes reports under `output/service-day/`. |
| `pixi run extensions` | Runs peak demand with a lunch break, a buffered production line, a machine with repairs, and a combined line from `examples/extensions.py`, writing them under `output/extensions/`. |
| `pixi run notebook` | Opens the Marimo lesson, which adds controls for staffing, shift and failure-clock rules, and customer timelines. |
| `pixi run notebook-export` | Executes the lesson and saves `output/lesson.html`. |
| `pixi run examples` | Runs the four tasks above that execute examples, and fails if Marimo replaced a lesson output with a size warning. |
| `pixi run check` | Runs the tests, lint, format check, and notebook check. |
| `pixi run format` | Formats the code with ruff. |

Each saved viewer (e.g., `output/two-stage/viewer.html`) embeds its Plotly
library and data, so it opens directly in a browser without internet access.
The lock file covers Linux, Windows, Intel Macs, and Apple Silicon Macs, and
execution has been verified on Linux with Python 3.13. The package installs into
other Python environments as the distribution `classroom-flowsim` (imported as
`flowsim`), and it depends on NumPy, Polars, NetworkX, Plotly, and SciPy.

## A first model

The model below has customers who check in at one station and then receive
service at a second station with two servers.

```python
from flowsim import Model

model = Model(time_unit="minutes")
arrivals = model.source(
    name="Customers",
    interarrival=lambda rng: rng.exponential(scale=3),
)
check_in = model.station(
    name="Check-in",
    capacity=1,
    service_time=lambda rng: rng.uniform(1, 2),
)
service = model.station(
    name="Service",
    capacity=2,
    service_time=lambda rng: rng.exponential(scale=4),
)
model.route([arrivals, check_in, service, model.exit])

results = model.run(
    duration=480,
    seed=42,
    drain=True,
)
print(
    results.summary.select(
        "arrivals",
        "completed",
        "mean_total_wait",
        "overtime",
    )
)
print(results.stations)
results.viewer("output/my-run.html")
results.export("output/my-run")
```

A sampler receives a NumPy Generator owned by the run and returns one finite
scalar duration. Constants also work (e.g., `service_time=2`). Interarrival
times must be positive, and service times can be zero. Samplers should use the
supplied generator rather than one captured from outside the model, since each
run creates fresh simulation state and separate random streams for durations and
routing. NumPy's exponential `scale` is a mean duration, not an arrival rate.
Every duration uses the model's declared time unit (`"minutes"` by default), and
the label does not convert units.

The first arrival occurs after one sampled interarrival time by default.
`first_arrival=0` starts arrivals at time zero, and `limit=3` creates at most
three customers from that source. The full signature of a run is
`model.run(duration, seed=42, *, warmup=0, drain=False)`, and Measurement rules
describes how `warmup` and `drain` change the results. Routes use nodes from the
same model, and each node needs a unique name. Disconnected nodes, missing exit
paths, invalid capacities, invalid duration samples, and cycles produce errors
before or during the run.

## Results

A run returns Polars DataFrames and figure methods. The viewer has linked
station selection for queue histories and wait distributions, zoom and hover
controls, utilization, a customer timeline, paginated customer records, status
filtering, and CSV downloads. It reports unfinished customers alongside
completed-customer averages. `results.viewer()` returns the complete HTML
string, and `results.viewer("output/viewer.html")` also saves it. The Marimo
lesson displays that string in an iframe.

Individual Plotly figures also work in scripts and notebooks:

```python
model.diagram().show()
results.queue_plot().show()
results.wait_plot().show()
results.utilization_plot().show()
results.customer_plot(1).show()
```

`results.export("output/my-run")` writes seven CSV files and one metadata file.
Exports keep missing starts and exits as empty CSV fields and never replace an
unknown outcome with zero.

| File | Contents |
| --- | --- |
| `customers.csv` | Each customer's system arrival, admission, exit, flow time, observed total wait and blocking, final status, and current station. |
| `visits.csv` | Each station visit's arrival, service start, processing completion, departure, server identity, waiting, blocking, and sampled service requirement. |
| `states.csv` | Station queue and server counts after each time with a state change, plus closing and the end of service. |
| `stations.csv` | Station counts, wait summaries, time-weighted queue lengths, and utilization. |
| `summary.csv` | System counts at closing and after service, overtime, completed flow-time averages, throughput, and time-average work in process. |
| `activities.csv` | Each customer's processing, paused, and blocked intervals by server. Intervals of zero length are omitted. |
| `failures.csv` | Per-server failure times, sampled lifetimes, repair requirements, and observed repair ends. The file has only a header when no station fails. |
| `metadata.json` | The FlowSim version, run settings (time unit, duration, warm-up, seed, drain), end time, capacities, per-node settings, routes, and text definitions of the measurement windows and cohorts. |

## Model features

The examples above use one source, a straight route, and stations with a fixed
number of servers. Branches, schedules, finite buffers, and failures extend
that model. Schedules, buffers, and failures each require an explicit behavior
argument, since the package does not choose a default for how a shift ends,
where overflow goes, or when a failure clock runs. Runnable versions of these
models are in `examples/models.py` and `examples/extensions.py`.

### Branches and shared stations

A branch sends each customer to exactly one destination, chosen with fixed
probabilities that must sum to one. Several sources or upstream stations can
route to the same station, sharing its servers and waiting room.

```python
from flowsim import Model

model = Model()
arrivals = model.source(
    name="Customers",
    interarrival=lambda rng: rng.exponential(scale=3),
)
triage = model.station(
    name="Triage",
    capacity=1,
    service_time=1,
)
routine = model.station(
    name="Routine",
    capacity=2,
    service_time=lambda rng: rng.gamma(
        shape=2,
        scale=2,
    ),
)
specialist = model.station(
    name="Specialist",
    capacity=1,
    service_time=lambda rng: rng.uniform(5, 8),
)
model.route([arrivals, triage])
model.branch(triage, {routine: 0.7, specialist: 0.3})
model.route([routine, model.exit])
model.route([specialist, model.exit])
results = model.run(duration=480)
```

### Demand and staffing schedules

A schedule is a list of (time, value) pairs that begins at zero and has strictly
increasing change times. Arrival `rates` are customers per model time unit, and
they replace `interarrival` for that source. Arrivals follow a piecewise constant
Poisson process sampled by integrating the rate across changes, so a zero rate
produces no arrivals until a positive period. An explicit `first_arrival`
overrides the first time, including during a zero-rate period.

```python
from flowsim import Model

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
    shift_end="finish",
)
model.route([arrivals, service, model.exit])
results = model.run(
    duration=480,
    drain=True,
)
```

`capacity` is installed capacity (i.e., the number of servers that exist), and
staffing ranges from zero through that capacity, with the lowest numbered
servers scheduled first. This example has a lunch break from minute 180 to 210
and a closing crew at minute 480. The shift rule is required with staffing.
`shift_end="finish"` lets an off-duty server finish its job and its downstream
transfer, then prevents new work. `shift_end="pause"` pauses processing until
that same server is scheduled again, since work does not move between servers.
A drained run honors future staffing (see Measurement rules). A paused server
must return and waiting work needs future capacity, so an impossible drain
raises an error naming the station or server. Later shift events do not extend
a run whose customers have all finished.

### Finite buffers and blocking

`buffer` limits the number of jobs waiting at a station, separately from jobs
occupying servers. `buffer=0` permits direct service only, and the default
`buffer=None` keeps an unlimited waiting room. A completed job that cannot enter
its next station holds its upstream server until downstream admission succeeds
(i.e., blocking after service), and blocked transfers wait in admission order.

```python
from flowsim import Model

model = Model()
parts = model.source(
    name="Parts",
    interarrival=2,
    first_arrival=0,
    limit=20,
)
assembly = model.station(
    name="Assembly",
    capacity=1,
    service_time=1,
    buffer=2,
    external_overflow="reject",
)
finishing = model.station(
    name="Finishing",
    capacity=1,
    service_time=3,
    buffer=0,
    external_overflow="reject",
)
model.route([parts, assembly, finishing, model.exit])
results = model.run(
    duration=40,
    drain=True,
)
print(
    results.summary.select(
        "arrivals",
        "rejected",
        "completed",
        "mean_total_blocked",
    )
)
```

The overflow rule is required with a finite buffer and applies to arrivals from
a source. `external_overflow="reject"` records a rejected arrival when the first
station has no room. `external_overflow="wait"` holds the arrival in a separate
outside queue until admission is possible, and that queue does not use the
inside buffer. Outside arrivals and blocked transfers from upstream stations
wait in one admission line, and the station admits them in the order they asked
to enter. `arrivals` counts attempts, with
`arrivals = completed + remaining + rejected`. `admitted` counts successful
admissions to the network, and `admitted_at_close` excludes later admissions.
`remaining_at_close` includes unfinished outside customers, and
`outside_at_close` reports them separately. Wait and flow averages exclude
rejections. Outside waiting adds to `total_wait`, blocking is reported
separately in `total_blocked`, and work in process begins at admission. A small
mean wait does not establish good service when many customers are rejected.

### Failures and repair

```python
from flowsim import Model

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
    failure_clock="available",
)
model.route([arrivals, machine, model.exit])
results = model.run(
    duration=240,
    drain=True,
)
```

Each server has its own failure and repair random streams. Time to failure is a
positive lifetime, and repair time is a nonnegative duration, both in model time
units. The failure clock is required. `failure_clock="available"` advances while
a server is up and scheduled, including idle and blocked time and time an
off-duty server spends finishing its job under the finish rule.
`failure_clock="busy"` advances only during processing. Both clocks keep the
unused lifetime while inactive and draw a fresh lifetime after each repair. A
failure pauses processing, and repair resumes the remaining requirement without
resampling it. Repairs run independently in elapsed time, including off-shift
periods, since there is no shared repair crew. A completed job that is blocked
can still transfer while its former server is down.

## Measurement rules

Arrivals occur in `[0, duration)`. With the default `drain=False`, service also
stops at `duration`, excluding events exactly at that time, and the records of
customers still waiting or in service remain in the results. With `drain=True`,
arrivals stop at `duration` and service continues until every admitted customer
finishes, including events exactly at closing. `end_time` reports when service
ends, and `overtime` is `end_time - duration` (zero when all customers finish
before closing). The state trace includes the continuation, and the viewer marks
closing with a dashed line.

Several events can occur at the same instant. FlowSim processes shift changes
first, then service completions, transfers, failures, and repairs in the order
they were scheduled, then new arrivals, and drain checks last. Thus, a server that finishes a job at minute 10 is free for a
customer who arrives at minute 10, and the state trace keeps the final state at
each time.

Queue averages, utilization, throughput, and event counts use the operating
window `[warmup, duration)`, so they exclude events exactly at closing and all
overtime. `warmup=60` keeps the full trace and measures station states over
`[60, duration)`. Station arrival, service-start, and service-completion counts
use each event's time in that window. `completed_at_close` and
`remaining_at_close` describe the backlog at closing, while `completed` and
`remaining` describe the final records after any continuation. Station closing
counts are `waiting_at_close` and `in_service_at_close`, and final station counts
are `waiting_at_end` and `in_service_at_end`. Closing and final counts include
customers who arrived before warm-up.

Mean and 95th percentile waiting times use station arrivals at or after warm-up
whose service starts were observed, including visits to downstream stations
after closing when service continues. `wait_arrivals` reports the size of this
visit cohort, and `wait_observations` reports the number with observed waits.
Flow-time and total-wait averages use system arrivals at or after warm-up whose
exits were observed, and `cohort_remaining` counts unfinished members of that
arrival cohort. With `drain=False`, these observed averages can underrepresent
long waits and flow times, particularly when the queue is still growing.
Draining completes the admitted cohort.

`total_wait` accumulates waits completed before service starts, so it excludes
any ongoing wait of an unfinished customer. `service_time` in `visits` is a
sampled service requirement, not elapsed busy time, and it can extend beyond the
run limit. `service_end - service_start` includes pauses, and `departure_time`
can be later than `service_end` because of downstream blocking. `activities`
separates actual processing, paused work, and blocked time.

Mean queue length is queue area divided by observation time. Utilization is
occupied-server area divided by installed capacity and observation time, where
occupied servers include paused and blocked jobs. `processing_utilization`
measures actual processing against installed capacity, and `blocking_fraction`
and `downtime_fraction` measure blocking and down-server exposure against that
capacity. Down time and paused work can overlap, so these fractions must not be
added. `mean_scheduled_servers` and `mean_available_servers` integrate staffing
and up-server counts, where available servers include off-duty servers finishing
a job. `staffed_utilization` divides processing area by available-server area
and is missing when available exposure is zero. Work in process uses admitted
customers' presence clipped to the measurement window, and queue maxima exclude
states lasting zero time.

## Replications and scenario comparisons

`model.experiment` runs independent replications with distinct seeds derived
from one seed and keeps each run's raw results in `experiment.runs`.

```python
from examples.models import service_network

experiment = service_network().experiment(
    duration=480,
    replications=20,
    seed=42,
    drain=True,
)
print(experiment.intervals("mean_wait"))
print(experiment.intervals("mean_total_wait"))
```

`intervals` estimates a Student t confidence interval across run-level values.
A station metric gives one row per station unless `station=` names one, and a
system metric gives one row. Missing run values are excluded and counted in
`observed_runs`. These intervals describe the finite-run statistic under the
selected stopping rule, so they do not establish steady-state performance, and
intervals from undrained runs do not correct the missing-outcome bias described
above. Repeated runs with the same seed and model reproduce results in the
locked environment. Changing only capacity preserves arrival streams, while
adding or renaming nodes can change which stream each node receives. The
`examples` import in this section and the next works from the repository root.

`compare` runs named models with the same replication seeds and pairs their
results by replication.

```python
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
print(comparison.intervals())
print(comparison.differences())
print(
    comparison.intervals(
        metric="mean_wait",
        station="Service",
    )
)
comparison.plot(metric="overtime").show()
comparison.plot(
    metric="overtime",
    differences=True,
).show()
comparison.viewer("output/comparison.html")
comparison.export("output/comparison")
```

The default metric is mean total waiting time. `intervals()` reports each
scenario's mean, confidence limits, and number of observed runs. `differences()`
subtracts the baseline scenario (the first scenario unless `baseline=` names
another) within each matched replication, then estimates a Student t interval
across those paired differences. A missing value excludes that pair and reduces
`observed_runs`. `plot`, `viewer`, and `export` accept the same `metric`,
`station`, `confidence`, and `baseline` arguments. Compared models must declare
the same time unit, and a station metric requires that station in every
scenario. Replication identity and seed matching are checked before paired
differences are calculated. Matching seeds preserve the arrival stream when only
capacity changes, but they do not guarantee that each customer receives the
same draws when the network structure or the order of upstream completions
changes.

The table below lists the metrics that `intervals`, `differences`, and `plot`
accept. System metrics come from `summary`, and station metrics come from
`stations` and require a station name in a comparison.

| Metric | Scope | Meaning |
| --- | --- | --- |
| `mean_total_wait` | System | Mean total waiting time per completed customer |
| `mean_flow_time` | System | Mean time from arrival to exit |
| `throughput` | System | Exits per time unit during operating hours |
| `remaining_at_close` | System | Customers present at closing |
| `completed_at_close` | System | Customers completed before closing |
| `remaining` | System | Customers unfinished at the end |
| `overtime` | System | Time to finish after closing |
| `mean_wip` | System | Time-average customers in the system |
| `rejected` | System | Rejected arrivals |
| `admitted` | System | Admitted customers |
| `mean_total_blocked` | System | Mean time blocked between stations |
| `mean_outside_wait` | System | Mean waiting time outside the first station |
| `mean_wait` | Station | Mean station waiting time |
| `mean_queue` | Station | Time-average customers waiting |
| `utilization` | Station | Occupied share of installed capacity |
| `p95_wait` | Station | 95th percentile station waiting time |
| `processing_utilization` | Station | Processing share of installed capacity |
| `blocking_fraction` | Station | Blocked share of installed capacity |
| `downtime_fraction` | Station | Down share of installed capacity |
| `staffed_utilization` | Station | Processing share of available capacity |
| `mean_available_servers` | Station | Mean number of available servers |

The offline comparison viewer shows scenario means and paired differences for
one metric (e.g., `viewer(metric="overtime")`). Comparison exports contain
per-replication system and station metrics, scenario intervals, paired
differences, and metadata. Raw customer records remain in
`comparison.experiments[scenario].runs`, and each run has its own `export()`.
The intervals are nominal for each reported metric or contrast, i.e., they are
not simultaneous confidence bounds across every scenario and metric.

## Classroom exercise

The service-day exercise uses the two-stage network from A first model.
Customers arrive every three minutes on average, check-in takes one to two
minutes with one server, and service takes four minutes on average. One service
server has an offered load of 4/3 (i.e., more work arrives than it can process),
and two service servers have an offered load of 2/3 per server. These ratios
motivate predictions before any simulation. The lesson asks students to predict
the bottleneck and compare waiting, closing backlog, throughput, and overtime.

`examples/service_day.py` defines the exercise settings once, and the lesson
reads them from that file. The exercise runs 20 days per staffing level, closes
arrivals at 480 minutes, and serves every customer to completion. The
illustrative targets are a mean total wait of at most 5 minutes and completion
within 30 minutes after closing on at least 90% of days (18 of 20). These are
adjustable teaching targets, not empirical service standards. The script chooses
the lowest staffing level meeting both observed targets, and the observed day
count is not a confidence bound on a population probability.

## For maintainers

`AGENTS.md` states the project rules for contributors and coding agents. The
standard for a behavioral change is a test against a hand calculation, not only
against simulation output. The deterministic queue in `examples/models.py` is
the reference case, with arrivals at 0, 1, and 2 minutes and a two-minute
service time. With one server, waits are 0, 1, and 2 minutes, mean queue length
over seven minutes is 3/7, and utilization is 6/7. With two servers, those three
customers do not wait.

`pixi run check` runs the test suite, and `pixi run examples` runs every example
end to end. Tests use fixed models in `tests/models.py`, so editing a teaching
example cannot change a library test, and `tests/test_examples.py` checks that
the examples still run. `tests/test_readme.py` runs the Python blocks in this
README. The browser tests block external requests and exercise the saved
viewers' controls and downloads. They run when Playwright is installed and
Chrome or Chromium is on the executable search path, and they report a skip
otherwise. Setting `FLOWSIM_CHROME` to a browser executable selects it, and a
path that does not exist fails the tests.

## Scope and limits

FlowSim supports acyclic routes, first-come, first-served service, identical
servers within each station, scheduled demand and staffing, finite buffers,
blocking after service, and independent failures with resumable work. Every
station has its own server pool. Priorities, reneging, batches, workers shared
across stations, shared repair crews, inventory policies, and rework loops are
not implemented.

Runs keep every customer, visit, and state record in memory, which suits
classroom-scale examples. There is no streaming or aggregate-only mode, and the
viewer embeds raw records, so it can become large for long runs (approximately
5 MB for one 480-minute day of the first model). Numeric outputs target
classroom tables and plots, and LaTeX numeric exports are not included. FlowSim
schedules events with its own scheduler (`flowsim/scheduler.py`) rather than a
simulation library, and that scheduler reproduces the event order of SimPy
4.1.2. The package is released under the MIT license.
