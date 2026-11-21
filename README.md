# FlowSim

FlowSim is a Python package for classroom simulations of service networks, i.e.,
systems in which customers or jobs arrive, wait for servers at one or more
stations, and leave, and of supply chains whose stages fill orders from stock and
reorder each period. A model is a set of arrival sources, stations with parallel
servers, and routes between them, and a run returns Polars tables, Plotly
figures, CSV files, and an offline HTML viewer. The package schedules events
itself, depends on neither SimPy nor Marimo, and runs the same code in Marimo,
Jupyter, VS Code, and plain scripts.

The model below has one station with two servers. Customers arrive every three
minutes on average and need four minutes of service on average, and printing the
results shows the run's settings, its headline measures, its tables, and the
calls that usually come next.

```python
from flowsim import Model, exponential

model = Model(time_unit="minutes")
customers = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
)
service = model.station(
    name="Service",
    capacity=2,
    service_time=exponential(mean=4),
)
model.route([customers, service, model.exit])
results = model.run(duration=480)
print(results)
```

`exponential(mean=3)` is a named distribution, i.e., an object that draws a new
random duration each time FlowSim calls it. A run uses seed 42 unless `seed=`
gives another, so the same model and seed reproduce the same results.

## What each call returns

Every FlowSim object describes itself. Printing a model, a result, or a
distribution (or leaving it as the last line of a notebook cell) lists what it
holds and the calls that usually come next. A single run, a set of replications,
a scenario comparison, and a set of distribution fits each return one object,
and the table below lists what each object holds.

| Object | Returned by | Tables | Plots | Viewer and export |
| --- | --- | --- | --- | --- |
| `Results` | `model.run(...)` | `customers`, `visits`, `states`, `activities`, `failures`, `stations`, and `summary` (plus `inventory`, `shipments`, and `stock_points` for a supply chain), and `report()`, which lists every metric of the run in one long table | `plot_queue()`, `plot_wait()`, `plot_utilization()`, `plot_resources()`, `plot_customer(id)`, `plot_inventory()`, and `plot_orders()` | `viewer()` and `export(folder)` |
| `Experiment` | `model.experiment(...)` | `summary`, `stations`, and `stock_points` with a `replication` column, `intervals(metric)`, and each run's `Results` in `runs` | `plot(metric)` | `viewer()`, a page of every metric whose runs open on the page, and `export(folder)` |
| `Comparison` | `flowsim.compare(...)` | `summary`, `stations`, and `stock_points` with `scenario` and `replication` columns, `intervals(metric)`, `differences(metric)`, and each scenario's `Experiment` in `experiments` | `plot(metric)` and `plot(metric, differences=True)` | `viewer()`, a page of every metric and baseline whose runs open on the page, and `export(folder)` |
| `Fits` | `flowsim.fit_all(data)` | `table` (one row per fitted family), `failed`, `best`, and `pick(name_or_rank)` | `plot()` | None |

Two catalog functions describe every number in these tables. `flowsim.metrics()`
returns a Polars table of the replication metrics with each one's scope, units,
measurement window, and meaning, and `flowsim.explain(name)` prints the same
description for one metric or table column with the call that requests it (e.g.,
`flowsim.explain("p95_wait")`). A misspelled name prints its close matches, and
an unknown metric passed to `intervals` raises an error that lists them. The
Reference section holds both catalogs as tables.

Each of these features appears differently in each environment. Text summaries
serve scripts and terminals, HTML summaries serve notebooks, and
`viewer().open()` serves scripts, as the table below shows.

| Feature | Marimo | Jupyter | VS Code | Plain scripts and terminals |
| --- | --- | --- | --- | --- |
| Object summaries | HTML summary as a cell's output | HTML summary as a cell's output | HTML summary in a notebook, text from `print` in a script | Text from `print(obj)` |
| Polars tables, including `flowsim.metrics()` | Interactive table as a cell's output | Table as a cell's output | Table in a notebook, text from `print` in a script | Text from `print(table)` |
| Plotly figures | Interactive figure as a cell's output | Interactive figure as a cell's output | Interactive figure in a notebook, `.show()` from a script | `.show()` opens the figure in a browser |
| Viewer | `mo.iframe(html=viewer.html)`, as `examples/lesson.py` does | The viewer as a cell's output, in an isolated frame | The viewer in a notebook, `.open()` from a script | `.open()` shows the page in a browser, and `.save(path)` writes it |
| `flowsim.explain(name)` and docstrings (e.g., `help(flowsim.Model.station)`) | Printed text | Printed text | Printed text, plus hover help in the editor | Printed text |

## Contents

- [Building models](#building-models)
  - [Sources, stations, and routes](#sources-stations-and-routes)
  - [Branches and shared stations](#branches-and-shared-stations)
  - [Durations and distributions](#durations-and-distributions)
  - [Inspecting a model](#inspecting-a-model)
  - [Drawing a model in the browser](#drawing-a-model-in-the-browser)
  - [Model features](#model-features)
    - [Customer types](#customer-types)
    - [Demand and staffing schedules](#demand-and-staffing-schedules)
    - [Finite buffers and blocking](#finite-buffers-and-blocking)
    - [Priorities and abandonment](#priorities-and-abandonment)
    - [Failures and repair](#failures-and-repair)
    - [Inventory and ordering](#inventory-and-ordering)
    - [Production at stations](#production-at-stations)
- [Analyzing results](#analyzing-results)
  - [One run](#one-run)
  - [Replications](#replications)
  - [Scenario comparisons](#scenario-comparisons)
- [Fitting durations to data](#fitting-durations-to-data)
- [Example studies](#example-studies)
  - [Classroom exercise](#classroom-exercise)
  - [Machining line](#machining-line)
  - [Truck cross-dock](#truck-cross-dock)
  - [Supply chain example](#supply-chain-example)
- [Reference](#reference)
  - [Metrics](#metrics)
  - [Table columns](#table-columns)
  - [Measurement rules](#measurement-rules)
  - [Event order](#event-order)
- [Setup for OM 522](#setup-for-om-522)
  - [Tasks](#tasks)
- [Changes in 2.0](#changes-in-20)
- [Videos](#videos)
- [For maintainers](#for-maintainers)
- [Scope and limits](#scope-and-limits)

## Building models

The example below is the two-stage network that the classroom exercise and the
core video use. Customers check in at a station with one server and then receive
service at a second station with two servers.

```python
from flowsim import Model, exponential, uniform

model = Model(time_unit="minutes")
arrivals = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
)
check_in = model.station(
    name="Check-in",
    capacity=1,
    service_time=uniform(
        low=1,
        high=2,
    ),
)
service = model.station(
    name="Service",
    capacity=2,
    service_time=exponential(mean=4),
)
model.route([arrivals, check_in, service, model.exit])

results = model.run(
    duration=480,
    seed=42,
    drain=True,
)
print(results.stations)
```

The subsections below give the rules for each part of this model, and Model
features describes the arguments that extend it.

### Sources, stations, and routes

A source creates customers, a station serves them with `capacity` identical
servers and one waiting line, and `model.exit` removes them from the network.
`model.route` takes the node objects that `model.source` and `model.station`
return (not their names), and every path through the network must end at
`model.exit`. Routes use nodes from the same model, and each node needs a unique
name. Disconnected nodes, missing exit paths, invalid capacities, invalid
duration samples, and cycles produce errors before or during the run.

The first arrival occurs after one sampled interarrival time by default.
`first_arrival=0` starts arrivals at time zero, and `limit=3` creates at most
three customers from that source. The full signature of a run is
`model.run(duration, seed=42, *, warmup=0, drain=False)`. Arrivals stop at
`duration`, `warmup` excludes an initial period from measurement, and
`drain=True` continues the run past closing until every customer who was not
rejected has completed service or abandoned (see Measurement rules).

### Branches and shared stations

A branch sends each customer to exactly one destination, chosen with fixed
probabilities that must sum to one. Several sources or upstream stations can
route to the same station, sharing its servers and waiting room.

```python
from flowsim import Model, exponential, gamma, uniform

model = Model()
arrivals = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
)
triage = model.station(
    name="Triage",
    capacity=1,
    service_time=1,
)
routine = model.station(
    name="Routine",
    capacity=2,
    service_time=gamma(
        shape=2,
        scale=2,
    ),
)
specialist = model.station(
    name="Specialist",
    capacity=1,
    service_time=uniform(
        low=5,
        high=8,
    ),
)
model.route([arrivals, triage])
model.branch(triage, {routine: 0.7, specialist: 0.3})
model.route([routine, model.exit])
model.route([specialist, model.exit])
results = model.run(duration=480)
```

### Durations and distributions

A duration argument (`interarrival`, `service_time`, `patience`,
`time_to_failure`, `repair_time`, and a stock point's `lead_time`) and a demand's
`per_period` quantity each take a constant, a named distribution, or a function
of the run's random generator. A constant gives the same value every time (e.g.,
`service_time=2`). A named distribution states its parameters by name and draws
a new value each time FlowSim calls it. It prints as it was written (e.g.,
`Exponential(mean=4)`), reports its `mean`, its `sd`, and a one-sentence
`describe()`, and appears by name and parameters in export metadata.
Interarrival times must be positive, and service times can be zero. Every
duration uses the model's declared time unit (`"minutes"` by default), and the
label does not convert units. A demand's `per_period` is instead a quantity of
units per review period.

| Constructor | Draws |
| --- | --- |
| `exponential(mean=)` | Memoryless gaps, as for random arrivals |
| `uniform(low=, high=)` | Every value in the range with equal chance |
| `triangular(low=, mode=, high=)` | A rough low, likely, and high estimate |
| `pert(low=, mode=, high=)` | A smooth low, likely, and high estimate |
| `normal(mean=, sd=)` | Values symmetric around the mean (a negative draw stops the run, so the mean must sit well above `sd`) |
| `lognormal(mean=, sd=)` | Right-skewed values that are never negative, with the mean and `sd` of the duration itself |
| `gamma(shape=, scale=)` | Right-skewed values, flexible for service times |
| `weibull(shape=, scale=)` | Lifetimes, which wear out when `shape` exceeds 1 |
| `erlang(k=, mean=)` | The sum of `k` exponential stages, less variable than exponential |
| `beta(a=, b=, low=0, high=1)` | A bounded, flexible shape between `low` and `high` |
| `empirical(data)` | One of the observed values, each with equal chance |
| `poisson(mean=)` | Whole-number counts, as for random demand |
| `discrete(values, weights=None)` | One of a few listed values, with equal chance or by weight |
| `negative_binomial(mean=, sd=)` | Whole-number counts more variable than Poisson |
| `shifted(distribution, by=)` | Another distribution's draw plus a fixed amount, e.g., a minimum time |

A function of one argument covers what the constructors do not, e.g., demand
truncated at zero (`lambda rng: max(0.0, rng.normal(100, 20))`, as in
Production at stations) or a mixture of two task types. Its argument is a NumPy
`Generator` owned by the run, and it returns one finite number drawn from that
generator, so each run starts with fresh random streams and one seed reproduces
it. NumPy's exponential `scale` is a mean duration, not an arrival rate. Thus,
`exponential(mean=3)` draws the same values as
`lambda rng: rng.exponential(scale=3)`, and `uniform(low=1, high=2)` draws the
same values as `lambda rng: rng.uniform(1, 2)`, so the NumPy code in the videos
gives the same results as the named distributions here.

### Inspecting a model

Printing a model lists its nodes, its routes, and whether it passes validation.
`model.diagram()` draws the network as a Plotly figure. With the default
`check=False`, an incomplete model still draws, and a node that no source
reaches or a source or station without an onward route appears in red with the
reason on hover. `model.diagram(check=True)` instead raises the error that `run`
would raise. For a supply chain, `model.diagram()` draws the outside supplier,
the stock points, and demand in one row with goods moving left to right, labels
the arrow into each stock point with its lead time, and places a producing
stage's stations below it. In either drawing, an arrow that would pass over
another node (e.g., one that skips a layer) curves around it.

In code, `model.nodes` maps each name to its node in definition order, and
`model.graph` returns a frozen NetworkX copy of the routes with each edge's
`probability`. An edge from a typed route holds `types` instead, i.e., a mapping
from each customer type that may take it to its probability, and
`model.routing` lists each node's destinations by customer type. None of these
can change the model.

### Drawing a model in the browser

`flowsim.builder()` returns a page for drawing a service network, and
`flowsim.builder(path)` also saves it. A notebook displays the page in an
isolated frame, and a script calls `.open()` to show it in a browser. The page
works offline. It adds sources, stations, and the exit to a canvas, connects
them with arrows, and treats two or more arrows from one node for the same
customers as a probabilistic branch whose probabilities must sum to one. With
customer types, drawing a node's second arrow opens the side panel on a choice
between a split by probability and a split by customer type (e.g., new patients
go from the source to a registration desk, while existing patients go to the
check-in desk), and that panel sets the types of every arrow from the node. A
second arrow may also join the same two nodes if each arrow carries
different types (e.g., walk-ins always go from a desk to an exam room, while
appointments branch from the desk to the exam room or the exit). A side
panel edits every argument of `Model.source` and `Model.station`, i.e., each
duration (a constant or a named distribution with its parameters), customer
types with each source's type mix and the types each arrow carries, arrival-rate
and staffing schedules, finite buffers, abandonment, server failures, and
priorities. As the model changes, the page writes a complete script with a copy
button and a `.py` download, and it saves and loads its own JSON model file
(including files saved by earlier versions of the page).

The page never chooses a behavior argument for the student. A staffing schedule
needs `shift_end`, a finite buffer needs `external_overflow`, patience needs
`abandon_from`, and failures need `failure_clock`, and each choice starts
unselected. Until the student chooses, the Checks list names the missing choice
and the script writes `None` for it, so running the script raises FlowSim's own
error. The page also leaves type mixes, ranks, patience, and failure durations
blank rather than suggesting values. It checks routes (including each customer
type's routes and the rule that a loop across types may pass only through
unlimited buffers), probabilities, choices, and single values, and `model.run`
in the generated script is the final check. Supply chains are not in the page,
so they are added by editing the generated script, which is ordinary FlowSim
code (the page does not read edited code back).

From the keyboard, Tab reaches each arrow and node, Enter opens it in the side
panel (whose Add route control connects nodes), the arrow keys move a node,
Delete removes it, and Escape clears the selection. Undo and redo cover every
change (Ctrl+Z, and Ctrl+Shift+Z or Ctrl+Y, outside a text field), and Arrange
places the nodes in the left-to-right layers that `model.diagram()` uses. The
page's forms come from the signatures and docstrings of the distribution
constructors and of `Model.source`, `Model.station`, and `Model.run`.
`pixi run demo` saves the page as `output/builder.html`, and the block below
saves it from any script or notebook.

```python
from flowsim import builder

page = builder("output/builder.html")
```

### Model features

The examples above use one source, routes without customer types, and stations
with a fixed number of servers. Customer types, schedules, finite buffers,
priorities, abandonment, failures, and stock points extend that model.
Schedules, buffers, abandonment, and failures each require an explicit behavior
argument, since the package does not choose a default for how a shift ends,
where overflow goes, which queues a customer may leave, or when a failure clock
runs. Runnable versions of these models are in `examples/models.py` and
`examples/extensions.py`.

#### Customer types

A customer type is a label that a source draws for each arrival (e.g., a
product, a call skill, or a patient acuity), and service times and routes may
depend on it. `model.source(..., types={"A": 0.6, "B": 0.4})` gives each
arrival type A with probability 0.6 and type B otherwise, and a one-type
mapping gives every arrival that type without a draw. A station's
`service_time` may be a mapping from type to duration, and `route` and
`branch` take `types=[...]` to apply only to the listed types. A node holds
either one route for every type or typed routes whose type lists do not
overlap. Customers from a source without `types` have no type, so the
`customer_type` column is empty for them.

Each type's own routes must be acyclic, but routes across types may form a
cycle, which is the classic job shop. For example, type A below visits the Mill
and then the Lathe, while type B visits the Lathe and then the Mill. A cycle of
finite buffers could deadlock, with each blocked server waiting for room at the
next station on the cycle, so a station on a cycle across types must have an
unlimited buffer, and `route` raises an error otherwise. Routes may be added
after their stations, so `run` checks that every type that can reach a station
has a service time, a route, and any rank or patience the station sets by type
(see Priorities and abandonment), and the error names the station, the type,
and the source.

```python
import polars as pl

from flowsim import Model, exponential, uniform

model = Model()
orders = model.source(
    name="Orders",
    interarrival=exponential(mean=4),
    types={"A": 0.6, "B": 0.4},
)
mill = model.station(
    name="Mill",
    capacity=1,
    service_time={"A": 1.5, "B": uniform(low=1, high=2)},
)
lathe = model.station(
    name="Lathe",
    capacity=1,
    service_time={"A": 1, "B": 2.5},
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
    [mill, lathe, model.exit],
    types=["A"],
)
model.route(
    [lathe, mill, model.exit],
    types=["B"],
)
results = model.run(duration=480)
waits = results.visits.group_by(
    "customer_type",
    "station",
).agg(pl.col("wait_time").mean())
print(waits)
```

The type draw uses its own random stream at each source, so adding types to a
source leaves its arrival times unchanged for a given seed. The `customers` and
`visits` tables carry each customer's `customer_type`, and the viewer adds a
type column when any customer has one. Waits by type come from a `group_by` on
`visits`, as above, and FlowSim adds no per-type replication metric.

#### Demand and staffing schedules

A schedule is a list of (time, value) pairs that begins at zero and has strictly
increasing change times. Arrival `rates` are customers per model time unit, and
they replace `interarrival` for that source. Arrivals follow a piecewise constant
Poisson process sampled by integrating the rate across changes, so a zero rate
produces no arrivals until a positive period. An explicit `first_arrival`
overrides the first time, including during a zero-rate period.

```python
from flowsim import Model, exponential

model = Model()
arrivals = model.source(
    name="Customers",
    rates=[(0, 0.2), (90, 0.6), (300, 0.2)],
)
service = model.station(
    name="Service",
    capacity=3,
    service_time=exponential(mean=4),
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

#### Finite buffers and blocking

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

The overflow rule applies to arrivals from a source and is required on any
finite-buffer station that receives arrivals directly from a source (interior
stations only receive blocked transfers from upstream stations, so
`external_overflow` is optional there). `external_overflow="reject"` records a
rejected arrival when the first station has no room. `external_overflow="wait"`
holds the arrival in a separate outside queue until admission is possible, and
that queue does not use the inside buffer. Outside arrivals and blocked transfers from upstream stations
wait in one admission line, and the station admits them in the order they asked
to enter. `arrivals` counts attempts, with
`arrivals = completed + remaining + rejected + abandoned`, where `abandoned` is
zero without patience (see Priorities and abandonment). `admitted` counts
successful admissions to the network, and `admitted_at_close` excludes later
admissions. `measurement_rejected` and `measurement_admitted` count only
rejections and admissions whose times fall in the measurement window
`[warmup, duration)`, so an outside customer who arrived before warm-up and
entered after it counts in `measurement_admitted`. `remaining_at_close` includes
unfinished outside customers, and `outside_at_close` reports them separately.
Wait and flow averages exclude rejections. Outside waiting adds to `total_wait`,
blocking is reported separately in `total_blocked`, and work in process begins
at admission. A small mean wait does not establish good service when many
customers are rejected.

#### Priorities and abandonment

A priority ranks customer types at one station (e.g., critical patients ahead
of routine ones). `priority={"Critical": 1, "Routine": 2}` maps each type to a
rank, a lower rank leaves the waiting line first, and customers of equal rank
keep the order in which they joined it. Service is not preemptive, so a server
finishes its current customer before it takes a higher-ranked one. The rank
orders only the inside waiting line, and the outside queue of a finite buffer
keeps request order, because a blocked upstream server holds its job until the
station admits it. Every type that can reach a ranked station must have a rank.

Abandonment refers to a waiting customer leaving before service (e.g., a caller
who hangs up or a patient who leaves without being seen). `patience` is a
duration, or a mapping from customer type to duration, drawn from its own
random stream at the station, and `abandon_from` is required with it.
`abandon_from="waiting"` starts the clock when the customer enters the waiting
line. `abandon_from="waiting_and_outside"` requires a finite buffer with
`external_overflow="wait"`, starts the clock when an outside arrival joins the
outside queue, and keeps it running after admission. A blocked transfer from an
upstream station starts its clock only when it enters the waiting line, since
its upstream server still holds it. A customer whose patience ends before
service starts leaves the network with status `abandoned`, and its
`abandon_time` appears in `customers` and, if it entered the waiting line, in
`visits`.

```python
import polars as pl

from flowsim import Model, exponential

model = Model()
patients = model.source(
    name="Patients",
    interarrival=exponential(mean=6),
    types={"Critical": 0.2, "Routine": 0.8},
)
doctor = model.station(
    name="Doctor",
    capacity=1,
    service_time=exponential(mean=5),
    priority={"Critical": 1, "Routine": 2},
    patience={
        "Critical": 240,
        "Routine": exponential(mean=30),
    },
    abandon_from="waiting",
)
model.route([patients, doctor, model.exit])
results = model.run(
    duration=480,
    drain=True,
)
print(
    results.summary.select(
        "arrivals",
        "completed",
        "abandoned",
        "abandonment_rate",
    )
)
waits = results.visits.group_by("customer_type").agg(pl.col("wait_time").mean())
```

At equal times, service wins, so a server that frees at the instant a
customer's patience ends serves that customer (see Event order). Abandoned
customers stay out of wait and flow averages, as rejected arrivals do, and
`arrivals = completed + remaining + rejected + abandoned`. `abandoned` counts
every abandonment, `measurement_abandoned` counts those whose times fall in
`[warmup, duration)`, and `abandonment_rate` is the share of arrivals at or
after warm-up who abandon. With `drain=False`, a customer still waiting at the
end has not abandoned, so the rate can understate abandonment. A drained run
finishes once the remaining waiting customers abandon, even at a station with
no future staffing. Thus, as with rejections, a short mean wait does not
establish good service when the abandonment rate is high.

#### Failures and repair

```python
from flowsim import Model, exponential, uniform

model = Model()
arrivals = model.source(
    name="Parts",
    interarrival=exponential(mean=5),
)
machine = model.station(
    name="Machine",
    capacity=2,
    service_time=uniform(low=4, high=8),
    time_to_failure=exponential(mean=30),
    repair_time=uniform(low=3, high=8),
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

#### Inventory and ordering

A supply chain is a sequence of stock points (i.e., stages that hold inventory)
that fill orders from stock and reorder from the next stage up the chain.
`model.demand` draws consumer demand as a quantity per review period,
`model.stock_point` defines a stage, and `model.supply` lists the chain from
demand to the top stage, which orders from a supplier with unlimited stock that
ships in the same period unless it produces at stations (see Production at
stations). A supply chain has no arrival sources, and a supply chain run does
not accept `drain=True`.

```python
from flowsim import Model, moving_average, normal, order_up_to

chain = Model(time_unit="weeks")
consumers = chain.demand(
    name="Consumers",
    per_period=normal(
        mean=100,
        sd=10,
    ),
)
stages = [
    chain.stock_point(
        name=name,
        initial=200,
        lead_time=2,
        shortage="backorder",
        policy=order_up_to(
            forecast=moving_average(window=5),
            safety_factor=0,
        ),
        forecast_from="orders",
    )
    for name in ["Retailer", "Wholesaler", "Factory"]
]
chain.supply(
    [consumers, *stages],
    period=1,
)
supply_run = chain.run(
    duration=104,
    seed=7,
    warmup=20,
)
print(supply_run.stock_points)
supply_run.plot_orders().show()
supply_run.plot_inventory().show()
supply_run.viewer("output/supply-chain.html")
```

Every stock-point argument is required, since each is a behavioral choice.
`initial` is the stock on hand at time zero, with nothing on order. `lead_time`
is the delay from the supplier's shipment to this stage's receipt, either a
constant that is a whole number of review periods or a sampling function, or
`None` for a top stage that produces at stations. `shortage` is `"backorder"`
(unfilled orders wait and ship first when stock arrives) or `"lost"` (unfilled
orders disappear, and the downstream stage stops expecting them).
`forecast_from` is `"orders"` (each stage forecasts from the orders it receives)
or `"end_demand"` (each stage forecasts from consumer demand, i.e., information
sharing).

`order_up_to` sets a target equal to cover times the moving-average forecast
plus safety stock, and each stage orders the target minus its inventory
position (on hand plus on order minus backorders), or nothing when the position
already meets the target. Cover is the number of periods of demand an order must
cover, which is `lead_time / period` for a constant lead time. A sampled lead
time requires `cover=` in `order_up_to`, since FlowSim does not estimate the
mean of a sampling function. Safety stock is `safety_factor * sqrt(cover)` times
the sample standard deviation of the demands in the forecast window, and it
stays zero until the window is full, because a deviation estimated from two or
three early observations can set a target far above steady demand. Before
`window` periods have passed, the forecast averages every observation so far.

Each review period runs from the retailer up the chain. At each stage, the
shipments due in the period arrive, backorders and then the period's incoming
orders are filled from stock, and the stage reviews its position and orders.
A stage's incoming orders are consumer demand at the retailer and, at every
other stage, the order its downstream stage placed in the same period, which
follows the model of Chen, Drezner, Ryan, and Simchi-Levi (1999). A shipment
arrives at the first review at or after its lead time, at least one period after
it was sent, and never before an earlier shipment to the same stage. Each
stage's sampled lead times come from its own random stream, and consumer demand
depends only on the seed and the demand's name, so adding a stage leaves
consumer demand unchanged.

A supply chain run fills three further tables (`inventory`, `shipments`, and
`stock_points`, described in Table columns), which `export` writes beside the
empty customer tables, and its viewer shows each stage's orders, stock, and
backorders.

Stock-point measures use review periods at or after warm-up. The bullwhip ratio
is the variance of a stage's orders divided by the variance of the orders it
receives, both with the n - 1 divisor, and it is missing when incoming orders do
not vary. The fill rate is the total units of incoming orders filled from
stock in the period they arrived divided by total incoming orders over the
measured periods, so filled backorders do not count and the rate is missing
when no orders arrived. Mean stock on hand and mean backorders average
end-of-period values with equal weight per review. Stock changes only at
reviews, so these means equal time averages when warm-up and closing fall on
review times, and a period that closing cuts short still counts as a whole
period. For independent demand, a moving average over p periods, cover L, and
no safety stock, the retailer's ratio is 1 + 2L/p + 2L^2/p^2 (Chen et al. 1999,
equation 14.8), i.e., 2.12 for p = 5 and L = 2, and the test suite checks the
simulator against this value. However, the closed form allows negative orders
and FlowSim never orders less than zero, so it applies only when demand rarely
falls far enough to call for a negative order.

#### Production at stations

A top stage with `lead_time=None` makes its orders at stations instead of
receiving them from a supplier after a stated delay, so the stations' capacity,
failures, and shifts set its lead time. Only the top stage can produce, since
every other stage orders from the stage above it. Its route leaves the stock
point and returns to it, and every station in the model must lie on that route,
because a supply chain has no arrival sources.

```python
from flowsim import Model, moving_average, order_up_to

plant = Model(time_unit="weeks")
shoppers = plant.demand(
    name="Consumers",
    per_period=lambda rng: max(0.0, rng.normal(100, 20)),
)
store = plant.stock_point(
    name="Retailer",
    initial=200,
    lead_time=2,
    shortage="backorder",
    policy=order_up_to(
        forecast=moving_average(window=5),
        safety_factor=1,
    ),
    forecast_from="orders",
)
factory = plant.stock_point(
    name="Factory",
    initial=200,
    lead_time=None,
    batch_size=25,
    shortage="backorder",
    policy=order_up_to(
        forecast=moving_average(window=5),
        safety_factor=1,
        cover=2,
    ),
    forecast_from="orders",
)
brewhouse = plant.station(
    name="Brewhouse",
    capacity=1,
    service_time=1 / 150,
)
plant.route([factory, brewhouse, factory])
plant.supply(
    [shoppers, store, factory],
    period=1,
)
plant_run = plant.run(
    duration=104,
    seed=7,
    warmup=20,
)
print(plant_run.stock_points)
print(
    plant_run.customers.select(
        "customer_id",
        "quantity",
        "arrival_time",
        "exit_time",
    )
)
print(plant_run.stations)
```

Each review's order splits into jobs of `batch_size` units, and the last job
holds the remainder (e.g., an order of 60 with a batch size of 25 makes jobs of
25, 25, and 10). A production station's `service_time` is the time per unit, so
a job's service time is its quantity times one draw, and the brewhouse above
makes 150 cases per week. A finished job enters stock at the first review at or
after it leaves the last station, and a job that finishes exactly at a review
counts at that review, since completions run before reviews at equal times.
Jobs may finish out of order at a station with several servers, and their
receipts follow the order in which they finish.

The batch size sets how units move along a line of several stations. A batch at
least as large as every order moves each order through one station at a time,
while a batch of 1 lets a downstream station start on the first unit while the
upstream station works on the rest, which shortens the lead time. For example,
an order of 4 units on two stations that each take 1/32 week per unit leaves
after 8/32 week as one job, while single units leave at 2/32, 3/32, 4/32, and
5/32 week.

A stage that produces requires `cover=` in `order_up_to`, because its lead time
comes from the stations instead of an argument. FlowSim does not estimate the
cover from observed lead times, since that would link targets to queues (i.e.,
larger targets raise orders, which lengthen queues and then raise targets
again). Jobs carry no customer type, so production stations cannot set service
times, priorities, or routes by type. They also cannot set patience or reject
outside arrivals, since an abandoned or rejected job would remove units from an
order. A finite first buffer with `external_overflow="wait"` holds released jobs
outside the line (i.e., a release queue), and `outside_wait` records how long
each job waited there.

The customers table holds one row per job, with its `quantity`, its release
time as `arrival_time`, and its finish time as `exit_time`, so `flow_time` is
the production lead time without the wait for the next review. `quantity` is
empty for customers from sources. The station, visit, activity, and summary
tables describe the production stations as they describe a service network,
and `inventory` reports what each review receives. The factory receives no
shipments, so `shipments` lists only shipments between stages. The supply
viewer adds a production section with each station's utilization, mean queue,
and mean wait, a chart of jobs waiting at a chosen station, the mean job lead
time, and a download of the jobs table.

## Analyzing results

Three calls cover the analysis of a model. `model.run(duration, seed=42, *,
warmup=0, drain=False)` simulates once and returns `Results`.
`model.experiment(duration, replications=20, seed=42, *, warmup=0, drain=False,
keep_records=True)` runs independent replications and returns an `Experiment`,
and `flowsim.compare(scenarios, duration, *, replications=20, seed=42, warmup=0,
drain=False, keep_records=True)` runs named models with matched replication
seeds and returns a `Comparison` (see Replications for `keep_records`).

Experiments and comparisons share one reporting interface, whose signature is
`intervals(metric="mean_total_wait", *, station=None, stock_point=None,
confidence=0.95)`. `plot` takes the same arguments, and `viewer(path=None, ...)`
and `export(folder, ...)` take them by keyword after the file or folder (in
`viewer`, they choose the metric and location the page shows first). The
default metric is mean total waiting time in every method. A station metric
without `station=` gives one row per station (per scenario in a comparison), a
stock-point metric without `stock_point=` gives one row per stock point, and
every interval table has a `metric` column that names the estimate. A
comparison's `differences`, `plot`, `viewer`, and `export` also take
`baseline=`, and `plot(differences=True)` draws paired differences. The Metrics
table in Reference lists every metric these methods accept.

### One run

The block below builds the two-stage network, runs one drained day, and uses
each part of `Results`.

```python
from flowsim import Model, exponential, uniform

model = Model(time_unit="minutes")
arrivals = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
)
check_in = model.station(
    name="Check-in",
    capacity=1,
    service_time=uniform(
        low=1,
        high=2,
    ),
)
service = model.station(
    name="Service",
    capacity=2,
    service_time=exponential(mean=4),
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
print(results.report())
model.diagram().show()
results.plot_queue(station="Service").show()
results.plot_wait().show()
results.plot_utilization().show()
results.plot_customer(1).show()
results.viewer("output/my-run.html")
results.export("output/my-run")
```

`results.report()` lists every replication metric that applies to the run, one
row per metric and location, with its label, value, and units. The `stations`
and `summary` tables put their headline columns first. `plot_queue()`,
`plot_wait()`, and `plot_resources()` without `station=` draw every station with
a menu that chooses among them, while `plot_utilization()` compares every
station in one chart.
`results.plot_resources()` draws each station's scheduled, available,
processing, blocked, paused, and down servers over time. The viewer includes it
when a model uses staffing schedules, finite buffers, or failures (see Model
features). These lines overlap, since a down server holding a paused job counts
as both paused and down. `results.plot_resources(stacked=True)` instead counts
each server in one layer, i.e., processing, blocked, or paused while it holds a
job, down while it is under repair without a job, and idle while it is on duty,
up, and free, and it draws the scheduled count as a dashed line over the stack.
The layers reach that line except while a server that went off duty still holds
a job or is under repair. The states table records each count on its own and
cannot say which down servers hold a job, so FlowSim rebuilds the layers from
each server's intervals in the activities and failures tables and from the
states table's scheduled count.

The viewer has linked station selection for queue histories and wait
distributions, zoom and hover controls, utilization, a customer timeline,
paginated customer records, status filtering, and CSV downloads. Below the
queue chart and the server-state chart, a box for each line shows or hides it
for every station (a click on a legend entry does the same), and a switch
redraws the server states stacked. The viewer reports unfinished customers
alongside completed-customer averages.
`results.viewer()` returns a `Viewer`, and `results.viewer("output/viewer.html")`
also saves it. A notebook displays a `Viewer` in an isolated frame, a script
calls its `open()` method to show the page in a browser, and its `html`
attribute holds the document, which the Marimo lesson passes to `mo.iframe`.
Each saved viewer embeds its Plotly library and data, so it opens directly in a
browser without internet access.

FlowSim writes a file only when a call asks for one. `save(path)`,
`export(folder)`, and the path argument of `viewer()` and `builder()` write
where the path says, and `open()` on a saved page writes it again at its saved
path. `open()` on a page that was never saved writes one file per kind of page
in `output/` under the current working directory, as the table below shows, and
each call replaces that file and prints its path. FlowSim writes no other
files, since a run's records live in memory and inside each saved page. Thus,
when every path a script names lies under `output/` (as in every example in
this README), deleting `output/` removes everything FlowSim's Python calls
wrote. The CSV, JSON, and `.py` downloads that a page offers are written by the
browser, which saves them to its own download folder.

| Page | File that `open()` writes before any save |
| --- | --- |
| `results.viewer()` for a service network | `output/flowsim-results.html` |
| `results.viewer()` for a supply chain | `output/flowsim-supply-chain.html` |
| `experiment.viewer()` | `output/flowsim-experiment.html` |
| `comparison.viewer()` | `output/flowsim-comparison.html` |
| `flowsim.builder()` | `output/flowsim-builder.html` |

`results.export("output/my-run")` writes seven CSV files and one metadata file.
Exports keep missing starts and exits as empty CSV fields and never replace an
unknown outcome with zero. An export also removes FlowSim files that an earlier
export left in the same folder and this one does not write, and it leaves other
files alone. An export refuses a folder that holds files with FlowSim's export
names but no FlowSim `metadata.json`, and the error names those files, so it
never overwrites or deletes data FlowSim did not write. Table columns in
Reference lists every column of these files.

| File | Contents |
| --- | --- |
| `customers.csv` | Each customer's source, type, production quantity, system arrival, admission, exit or abandonment, flow time, observed total wait and blocking, final status, and current station. |
| `visits.csv` | Each station visit's customer type, arrival, service start, processing completion, departure or abandonment, server identity, waiting, blocking, and sampled service requirement. |
| `states.csv` | Station queue and server counts after each time with a state change, plus closing and the end of service. |
| `stations.csv` | Station counts, wait summaries, time-weighted queue lengths, and utilization. |
| `summary.csv` | System counts at closing and after service, rejections and abandonments, overtime, completed flow-time averages, throughput, and time-average work in process. |
| `activities.csv` | Each customer's processing, paused, and blocked intervals by server. Intervals of zero length are omitted. |
| `failures.csv` | Per-server failure times, sampled lifetimes, repair requirements, and observed repair ends. The file has only a header when no station fails. |
| `metadata.json` | The FlowSim version, run settings (time unit, duration, warm-up, seed, drain), end time, capacities, per-node settings, routes, and text definitions of the measurement windows and cohorts. |

### Replications

`model.experiment` runs independent replications with distinct seeds derived
from one seed and, by default, keeps each run's raw records in `experiment.runs`.

```python
from flowsim import Model, exponential, uniform

model = Model(time_unit="minutes")
arrivals = model.source(
    name="Customers",
    interarrival=exponential(mean=3),
)
check_in = model.station(
    name="Check-in",
    capacity=1,
    service_time=uniform(
        low=1,
        high=2,
    ),
)
service = model.station(
    name="Service",
    capacity=2,
    service_time=exponential(mean=4),
)
model.route([arrivals, check_in, service, model.exit])
experiment = model.experiment(
    duration=480,
    replications=20,
    seed=42,
    drain=True,
)
print(experiment)
print(experiment.intervals())
print(experiment.intervals("mean_wait"))
experiment.plot(
    "utilization",
    station="Service",
).show()
experiment.viewer("output/experiment.html")
experiment.export("output/experiment")
```

`intervals` estimates a Student t confidence interval across run-level values.
A station metric gives one row per station unless `station=` names one, and a
system metric gives one row. Missing run values are excluded and counted in
`observed_runs`. These intervals describe the finite-run statistic under the
selected stopping rule, so they do not establish steady-state performance, and
intervals from undrained runs do not correct the missing-outcome bias described
in Measurement rules. The seed argument seeds one NumPy `SeedSequence`, which
spawns each replication's seed, so replication 1 does not repeat
`model.run(seed=42)`. Repeated experiments with the same seed and model
reproduce results in the locked environment. Each node's random streams depend
only on the seed and the node's name, so adding, removing, or capacity-changing
another node leaves a node's own draws unchanged, while renaming a node gives it
new streams. An experiment's export writes `runs.csv` (the stacked summary
tables), `stations.csv`, `stock_points.csv` for a supply chain, `intervals.csv`
for the requested metric, and `metadata.json`.

`experiment.viewer()` returns a page with a menu of every replication metric
that applies to the model (from `flowsim.metrics()`), and for a station or
stock-point metric a second menu chooses the location. For the chosen metric,
the page shows the interval chart and table and a chart of each replication's
value. Selecting a replication's point, or choosing the run from the menu below
the chart, opens that run's single-run view on the same page, i.e., its queues,
waits, utilization, server states (with the line boxes and stacked switch), and
customer timeline, or the supply-chain view for a supply chain. The page embeds
Plotly once and every run's records, so its size grows with the number of runs
(see Scope and limits).

`keep_records=False` drops each run's raw records (customers, visits, states,
activities, failures, inventory, and shipments) once the run's measures are
computed, which keeps memory low for long runs or many replications. The
experiment's tables, intervals, plots, and export are unchanged, and its viewer
shows the overview without opening single runs, while a single run's plots,
viewer, and export then raise an error that names the argument. `flowsim.compare` accepts the same argument.

### Scenario comparisons

`compare` runs named models with the same replication seeds and pairs their
results by replication.

```python
import polars as pl

from flowsim import Model, compare, exponential, uniform


def service_network(servers):
    model = Model(time_unit="minutes")
    arrivals = model.source(
        name="Customers",
        interarrival=exponential(mean=3),
    )
    check_in = model.station(
        name="Check-in",
        capacity=1,
        service_time=uniform(
            low=1,
            high=2,
        ),
    )
    service = model.station(
        name="Service",
        capacity=servers,
        service_time=exponential(mean=4),
    )
    model.route([arrivals, check_in, service, model.exit])
    return model


comparison = compare(
    scenarios={
        "One server": service_network(1),
        "Two servers": service_network(2),
        "Three servers": service_network(3),
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
on_time = comparison.summary.group_by(
    "scenario",
    maintain_order=True,
).agg((pl.col("overtime") <= 30).sum().alias("days_finished_on_time"))
print(comparison.intervals().join(on_time, on="scenario"))
comparison.plot(metric="overtime").show()
comparison.plot(
    metric="overtime",
    differences=True,
).show()
comparison.viewer("output/comparison.html")
comparison.export("output/comparison")
```

`intervals()` reports each scenario's mean, confidence limits, and number of
observed runs. `differences()` subtracts the baseline scenario (the first
scenario unless `baseline=` names another) within each matched replication, then
estimates a Student t interval across those paired differences. A missing value
excludes that pair and reduces `observed_runs`. Compared models must declare the
same time unit, and a named station must exist in every scenario. Replication
identity and seed matching are checked before paired differences are
calculated. Matching seeds give each node the same draws in every scenario that
keeps its name, so a source's arrivals match across scenarios. They do not
guarantee that each customer receives the same service draws when the network
structure or the order of upstream completions changes, because a station draws
in the order customers reach it.

`comparison.summary`, `comparison.stations`, and `comparison.stock_points` stack
every scenario's runs with `scenario` and `replication` columns. Thus, a Polars
`group_by` and `join` give per-scenario measures that no interval reports, such
as the count of days that finish within 30 minutes of closing above. The intervals
are nominal for each reported metric or contrast, i.e., they are not
simultaneous confidence bounds across every scenario and metric.

`comparison.viewer()` returns the same page as `experiment.viewer()` with a
third menu that chooses the baseline. For the chosen metric, location, and
baseline, it shows each scenario's interval, the paired differences from the
baseline, and each scenario's value in each replication, and selecting a
scenario's replication opens that run on the page. The arguments choose the
first view (e.g., `viewer(metric="overtime", baseline="Two servers")`), and a
scenario without the chosen station has no row for it. Comparison exports contain
per-replication system and station metrics (and stock-point metrics for supply
chains), scenario intervals, paired differences, and metadata. Raw customer
records remain in `comparison.experiments[scenario].runs`, and each run has its
own `export()`.

## Fitting durations to data

`fit_all(data)` fits five families to a sample of durations by maximum
likelihood, i.e., exponential, gamma, lognormal, and Weibull, each starting at
zero since a duration cannot be negative, and normal. It ranks the fits by AIC,
i.e., 2k minus twice the log-likelihood, where k counts the fitted parameters,
so a family with more parameters must earn its extra flexibility. Each fit also
shows the Kolmogorov-Smirnov (KS) statistic, i.e., the largest vertical gap
between the data's empirical CDF and the fitted CDF, and `p_negative`, the
fitted chance of a draw below zero. The fits use no random draws, so the
ranking is the same on every run.

```python
import numpy as np

from flowsim import Model, best_fit, exponential, fit_all

observed = np.random.default_rng(7).gamma(
    shape=4,
    scale=1.5,
    size=200,
)
fits = fit_all(observed)
print(fits)
print(fits.table.select("rank", "family", "mean", "sd", "aic", "ks"))

model = Model(time_unit="minutes")
jobs = model.source(
    name="Jobs",
    interarrival=exponential(mean=8),
)
machine = model.station(
    name="Machine",
    capacity=1,
    service_time=fits.best,
)
model.route([jobs, machine, model.exit])
fitted_run = model.run(
    duration=480,
    seed=42,
)
print(fitted_run.stations.select("station", "mean_wait", "utilization"))
print(best_fit(observed))
```

`fits.best` is the top-ranked fit whose chance of a negative draw is at most
one in a million, so a normal fitted to short times is skipped instead of
stopping a run with a negative duration. A fit is itself a distribution. It
works as `service_time=` or `interarrival=`, draws exactly what its fitted
distribution draws (e.g., `gamma(shape=4.39, scale=1.26)`), and lists its
parameters by name in `fit.params`. `best_fit(data)` returns `fits.best` in one
call. `fits.pick("lognormal")` or `fits.pick(2)` chooses another fit by family
name or rank, `fits.table` lists every fit with its mean, sd, AIC, KS, and
named parameters, `fits.failed` lists each family that did not fit and why, and
`fits.plot()` draws the fitted densities over a histogram of the data beside
the fitted and empirical CDFs. The ranking compares only the candidate
families, so a first rank does not show that a family fits well, and the plot
is the check on fit quality.

`FAMILIES` is the default search. Passing `families=` fits a different list,
and `ALL_FAMILIES` adds uniform, triangular, and beta, which are fitted only
when named because their fitted endpoints hug the sample's minimum and maximum,
so they win on data from unrelated families and never draw beyond the observed
range. `shifted=True` also fits a minimum time (a location) for the four
families that otherwise start at zero. A shifted gamma, lognormal, or Weibull
whose minimum time reaches the smallest observation appears in `fits.failed`,
since its likelihood grows without bound there (e.g., most shifted lognormal
fits to ten or fewer values). Times recorded to the nearest minute produce ties
and exact zeros, and a warning says the values look rounded. A
zero value leaves gamma, lognormal, and Weibull starting at zero without a
finite likelihood, so they appear in `fits.failed`. When no family fits,
`empirical(data)` resamples the observed values instead. For whole-number
demand counts, `fit_all(counts, discrete=True)` fits Poisson and negative
binomial distributions, the second for counts more variable than Poisson.

## Example studies

The `examples/` folder holds the studies below, and each runs from one Pixi
task (see Tasks).

### Classroom exercise

The service-day exercise uses the two-stage network from Building models.
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

### Operations examples

`examples/operations.py` holds two multi-stage models from manufacturing and
logistics, each with a scenario study. `pixi run operations` writes their
comparison reports, one viewer per study, and the network diagrams under
`output/operations/`.

#### Machining line

The machining line runs blanks through a saw, two CNC machines, a washer, two
assembly fitters, and a packer during a 480-minute shift. Blanks are released
every 2 minutes, which is faster than the line can work, and the saw has
`buffer=0` with `external_overflow="wait"`, so unsawn blanks wait outside the
line as raw stock. This pattern keeps the line saturated (i.e., it never
starves for blanks), so the parts completed by closing measure one shift's
output from an empty line. The video
[FlowSim: modeling a machining line](https://youtu.be/jWuCiGMI9fU) walks
through this model and its scenario study.
Raw stock counts toward flow time and `remaining_at_close`, so the study reports
`completed_at_close`, and work in process (`mean_wip`) begins only at admission
to the saw. The CNC machines fail on a busy clock, and assembly drops to one
fitter for a lunch hour.

`BUFFER_PLANS` gives the waiting spaces in front of the CNC, washer, assembly,
and packing stations, and `line_study` compares the plans with a fourth
scenario that removes the CNC failures. In the saved study, two spaces in front
of each station add more than ten parts per shift relative to no buffers,
moving those spaces in front of assembly changes output by less than one part,
and removing the CNC failures adds about as many parts again. The CNC machines
are the bottleneck, so buffers help where they keep the CNC from blocking or
starving, and failures at the bottleneck cost about as much as removing every
buffer.

#### Truck cross-dock

The cross-dock receives inbound trucks at time-varying rates for 960 minutes.
Two gate lanes check trucks in, and the gate has `buffer=0` with
`external_overflow="wait"`, so trucks that find both lanes busy queue on the
access road. Checked-in trucks wait in a yard (the unload station's buffer) for
one of six dock doors, whose crews follow a shift plan. A full yard holds trucks
in the gate lanes (blocking after service), which lengthens the road queue. The
sorter fails while running, three quarters of loads go to outbound trailers,
and the rest go to storage.

`dock_study` serves every truck (`drain=True`) and compares eight doors and a
yard of 20 spaces with the base case. In the saved study, eight doors shorten
the mean flow time by about 8 minutes, while the larger yard leaves it
unchanged, i.e., trucks move off the road and into the yard, but the doors
still unload them at the same times. Each study also prints intervals for
`mean_outside_wait` and `mean_total_blocked`, which show whether a scenario's
queue sits on the access road or in gate lanes blocked by a full yard.

Both models simplify their settings. Each truckload remains one job from gate
to exit, since FlowSim cannot split a load into pallets or combine pallets into
an outbound trailer, and every blank follows the same routing.

### Supply chain example

`examples/supply_chain.py` builds a four-stage chain in the style of the beer
game (i.e., a retailer, wholesaler, distributor, and factory, each ordering from
the next) and studies the bullwhip effect. Consumer demand averages 100 cases
per week with a standard deviation of 20, every stage receives shipments two
weeks after they are sent, and each stage carries one standard deviation of
safety stock. `bullwhip_study` runs 20 replications of 104 weeks with a 20-week
warm-up and compares forecasting from orders with sharing consumer demand and
with a ten-week moving average. `pixi run supply-chain` writes the comparison
report, the per-replication stock-point table, the first replication's records
and viewer, and the chain's diagram (`network.html`, drawn by
`model.diagram()`) under `output/supply_chain/`. The video
[FlowSim: the bullwhip effect](https://youtu.be/Eir_tSuytso) walks through this
study.

`capacity_study` replaces the factory's two-week lead time with a brewhouse
that makes 120, 150, or 200 cases per week in jobs of 25 cases, with a target
that covers two weeks of forecast demand, and a fifth scenario brews 150 cases
per week with three weeks of cover. `pixi run supply-chain` writes its report
and the diagram of the chain with the brewhouse below the factory under
`output/supply_chain/capacity/`.

In the saved bullwhip study, forecasting from orders gives a retailer bullwhip
ratio of 2.25 (95% CI 2.18 to 2.32), above the closed-form 2.12 because safety
stock estimated from five weeks of demand also varies. The ratios compound up
the chain, so factory orders vary 37.6 times as much as consumer demand. Sharing
consumer demand leaves the retailer unchanged, since the retailer already sees
that demand, and lowers the factory's own ratio by 0.89 (95% CI 0.77 to 1.00),
which cuts factory order variance to 9.7 times consumer demand. A ten-week
average damps every stage (factory order variance 8.6 times consumer demand) and
raises the retailer's fill rate from 87.0% to 91.4%. Sharing instead lowers the
retailer's fill rate to 84.4%, since the wholesaler then plans its stock from
consumer demand while still filling the retailer's more variable orders, and its
own fill rate falls from 83.4% to 77.9%. Thus, sharing demand removes most of
the amplification between stages, but the stages that receive the shared data
still need stock sized to the orders they actually fill.

In the saved capacity study, the factory fills 83.8% of its incoming orders in
the same week with a two-week lead time (95% CI 82.4% to 85.3%). Brewing 120
cases per week lowers that fill rate to 76.5%, since a job then takes 2.29 weeks
on average from its order to its finish, and brewing 150 or 200 cases per week
raises it to 88.3% and 94.2% with mean job times of 1.49 and 0.92 weeks. The
factory's bullwhip ratio is 2.32 in all four scenarios, because the inventory
position counts units on order, so receipts never change it, and the factory
places the same orders however soon they arrive. Three weeks of cover at 150
cases per week raises the fill rate to 97.1% but also raises the factory's
bullwhip ratio to 2.76 (95% CI 2.61 to 2.91), and the mean job time rises from
1.49 to 1.71 weeks with those more variable orders. Thus, capacity above mean
demand (120 cases is 20% above it) is not enough when orders arrive amplified,
and a longer cover buys service with more variable orders.

Each stage starts with 200 cases on hand and nothing on order, so the first
weeks carry a startup surge of orders that the warm-up excludes. The orders
chart in the viewer scales to the measured weeks, and double-clicking it shows
the surge.

## Reference

This section lists the replication metrics and every table column, both
generated from the catalog in `flowsim/catalog.py`, and then states the
measurement rules and the order of simultaneous events.
`tests/test_readme.py` checks that the two generated listings match the catalog.

### Metrics

The table below lists the metrics that `intervals`, `differences`, and `plot`
accept. System metrics come from `summary`, and station metrics come from
`stations`. Stock-point metrics come from `stock_points`, and their interval
tables name the stage in a `stock_point` column instead of `station`. An
experiment or comparison reports a station metric for every station unless
`station=` names one, and a stock-point metric for every stage unless
`stock_point=` names one. The window column names the period or cohort each
metric measures (see Measurement rules), and a time metric's units are the
model's time unit.

<!-- metrics table start -->
| Metric | Scope | Units | Window | Meaning |
| --- | --- | --- | --- | --- |
| `mean_total_wait` | System | time unit | arrivals at or after warmup with observed exits | Mean total time that a completed customer waited before service, summed over its stations and including any wait outside the first station. |
| `mean_flow_time` | System | time unit | arrivals at or after warmup with observed exits | Mean time from system arrival to exit for completed customers. |
| `throughput` | System | customers per time unit | [warmup, duration) | Customers who exit during the operating window, whenever they arrived, divided by the window's length. |
| `remaining_at_close` | System | count | at closing | Customers who were not rejected and had neither exited nor abandoned before closing, including customers still waiting outside the first station. |
| `completed_at_close` | System | count | before closing | Customers who exit before closing, whenever they arrived. |
| `remaining` | System | count | at the end of the run | Customers who were not rejected and had neither completed nor abandoned when the run ended. |
| `overtime` | System | time unit | whole run | Time from closing to the end of the run, i.e., end_time minus duration, which is zero in a run that is not drained and in a drained run whose customers all finish by closing. |
| `mean_wip` | System | count | [warmup, duration) | Time-average number of admitted customers in the system, which excludes customers still waiting outside the first station. |
| `rejected` | System | count | whole run | Arrivals that were rejected on arrival. |
| `admitted` | System | count | whole run | Customers admitted to the first station, including admissions after closing. A customer routed from the source straight to the exit counts as admitted on arrival. |
| `measurement_rejected` | System | count | [warmup, duration) | Arrivals at or after warmup that were rejected on arrival. |
| `measurement_admitted` | System | count | [warmup, duration) | Customers admitted to the first station during the operating window. |
| `abandonment_rate` | System | share | arrivals at or after warmup, including rejected arrivals | Share of arrivals at or after warmup, counting rejected arrivals in the denominator, who abandoned at any time in the run, including after closing in a drained run. |
| `mean_total_blocked` | System | time unit | arrivals at or after warmup with observed exits | Mean time that a completed customer was held at a station after service because the next station could not accept it. |
| `mean_outside_wait` | System | time unit | arrivals at or after warmup with observed exits | Mean time that a completed customer waited outside the first station before admission, which is zero when it was admitted on arrival. |
| `arrivals` | System | count | whole run | Customers who arrived during the run, including rejected arrivals. |
| `admitted_at_close` | System | count | before closing | Customers admitted to the first station before closing. |
| `outside_at_close` | System | count | at closing | Customers who were not rejected and had neither been admitted nor abandoned before closing, so they were waiting outside the first station. |
| `abandoned` | System | count | whole run | Customers who left without service, including abandonments after closing. |
| `completed` | System | count | at the end of the run | Customers who completed service, including completions after closing when the run continues past it. |
| `after_close_completions` | System | count | at or after closing | Customers who exit at or after closing, during the continuation of a drained run. |
| `end_time` | System | time unit | whole run | Simulation time at which the run stopped, which is the closing time in a run that is not drained and, in a drained run, the later of closing and the last exit or abandonment. |
| `measurement_arrivals` | System | count | [warmup, duration) | Arrivals at or after warmup, including rejected arrivals, which form the denominator of the abandonment rate. |
| `measurement_abandoned` | System | count | [warmup, duration) | Customers whose abandonment time falls in the operating window. |
| `cohort_arrivals` | System | count | arrivals at or after warmup | Customers who arrived at or after warmup and were not rejected, whose completed members form the cohort behind the flow-time and total-wait averages. |
| `measurement_completions` | System | count | [warmup, duration) | Customers who exit during the operating window, which is the numerator of throughput. |
| `cohort_completions` | System | count | arrivals at or after warmup with observed exits | Members of the arrival cohort whose exits were observed. |
| `cohort_remaining` | System | count | arrivals at or after warmup | Members of the arrival cohort who had neither completed nor abandoned when the run ended. |
| `mean_wait` | Station | time unit | visits admitted at or after warmup with observed starts | Mean time from a visit's admission to the station's line until its service started, which excludes time spent outside a full finite buffer or blocked upstream and excludes visits that abandoned or had not started. |
| `mean_queue` | Station | count | [warmup, duration) | Time-average number of customers waiting in the station's line, excluding customers waiting outside a finite buffer. |
| `utilization` | Station | share | [warmup, duration) | Occupied-server time as a share of installed capacity times the window length, where an occupied server holds a job that is processing, paused, or blocked. |
| `p95_wait` | Station | time unit | visits admitted at or after warmup with observed starts | The 95th percentile of the run's observed visit waits, interpolated linearly between the two nearest order statistics, so an interval across replications estimates the expected run-level 95th percentile and not the 95th percentile of all customers' waits pooled. |
| `processing_utilization` | Station | share | [warmup, duration) | Server time spent processing as a share of installed capacity times the window length. |
| `blocking_fraction` | Station | share | [warmup, duration) | Server time spent blocked as a share of installed capacity times the window length. |
| `downtime_fraction` | Station | share | [warmup, duration) | Server time spent down as a share of installed capacity times the window length, which can overlap paused and blocked time and so must not be added to the other shares. |
| `staffed_utilization` | Station | share | [warmup, duration) | Server time spent processing as a share of available-server time, which is missing when no server was available at any time in the window. |
| `mean_scheduled_servers` | Station | servers | [warmup, duration) | Time-average number of servers on duty under the staffing schedule, which equals the capacity at a station without a staffing schedule and includes servers that are down. |
| `mean_available_servers` | Station | servers | [warmup, duration) | Time-average number of servers that are on duty and not down, plus off-duty servers that are not down and are finishing a job at a station whose shifts end with shift_end='finish'. |
| `mean_outside_queue` | Station | count | [warmup, duration) | Time-average number of arriving customers waiting outside the station's full finite buffer for admission, which excludes upstream customers blocked from entering. |
| `max_queue` | Station | count | [warmup, duration) | Largest number of customers waiting in the station's line, ignoring states that last zero time. |
| `service_starts` | Station | count | [warmup, duration) | Services that start at the station during the operating window. |
| `service_completions` | Station | count | [warmup, duration) | Services whose processing ends at the station during the operating window, before any blocked time. |
| `wait_arrivals` | Station | count | visits admitted at or after warmup | Visits admitted to the station's line at or after warmup, which form the cohort behind the wait averages and include visits after closing when a drained run continues. |
| `wait_observations` | Station | count | visits admitted at or after warmup with observed starts | Visits in the wait cohort whose service start was observed. |
| `waiting_at_close` | Station | count | at closing | Customers waiting in the station's line at closing, including customers who arrived before warmup. |
| `occupied_at_close` | Station | servers | at closing | Servers holding a job at closing, whether processing, paused, or blocked, so the count includes blocked_at_close and paused_at_close. |
| `waiting_at_end` | Station | count | at the end of the run | Customers waiting in the station's line when the run ended. |
| `occupied_at_end` | Station | servers | at the end of the run | Servers holding a job when the run ended, whether processing, paused, or blocked. |
| `blocked_at_close` | Station | servers | at closing | Servers holding a finished job that the next station could not accept at closing. |
| `paused_at_close` | Station | servers | at closing | Servers holding a job whose work was paused at closing because the server was down or off duty. |
| `bullwhip_ratio` | Stock point | variance ratio | review periods at or after warmup | Sample variance of the quantities the stock point ordered divided by the sample variance of its incoming orders, which is missing with fewer than two periods or constant incoming orders. |
| `fill_rate` | Stock point | share | review periods at or after warmup | Total units of incoming orders filled from stock in the period they arrived divided by total incoming orders over the measured periods, so filled backorders do not count and the rate is missing when no orders arrived. |
| `mean_on_hand` | Stock point | units | review periods at or after warmup | Mean stock on hand after each review's receipts and shipments, a level that holds until the next review, over the review periods at or after warmup. |
| `mean_backorders` | Stock point | units | review periods at or after warmup | Mean backorders after each review's receipts and shipments, a level that holds until the next review, over the review periods at or after warmup. |
| `lost_units` | Stock point | units | review periods at or after warmup | Total units of incoming orders lost, which is zero unless the stock point's shortage rule is 'lost'. |
| `mean_demand` | Stock point | units | review periods at or after warmup | Mean incoming orders per review period, which are consumer demand at the retailer and the downstream stage's order at every other stage. |
| `mean_order` | Stock point | units | review periods at or after warmup | Mean quantity that the stock point ordered per review period. |
| `demand_variance` | Stock point | squared units | review periods at or after warmup | Sample variance of incoming orders per review period, with the n - 1 divisor. |
| `order_variance` | Stock point | squared units | review periods at or after warmup | Sample variance of the quantities ordered per review period, with the n - 1 divisor. |
<!-- metrics table end -->

### Table columns

Each table's columns are listed below with their units and meanings. The
`summary`, `stations`, and `stock_points` tables also hold every metric of their
scope from the table above, so only their other columns appear here, and
`summary` has none. A unit of "metric units" means the units of the requested
metric, and "data unit" means the units of the fitted data.

<!-- column tables start -->
<details>
<summary><code>customers</code>: results.customers, one row per customer</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `customer_id` | id | Identifier of the customer, unique within a run. |
| `source` | label | Name of the source that created the customer, or of the stock point that released the production job. |
| `customer_type` | label | Customer type, empty for a production job or a customer from a source without types. |
| `quantity` | units | Units in a production job, empty for a customer from a source. |
| `arrival_time` | time unit | Time the customer arrived in the system. |
| `exit_time` | time unit | Time the customer left the network, empty if it did not complete. |
| `abandon_time` | time unit | Time the customer abandoned before service, empty if it did not abandon. |
| `flow_time` | time unit | Time from arrival to exit, empty if the customer did not exit. |
| `total_wait` | time unit | Total of the customer's completed waits before service, including any wait outside the first station. |
| `total_blocked` | time unit | Total time the customer was held at a station after service because the next station could not accept it, counting only blocking that had ended. |
| `admitted` | true/false | Whether the customer was admitted to the first station. A customer routed from the source straight to the exit counts as admitted on arrival. |
| `admission_time` | time unit | Time the customer was admitted to the first station, empty if never admitted. |
| `outside_wait` | time unit | Time from arrival to admission, which is zero for a customer admitted on arrival and empty for a customer never admitted. |
| `status` | label | The customer's status at the end of the run: outside, waiting, in_service, blocked, paused, rejected, abandoned, or completed. |
| `station` | label | Station where the customer was at the end of the run, or where it was rejected or abandoned, empty for a completed customer. |

</details>

<details>
<summary><code>visits</code>: results.visits, one row per station visit</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `customer_id` | id | Identifier of the visiting customer. |
| `source` | label | Name of the source that created the customer, or of the stock point that released the production job. |
| `customer_type` | label | Customer type, empty for a production job or a customer from a source without types. |
| `station` | label | Station that was visited. |
| `arrival_time` | time unit | Time the customer entered the station's line, which follows its system arrival when it waited outside a full finite buffer and follows its upstream service end when it was blocked upstream. |
| `service_start` | time unit | Time service started, empty if it never started. |
| `service_end` | time unit | Time processing finished, so service_end minus service_start includes any paused time, empty if processing had not finished. |
| `departure_time` | time unit | Time the customer left the station, which can be later than service_end because of downstream blocking, empty if the customer had not left or abandoned the line. |
| `abandon_time` | time unit | Time the customer abandoned this station's line, empty if it did not. |
| `server_id` | id | Server that served the visit, empty if service never started. |
| `blocked_time` | time unit | Time the customer was held after service until departure, empty if not observed. |
| `wait_time` | time unit | Time from arrival at the station to the start of service, empty if service never started. |
| `service_time` | time unit | Sampled service requirement, i.e., the per-unit draw times the job's quantity for a production job, which is not elapsed busy time and can extend beyond the run limit. |

</details>

<details>
<summary><code>states</code>: results.states, one row per station and recorded time</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `station` | label | Station the row describes. |
| `time` | time unit | Time of the row, i.e., the start of the run, a time when the station's state changed, closing, or the end of the run, and the row holds the state after every event at that time. |
| `waiting` | count | Customers waiting in the station's line after the change. |
| `busy` | servers | Servers holding a job that is processing, paused, or blocked. |
| `processing` | servers | Servers actively processing a job. |
| `blocked` | servers | Servers holding a finished job that the next station cannot accept. |
| `paused` | servers | Servers holding a job whose work is paused because the server was down or off duty. |
| `down` | servers | Servers that are down for repair. |
| `scheduled` | servers | Servers on duty under the staffing schedule, which equals the capacity at a station without a staffing schedule and includes servers that are down. |
| `available` | servers | Servers that are on duty and not down, plus off-duty servers that are not down and are finishing a job when shift_end is 'finish'. |
| `outside` | count | Arriving customers waiting outside the station's full finite buffer for admission, which excludes upstream customers blocked from entering. |

</details>

<details>
<summary><code>activities</code>: results.activities, one row per processing, paused, or blocked interval</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `customer_id` | id | Identifier of the customer served. |
| `station` | label | Station where the interval occurred. |
| `server_id` | id | Server that held the job during the interval. |
| `state` | label | Server phase during the interval: processing, blocked, or paused. |
| `start` | time unit | Start of the interval. |
| `end` | time unit | End of the interval, empty if it was still open at the end. |

</details>

<details>
<summary><code>failures</code>: results.failures, one row per server failure</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `station` | label | Station of the failed server. |
| `server_id` | id | Server that failed. |
| `failure_time` | time unit | Time the server failed. |
| `time_to_failure` | time unit | Sampled lifetime, counted only while the failure clock runs, so it can be shorter than the time elapsed since the previous repair ended. |
| `repair_time` | time unit | Sampled repair requirement. |
| `repair_end` | time unit | Time the repair finished, empty if it was not observed. |

</details>

<details>
<summary><code>inventory</code>: results.inventory, one row per stock point and review period</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `stock_point` | label | Stock point the row describes. |
| `period` | index | Review period number, counted from zero. |
| `time` | time unit | Time of the review. |
| `received` | units | Units added to stock at the review, from shipments due by this period and, at a producing stage, jobs finished since the previous review. |
| `demand` | units | Incoming orders in the period. |
| `filled` | units | Units of the period's incoming orders filled from stock in the same period. |
| `shipped` | units | Units shipped downstream in the period, including filled backorders. |
| `lost` | units | Units of incoming orders lost in the period. |
| `on_hand` | units | Stock on hand at the end of the period, after the review's order. |
| `backorders` | units | Backorders at the end of the period. |
| `on_order` | units | Units ordered but not yet received, recorded after this stage's order, so an order that the stage above loses later in the same review still counts. |
| `position` | units | Inventory position after this stage's order, i.e., on hand plus on order minus backorders, with on order as recorded in that column. |
| `forecast` | units | One-period forecast used for the order, i.e., the moving average of incoming orders, or of consumer demand when forecast_from is 'end_demand', including this period. |
| `target` | units | Order-up-to target used for the period's order. |
| `order_quantity` | units | Quantity ordered at the period's review. |

</details>

<details>
<summary><code>shipments</code>: results.shipments, one row per shipment</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `sender` | label | Stage that shipped, or Supplier for orders of a top stage that does not produce. |
| `receiver` | label | Stage that receives the shipment. |
| `quantity` | units | Units shipped. |
| `ship_time` | time unit | Time the shipment was sent. |
| `lead_time` | time unit | Lead time of the shipment, constant or sampled, which can be shorter than arrival_time minus ship_time because a shipment arrives only at a review and never before an earlier shipment to the same stage. |
| `arrival_time` | time unit | Time the shipment arrived, empty if it was still in transit at the end. |

</details>

<details>
<summary><code>stations</code>: results.stations, one row per station</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `station` | label | Station the row describes. |
| `capacity` | servers | Number of installed servers at the station. |
| `arrivals` | count | Visits admitted to the station's line in [warmup, duration), which excludes rejected arrivals and customers still waiting outside. |
| `outside_at_close` | count | Arriving customers waiting outside the station's full finite buffer for admission at closing, which excludes upstream customers blocked from entering. |

</details>

<details>
<summary><code>stock_points</code>: results.stock_points, one row per stock point</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `stock_point` | label | Stock point the row describes. |
| `periods` | count | Review periods at or after warmup. |

</details>

<details>
<summary><code>intervals</code>: intervals() and differences(), one row per scenario and location</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `scenario` | label | Scenario that the interval describes. |
| `baseline` | label | Baseline scenario that the difference is measured against, in the differences table only. |
| `station` | label | Station the metric was measured at, empty for a system metric and absent from the tables of stock-point metrics. |
| `stock_point` | label | Stock point the metric was measured at, a column that only the tables of stock-point metrics have, in place of station. |
| `metric` | label | Name of the replication metric. |
| `runs` | count | Replications run. |
| `observed_runs` | count | Replications with a finite value, or, in the differences table, matched pairs whose difference is finite, which are the ones the interval uses. |
| `mean` | metric units | Mean of the run-level values, or of the paired differences in the differences table. |
| `lower` | metric units | Lower limit of the Student t confidence interval, empty when fewer than two runs are observed. |
| `upper` | metric units | Upper limit of the Student t confidence interval, empty when fewer than two runs are observed. |
| `confidence` | share | Confidence level of the interval. |

</details>

<details>
<summary><code>pooled</code>: columns that experiments and comparisons add to stacked tables</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `replication` | index | Replication number within an experiment, counted from one. |
| `scenario` | label | Scenario name in a comparison's pooled tables. |

</details>

<details>
<summary><code>fits</code>: fits.table, one row per fitted family</summary>

| Column | Units | Meaning |
| --- | --- | --- |
| `rank` | count | Position by AIC, where one is the best fit. |
| `family` | label | Family name. |
| `description` | label | Plain-language description of the fitted distribution with its parameters, including any shift and a warning when draws can be negative. |
| `mean` | data unit | Mean of the fitted distribution. |
| `sd` | data unit | Standard deviation of the fitted distribution. |
| `p_negative` | share | Chance that a draw from the fitted distribution is below zero. |
| `aic` | dimensionless | Akaike information criterion, 2k - 2 log-likelihood for k fitted parameters, where lower is better. |
| `ks` | share | Kolmogorov-Smirnov statistic, the largest vertical gap between the data's empirical CDF and the fitted CDF, empty for count fits. |
| `shape` | dimensionless | Shape parameter of a gamma or Weibull fit before any shift. |
| `scale` | data unit | Scale parameter of a gamma or Weibull fit before any shift. |
| `low` | data unit | Lower end of a uniform, triangular, or beta fit before any shift, so the fitted lower end is low plus by when by is present. |
| `mode` | data unit | Mode of a triangular fit before any shift, so the fitted mode is mode plus by when by is present. |
| `high` | data unit | Upper end of a uniform, triangular, or beta fit before any shift, so the fitted upper end is high plus by when by is present. |
| `a` | dimensionless | First shape parameter of a beta fit. |
| `b` | dimensionless | Second shape parameter of a beta fit. |
| `by` | data unit | Shift added to a shifted fit, so the unshifted mean is mean minus by. |

</details>
<!-- column tables end -->

### Measurement rules

Arrivals occur in `[0, duration)`. With the default `drain=False`, service also
stops at `duration`, excluding events exactly at that time, and the records of
customers still waiting or in service remain in the results. With `drain=True`,
arrivals stop at `duration`, and the run includes events exactly at closing and
continues until every customer who was not rejected has completed service or
abandoned. `end_time` is the closing time in a run that is not drained and, in a
drained run, the later of closing and the last exit or abandonment, and
`overtime` is `end_time - duration` (zero in a run that is not drained and in a
drained run whose customers all finish by closing). The state trace includes the
continuation, and the viewer marks closing with a dashed line.

Queue averages, utilization, throughput, and event counts use the operating
window `[warmup, duration)`, so they exclude events exactly at closing and all
overtime. `warmup=60` keeps the full trace and measures station states over
`[60, duration)`. Station arrival, service-start, and service-completion counts
use each event's time in that window. `completed_at_close` and
`remaining_at_close` describe the backlog at closing, while `completed` and
`remaining` describe the final records after any continuation. Station closing
counts are `waiting_at_close` and `occupied_at_close`, and final station counts
are `waiting_at_end` and `occupied_at_end`. An occupied server holds a job that
is processing, paused, or blocked, so `occupied_at_close` includes the servers
that `blocked_at_close` and `paused_at_close` count. Closing and final counts
include customers who arrived before warm-up.

Mean and 95th percentile waiting times use visits admitted to the station's
line at or after warm-up whose service starts were observed, including visits
admitted after closing when a drained run continues, and they exclude time spent
outside a full finite buffer or blocked upstream. `wait_arrivals` reports the
size of this visit cohort, and `wait_observations` reports the number with
observed waits. Flow-time and total-wait averages use system arrivals at or
after warm-up whose exits were observed, and `cohort_remaining` counts
unfinished members of that arrival cohort. With `drain=False`, these observed
averages can underrepresent long waits and flow times, particularly when the
queue is still growing. Draining leaves no unfinished customers, so every
admitted customer's outcome is observed.

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
capacity. Down time can overlap paused and blocked time, so these fractions must
not be added. `mean_scheduled_servers` and `mean_available_servers` integrate
staffing and available-server counts, where available servers are on duty and
not down, plus off-duty servers that are not down and are finishing a job at a
station whose shifts end with `shift_end='finish'`. `staffed_utilization`
divides processing area by available-server area and is missing when available
exposure is zero. Work in process uses admitted customers' presence clipped to
the measurement window, and queue maxima exclude states lasting zero time.

### Event order

Several events can occur at the same instant. FlowSim processes shift changes
first, then service completions, transfers, failures, and repairs in the order
they were scheduled, then abandonments, then new arrivals, then stock-point
reviews, and drain checks last. Thus, a server that finishes a job at minute 10
is free for a customer who arrives at minute 10 and for a waiting customer
whose patience ends at minute 10, and the state trace keeps the final state at
each time.

## Setup for OM 522

These steps set up FlowSim on Windows or macOS and reproduce the core video and
the service day video. Every command runs in a terminal (PowerShell on Windows,
Terminal on macOS), and one command works on both systems unless a step shows a
separate command for each.

### 1. Check for Pixi

FlowSim uses [Pixi](https://pixi.sh) to install Python and every package the
project needs into the project folder. OM 522 students installed Pixi in the
Technology Foundations meeting. Open a terminal and run

```bash
pixi --version
```

A version number (e.g., `pixi 0.83.0`) means Pixi is ready. If the terminal
reports that `pixi` is not found or not recognized, install it with the command
for the system, then close the terminal and open a new one, since the installer
updates the `PATH` (the list of folders a terminal searches for programs) only
for terminals opened afterward.

<details>
<summary>macOS (Terminal)</summary>

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

</details>

<details>
<summary>Windows (PowerShell)</summary>

```powershell
powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

On a Windows machine that blocks scripts, `winget install prefix-dev.pixi`
installs the same program.

</details>

### 2. Download FlowSim

Open <https://github.com/nkfreeman-teaching/flowsim> in a browser, click the
green **Code** button, and choose **Download ZIP**. The browser saves
`flowsim-main.zip` in the Downloads folder.

<details>
<summary>macOS</summary>

Safari extracts the ZIP automatically and leaves a `flowsim-main` folder in
Downloads. With another browser, double-click `flowsim-main.zip` in Finder to
extract it.

</details>

<details>
<summary>Windows</summary>

Right-click `flowsim-main.zip` in File Explorer, choose **Extract All**, and
accept the suggested destination. Windows places a second `flowsim-main` folder
inside the first, and the inner folder is the project.

</details>

The project folder is the one that holds `pixi.toml`, `README.md`, and the
folders `examples` and `flowsim` (Windows may hide the `.toml` ending and show
`pixi`).

### 3. Move the project to OM522/flowsim

These steps keep the project at `OM522/flowsim` in the home folder
(`C:\Users\<name>` on Windows, `/Users/<name>` on macOS). Neither OneDrive nor
iCloud syncs the home folder itself, which matters because a synced folder can
lock or partly upload the thousands of files Pixi installs. Create the `OM522`
folder from the terminal.

```bash
mkdir ~/OM522
```

If `OM522` already exists from an earlier meeting, `mkdir` reports an error that
can be ignored. Then move the project folder from step 2 into `OM522` and rename
it `flowsim`.

<details>
<summary>macOS</summary>

In Finder, choose **Go > Home** (Shift-Command-H), open `OM522`, and drag the
`flowsim-main` folder from Downloads into it. Select the folder, press Return,
and type `flowsim`.

</details>

<details>
<summary>Windows</summary>

In File Explorer, type `%USERPROFILE%\OM522` in the address bar and press
Enter. Drag the inner `flowsim-main` folder from Downloads into it, then
right-click the folder, choose **Rename**, and type `flowsim`.

</details>

Check the result from the terminal.

```bash
cd ~/OM522/flowsim
ls pixi.toml
```

The second command prints `pixi.toml`. An error means the moved folder is not
the project folder. On Windows it is usually the outer `flowsim-main` folder, so
move the inner folder instead.

### 4. Install the environment

From `~/OM522/flowsim`, run

```bash
pixi install
```

The first run downloads Python and every package listed in the lock file
(`pixi.lock`), so it needs an internet connection, and later runs reuse those
downloads. Every `pixi run` command below starts from this folder, so begin each
new terminal session with `cd ~/OM522/flowsim`.

### 5. Reproduce the core video

The core video is [FlowSim: the core workflow](https://youtu.be/5vstGf6u48U).

```bash
pixi run demo
```

The first pair of tables, under `deterministic`, describes the three-customer
queue that the core video times by hand. Its `Service` row shows a mean wait of
1.0 minute, a mean queue of 0.428571 (i.e., 3/7), and a utilization of 0.857143
(i.e., 6/7), which are the values the video derives in "Checking the timing by
hand" and reads back in "Reading the result tables". The run also writes the
offline viewer page and the CSV export that the video opens in "Viewing and
exporting results". Open the viewer with the command for the system.

<details>
<summary>macOS</summary>

```bash
open output/deterministic/viewer.html
```

</details>

<details>
<summary>Windows</summary>

```powershell
start output\deterministic\viewer.html
```

</details>

### 6. Reproduce the service day video

The service day video is
[FlowSim: staffing a service day](https://youtu.be/W5rkeS2SmCY).

```bash
pixi run exercise
```

The `Staffing targets` table repeats the service day video's comparison, in
which one server averages 78.6 minutes of total wait, two servers average 3.2,
and three average 1.1. Its `days_finished_on_time` column shows 19 of 20 days
for two servers, and the last line names two servers as the lowest staffing that
meets both targets, which is the video's decision. The same three means appear
in the core video's "Comparing scenarios" part. The run also writes the pages
the service day video shows, i.e., day 1 with one server
(`output/service-day/one-server/viewer.html`), day 1 with two servers
(`output/service-day/two-servers/viewer.html`), and the overtime comparison
(`output/service-day/overtime-comparison.html`). Open each with `open` or
`start` as in step 5.

### Updating FlowSim

To update FlowSim, download a new ZIP, replace the `flowsim` folder as in steps
2 and 3, and run `pixi install` again. The tasks regenerate everything under
`output/`. Readers who use git can instead delete the ZIP copy of the `flowsim`
folder, clone the repository into the same place, and update it later with
`git pull`.

```bash
git clone https://github.com/nkfreeman-teaching/flowsim ~/OM522/flowsim
```

### Using FlowSim in another project

Another Pixi project can use the FlowSim folder as a dependency, without a
second copy of the library. These commands create a project at
`~/OM522/project1` (any name works) and add FlowSim by the relative path
`../flowsim`, which reaches the FlowSim folder on every machine because both
folders sit inside `OM522`.

```bash
mkdir ~/OM522/project1
cd ~/OM522/project1
pixi init
pixi add "python>=3.12,<3.14"
pixi add --pypi --editable "classroom-flowsim @ ../flowsim"
```

The package is named `classroom-flowsim`, and the project imports it with
`import flowsim`. FlowSim's package dependencies (NumPy, Polars, NetworkX,
Plotly, and SciPy) install with it, but Marimo does not, so a project that uses
notebooks also runs `pixi add marimo`. Pixi does not expand `~` in a dependency
path, so the path is either relative, as above, or a full path such as
`/Users/<name>/OM522/flowsim`. The install is editable (i.e., the project reads
the code in `~/OM522/flowsim` instead of a copy), so updating FlowSim as above
also updates every project that uses it. Every Python block in this README runs
on its own in such a project, since none imports the repository's `examples`.

### Tasks

The repository defines these tasks:

| Task | What it does |
| --- | --- |
| `pixi run demo` | Runs the hand-calculated queue, two-stage network, and triage network in `examples/models.py`, then compares one, two, and three servers across 12 replications. Writes viewers, flowcharts, CSV files, and the model builder page (`builder.html`) under `output/`. |
| `pixi run exercise` | Runs the worked staffing exercise (see Classroom exercise) and writes reports under `output/service-day/`. |
| `pixi run extensions` | Runs peak demand with a lunch break, a buffered production line, a machine with repairs, and a combined line from `examples/extensions.py`, writing them under `output/extensions/`. |
| `pixi run operations` | Runs the saturated machining line and the truck cross-dock in `examples/operations.py`, comparing buffer plans and dock capacity across 20 replications, and writes them under `output/operations/` (see Operations examples). |
| `pixi run supply-chain` | Runs the beer-game supply chain in `examples/supply_chain.py`, comparing forecasting scenarios and brewing capacity across 20 replications, and writes them under `output/supply_chain/` (see Supply chain example). |
| `pixi run notebook` | Opens the Marimo lesson, which adds controls for staffing, shift and failure-clock rules, and customer timelines. |
| `pixi run notebook-export` | Executes the lesson and saves `output/lesson.html`. |
| `pixi run examples` | Runs the five tasks above that execute examples, and fails if Marimo replaced a lesson output with a size warning. |
| `pixi run check` | Runs the tests, lint, format check, notebook check, and the Pyright type check of `flowsim/` and `examples/`. |
| `pixi run format` | Formats the code with ruff. |

The lock file covers Linux, Windows, Intel Macs, and Apple Silicon Macs, and
execution has been verified on Linux with Python 3.13. The package installs into
other Python environments as the distribution `classroom-flowsim` (imported as
`flowsim`), and it depends on NumPy, Polars, NetworkX, Plotly, and SciPy.

## Changes in 2.0

FlowSim 2.0 changes no simulation result, so every example prints and exports
the same numbers as 1.0. Code written for 1.0 needs the following changes.

- An export refuses a folder that holds files with FlowSim's export names but
  no FlowSim `metadata.json`, and the error names those files. Export into a
  new folder or into one that an earlier FlowSim export wrote.
- The metric and column catalog moved from `flowsim.results` to
  `flowsim.catalog`, the record schemas to `flowsim.records`, and the export
  and interval helpers to `flowsim.reporting`. These names no longer import
  from `flowsim.results`:
  - from `flowsim.catalog`: `Column`, `COLUMNS`, `EXCLUDED`, `Inapplicable`,
    `Metric`, `metric_error`, `metrics`, `explain`, `RUN_LEVEL_METRICS`,
    `Scope`, `scope_name`, and `unknown` (`metrics` and `explain` also import
    from `flowsim`);
  - from `flowsim.records`: `INTERVAL_SCHEMA`, `interval_frame`, `Phase`,
    `STATION_HEADLINE`, and `SUPPLIER`;
  - from `flowsim.reporting`: `confidence_level`, `EXPORT_FILE_NAMES`,
    `interval_estimate`, and `write_text`.

  A few moved names (e.g., `METRICS` and `STATION_SCHEMA`) still import from
  `flowsim.results` because it uses them, but import them from their new module.
- `fit_all` and `best_fit` refuse fitting data that is text or booleans (1.0
  read `"2.5"` as 2.5 and `True` as 1). An error other than a failed fit (e.g.,
  a `TypeError` from a bug) now propagates instead of listing the family as
  failed.
- A run's supply-chain settings are public. `results.supply` (a frozen
  `SupplySettings`, or None for a service network), `results.stock_point_names`,
  and `results.records_kept` replace the private `_supply` and `_records_kept`,
  and `results.settings.capacities` replaces `_capacities`. For example,
  `results._supply["chain"]` becomes `results.supply.chain`, which is a tuple.
- FlowSim 1.0 pointed names from earlier versions to their current ones, and
  2.0 gives the ordinary missing-attribute error with any close matches
  instead. A run's plot methods are `plot_queue`, `plot_wait`, and so on
  (earlier versions named them `queue_plot`, `wait_plot`, and so on), and
  settings such as `duration` are read from `.settings` (e.g.,
  `results.settings.duration`).
- Saved pages hold each record table column by column and store chart data as
  compact arrays, so the service-day comparison page is about 14 MB instead of
  23 MB. Code that reads a page's embedded JSON reads each table as a mapping
  from column name to values.

## Videos

Five videos walk through FlowSim, and all five are in one
[YouTube playlist](https://www.youtube.com/playlist?list=PLXLjk3y_o8_Y). Each
video's numbers come from a task in this repository, so a student can reproduce
what the video shows.

| Video | Task | README section |
| --- | --- | --- |
| [FlowSim: the core workflow](https://youtu.be/5vstGf6u48U) | `pixi run demo` | Setup for OM 522, step 5 |
| [FlowSim: staffing a service day](https://youtu.be/W5rkeS2SmCY) | `pixi run exercise` | Classroom exercise, and Setup for OM 522, step 6 |
| [FlowSim: modeling a machining line](https://youtu.be/jWuCiGMI9fU) | `pixi run operations` | Machining line |
| [FlowSim: the bullwhip effect](https://youtu.be/Eir_tSuytso) | `pixi run supply-chain` | Supply chain example |
| [FlowSim: drawing a model in the builder](https://youtu.be/pryrCaFfH7s) | `flowsim.builder("output/builder.html")` | Drawing a model in the browser |

The first four videos were recorded before FlowSim had named distributions, so
their code calls NumPy directly (e.g., `lambda rng: rng.exponential(scale=3)`)
where this README uses a named distribution such as `exponential(mean=3)`. The
two forms draw the same values (see Durations and distributions), and the code
the videos show still runs. The builder video draws its model with named
distributions in the model builder (see Drawing a model in the browser).

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
the examples still run. `tests/test_readme.py` runs each Python block in this
README on its own, in a fresh namespace, and checks that the generated metric
and column tables match the catalog. After a catalog change, the failing test
prints the new table to paste between the markers. The browser tests block
external requests and exercise the saved viewers' controls and downloads and
the builder page's controls (`tests/test_builder.py`). Every browser test runs
twice, once in Chrome or Chromium and once in Playwright's Firefox (installed
with `pixi run playwright install firefox`). Safari's engine (WebKit) is not
tested. The tests find Chrome or Chromium on the executable search path, and a
test whose browser is missing reports a skip. Setting `FLOWSIM_CHROME` to a
browser executable selects it, and a path that does not exist fails the tests.
On macOS, Chrome is an app bundle that the search path does not reach, so the
Chrome tests skip unless `FLOWSIM_CHROME` names its executable (e.g.,
`export FLOWSIM_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`
before `pixi run check`).

## Scope and limits

FlowSim supports routes that are acyclic for each customer type (routes across
types may cycle through stations with unlimited buffers), first-come,
first-served service unless a station ranks customer types, abandonment after a
patience time, identical servers within each station, scheduled demand and
staffing, finite buffers, blocking after service, and independent failures with
resumable work. Every station has its own server pool. Preemption, balking
(i.e., refusing to join a long line), batch service, workers shared across
stations, shared repair crews, and rework loops are not implemented.
Supply chains are linear, review every stage on one period, and order with an
order-up-to policy and a moving-average forecast. Only the top stage can
produce at stations, its jobs cannot share those stations with customers from
sources, and its cover is stated instead of estimated.

A run keeps every customer, visit, and state record in memory until it ends,
which suits classroom-scale examples. An experiment or comparison with
`keep_records=False` then keeps only each run's measures, so it holds one run's
records at a time (see Replications), but there is no streaming mode for one
long run. A single run's viewer embeds its raw records, so it can become large
for long runs (approximately 1.7 MB for one 480-minute day of the first model).
An experiment or comparison page embeds every run's records when they were
kept, so the service day comparison (3 scenarios of 20 days) saves a 10.8 MB
page, i.e., 1.5 MB of Plotly, 8.6 MB of records (0.14 MB per run), and 0.7 MB
of intervals, charts, and page code. With `keep_records=False`, the same page
holds only the overview (2.2 MB). A Marimo notebook displays both pages under
the 30 MB `output_max_bytes` that `pyproject.toml` sets. A comparison with more
or longer runs can exceed that limit, in which case a notebook saves the page
and opens it in a browser.
Numeric outputs target classroom tables and plots, and LaTeX numeric exports
are not included. FlowSim schedules events with its own scheduler
(`flowsim/scheduler.py`) instead of a simulation library, and that scheduler was
checked against SimPy 4.1.2 at commit `32e96d3`. The package is released under the MIT license.
