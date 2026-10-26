# FlowSim

FlowSim is a Python package for classroom simulations of service networks, i.e.,
systems in which customers or jobs arrive, wait for servers at one or more
stations, and leave. A model is a set of arrival sources, stations with parallel
servers, and routes between them. A small built-in scheduler orders the events,
and student code uses ordinary Python calls and NumPy duration samplers. Results
are Polars tables, Plotly figures, CSV exports, and an offline HTML viewer. A
Marimo lesson in `examples/lesson.py` is an optional classroom client, and the
package itself has no Marimo dependency. FlowSim also models supply chains of
stock points that fill orders from inventory and reorder each period, including
a top stage that produces its orders at stations (see Inventory and ordering).

## Getting started

These steps set up FlowSim on Windows or macOS and reproduce the core video and
the service day video. Every command runs in a terminal (PowerShell on Windows,
Terminal on macOS), and one command works on both systems unless a step shows a
separate command for each. The four FlowSim videos are in one
[YouTube playlist](https://www.youtube.com/playlist?list=PLGOCHatbz0gA).

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

```bash
# macOS (Terminal)
curl -fsSL https://pixi.sh/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -c "irm -useb https://pixi.sh/install.ps1 | iex"
```

On a Windows machine that blocks scripts, `winget install prefix-dev.pixi`
installs the same program.

### 2. Download FlowSim

Open <https://github.com/nkfreeman-teaching/flowsim> in a browser, click the
green **Code** button, and choose **Download ZIP**. The browser saves
`flowsim-main.zip` in the Downloads folder.

- **macOS.** Safari extracts the ZIP automatically and leaves a `flowsim-main`
  folder in Downloads. With another browser, double-click `flowsim-main.zip` in
  Finder to extract it.
- **Windows.** Right-click `flowsim-main.zip` in File Explorer, choose
  **Extract All**, and accept the suggested destination. Windows places a second
  `flowsim-main` folder inside the first, and the inner folder is the project.

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

- **macOS.** In Finder, choose **Go > Home** (Shift-Command-H), open `OM522`,
  and drag the `flowsim-main` folder from Downloads into it. Select the folder,
  press Return, and type `flowsim`.
- **Windows.** In File Explorer, type `%USERPROFILE%\OM522` in the address bar
  and press Enter. Drag the inner `flowsim-main` folder from Downloads into it,
  then right-click the folder, choose **Rename**, and type `flowsim`.

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

The core video is [FlowSim: the core workflow](https://youtu.be/lRh8qnjg4lo).

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

```bash
# macOS
open output/deterministic/viewer.html
```

```powershell
# Windows
start output\deterministic\viewer.html
```

### 6. Reproduce the service day video

The service day video is
[FlowSim: staffing a service day](https://youtu.be/z-lPhexe7ZY).

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

### Tasks

The repository defines these tasks:

| Task | What it does |
| --- | --- |
| `pixi run demo` | Runs the hand-calculated queue, two-stage network, and triage network in `examples/models.py`, then compares one, two, and three servers across 12 replications. Writes viewers, flowcharts, and CSV files under `output/`. |
| `pixi run exercise` | Runs the worked staffing exercise (see Classroom exercise) and writes reports under `output/service-day/`. |
| `pixi run extensions` | Runs peak demand with a lunch break, a buffered production line, a machine with repairs, and a combined line from `examples/extensions.py`, writing them under `output/extensions/`. |
| `pixi run operations` | Runs the saturated machining line and the truck cross-dock in `examples/operations.py`, comparing buffer plans and dock capacity across 20 replications, and writes them under `output/operations/` (see Operations examples). |
| `pixi run supply-chain` | Runs the beer-game supply chain in `examples/supply_chain.py`, comparing forecasting scenarios and brewing capacity across 20 replications, and writes them under `output/supply_chain/` (see Supply chain example). |
| `pixi run notebook` | Opens the Marimo lesson, which adds controls for staffing, shift and failure-clock rules, and customer timelines. |
| `pixi run notebook-export` | Executes the lesson and saves `output/lesson.html`. |
| `pixi run examples` | Runs the five tasks above that execute examples, and fails if Marimo replaced a lesson output with a size warning. |
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

`results.resource_plot()` draws each station's scheduled, available,
processing, blocked, paused, and down servers over time. The viewer includes
it when a model uses staffing schedules, finite buffers, or failures (see
Model features).

`results.export("output/my-run")` writes seven CSV files and one metadata file.
Exports keep missing starts and exits as empty CSV fields and never replace an
unknown outcome with zero.

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

## Model features

The examples above use one source, a straight route, and stations with a fixed
number of servers. Branches, customer types, schedules, finite buffers,
priorities, abandonment, and failures extend that model. Schedules, buffers,
abandonment, and failures each require an explicit behavior argument, since the
package does not choose a default for how a shift ends, where overflow goes,
which queues a customer may leave, or when a failure clock runs. Runnable
versions of these models are in `examples/models.py` and
`examples/extensions.py`.

To inspect a model, `model.nodes` maps each name to its node in definition
order, and `model.graph` returns a frozen NetworkX copy of the routes with each
edge's `probability`. An edge from a typed route holds `types` instead, i.e., a
mapping from each customer type that may take it to its probability, and
`model.routing` lists each node's destinations by customer type. None of these
can change the model.

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

### Customer types

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

from flowsim import Model

model = Model()
orders = model.source(
    name="Orders",
    interarrival=lambda rng: rng.exponential(scale=4),
    types={"A": 0.6, "B": 0.4},
)
mill = model.station(
    name="Mill",
    capacity=1,
    service_time={"A": 1.5, "B": lambda rng: rng.uniform(1, 2)},
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
```

The type draw uses its own random stream at each source, so adding types to a
source leaves its arrival times unchanged for a given seed. The `customers` and
`visits` tables carry each customer's `customer_type`, and the viewer adds a
type column when any customer has one. Waits by type come from a `group_by` on
`visits`, as above, and FlowSim adds no per-type replication metric.

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
`arrivals = completed + remaining + rejected + abandoned`, where `abandoned` is
zero without patience (see Priorities and abandonment). `admitted` counts
successful admissions to the network, and `admitted_at_close` excludes later
admissions.
`measurement_rejected` and `measurement_admitted` count only rejections and
admissions whose times fall in the measurement window `[warmup, duration)`, so
an outside customer who arrived before warm-up and entered after it counts in
`measurement_admitted`.
`remaining_at_close` includes unfinished outside customers, and
`outside_at_close` reports them separately. Wait and flow averages exclude
rejections. Outside waiting adds to `total_wait`, blocking is reported
separately in `total_blocked`, and work in process begins at admission. A small
mean wait does not establish good service when many customers are rejected.

### Priorities and abandonment

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

from flowsim import Model

model = Model()
patients = model.source(
    name="Patients",
    interarrival=lambda rng: rng.exponential(scale=6),
    types={"Critical": 0.2, "Routine": 0.8},
)
doctor = model.station(
    name="Doctor",
    capacity=1,
    service_time=lambda rng: rng.exponential(scale=5),
    priority={"Critical": 1, "Routine": 2},
    patience={
        "Critical": 240,
        "Routine": lambda rng: rng.exponential(scale=30),
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
customer's patience ends serves that customer (see Measurement rules).
Abandoned customers stay out of wait and flow averages, as rejected arrivals
do, and `arrivals = completed + remaining + rejected + abandoned`. `abandoned`
counts every abandonment, `measurement_abandoned` counts those whose times fall
in `[warmup, duration)`, and `abandonment_rate` is the share of arrivals at or
after warm-up who abandon. With `drain=False`, a customer still waiting at the
end has not abandoned, so the rate can understate abandonment. A drained run
finishes once the remaining waiting customers abandon, even at a station with
no future staffing. Thus, as with rejections, a short mean wait does not
establish good service when the abandonment rate is high.

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

### Inventory and ordering

A supply chain is a sequence of stock points (i.e., stages that hold inventory)
that fill orders from stock and reorder from the next stage up the chain.
`model.demand` draws consumer demand as a quantity per review period,
`model.stock_point` defines a stage, and `model.supply` lists the chain from
demand to the top stage, which orders from a supplier with unlimited stock that
ships in the same period unless it produces at stations (see Production at
stations). A supply chain has no arrival sources, and a supply chain run does
not accept `drain=True`.

```python
from flowsim import Model, moving_average, order_up_to

chain = Model(time_unit="weeks")
consumers = chain.demand(
    name="Consumers",
    per_period=lambda rng: rng.normal(100, 10),
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
supply_run.orders_plot().show()
supply_run.inventory_plot().show()
supply_run.viewer("output/supply-chain.html")
```

Every stock-point argument is required, since each is a behavioral choice.
`initial` is the stock on hand at time zero, with nothing on order. `lead_time`
is the delay from the supplier's shipment to this stage's receipt, either a
constant that is a whole number of review periods or a sampling function, or
`None` for a top stage that produces at stations.
`shortage` is `"backorder"` (unfilled orders wait and ship first when stock
arrives) or `"lost"` (unfilled orders disappear, and the downstream stage stops
expecting them). `forecast_from` is `"orders"` (each stage forecasts from the
orders it receives) or `"end_demand"` (each stage forecasts from consumer
demand, i.e., information sharing).

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

A supply chain run fills three further tables, which `export` writes beside the
empty customer tables, and its viewer shows each stage's orders, stock, and
backorders.

| File | Contents |
| --- | --- |
| `inventory.csv` | One row per stock point and period with receipts, incoming orders, units filled in the same period, units shipped, lost sales, and end-of-period stock, backorders, units on order, position, forecast, target, and order quantity. |
| `shipments.csv` | Each shipment's sender, receiver, quantity, ship time, lead time, and arrival time, which is empty for a shipment still in transit at the end. |
| `stock_points.csv` | Each stage's mean incoming orders and orders placed, their variances, bullwhip ratio, fill rate, mean stock and backorders, and lost sales over the measured periods. |

Stock-point measures use review periods at or after warm-up. The bullwhip ratio
is the variance of a stage's orders divided by the variance of the orders it
receives, both with the n - 1 divisor, and it is missing when incoming orders do
not vary. The fill rate is the share of each period's incoming orders filled
from stock in that period, so filled backorders do not count toward it. Mean
stock and backorders average end-of-period values rather than integrating over
time. For independent demand, a moving average over p periods, cover L, and no
safety stock, the retailer's ratio is 1 + 2L/p + 2L^2/p^2 (Chen et al. 1999,
equation 14.8), i.e., 2.12 for p = 5 and L = 2, and the test suite checks the
simulator against this value. However, the closed form allows negative orders
and FlowSim never orders less than zero, so it applies only when demand rarely
falls far enough to call for a negative order.

### Production at stations

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
comes from the stations rather than from an argument. FlowSim does not estimate
the cover from observed lead times, since that would link targets to queues
(i.e., larger targets raise orders, which lengthen queues and then raise
targets again). Jobs carry no customer type, so production stations cannot set
service times, priorities, or routes by type. They also cannot set patience or
reject outside arrivals, since an abandoned or rejected job would remove units
from an order. A finite first buffer with `external_overflow="wait"` holds
released jobs outside the line (i.e., a release queue), and `outside_wait`
records how long each job waited there.

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
they were scheduled, then abandonments, then new arrivals, then stock-point
reviews, and drain checks last. Thus, a server that finishes a job at minute 10
is free for a customer who arrives at minute 10 and for a waiting customer
whose patience ends at minute 10, and the state trace keeps the final state at
each time.

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
locked environment. Each node's random streams depend only on the seed and
the node's name, so adding, removing, or capacity-changing another node leaves
a node's own draws unchanged, while renaming a node gives it new streams. The
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
`station`, `stock_point`, `confidence`, and `baseline` arguments. These defaults differ from
an experiment's, since `experiment.intervals()` reports `mean_wait` for every
station, while `comparison.intervals()` reports `mean_total_wait` and needs
`station=` for a station metric. Compared models must declare
the same time unit, and a station metric requires that station in every
scenario. Replication identity and seed matching are checked before paired
differences are calculated. Matching seeds give each node the same draws in
every scenario that keeps its name, so a source's arrivals match across
scenarios. They do not guarantee that each customer receives the same service
draws when the network structure or the order of upstream completions changes,
because a station draws in the order customers reach it.

The table below lists the metrics that `intervals`, `differences`, and `plot`
accept. System metrics come from `summary`, and station metrics come from
`stations` and require a station name in a comparison. Stock-point metrics come
from `stock_points` and require `stock_point=` in a comparison, and their
interval tables name the stage in a `stock_point` column rather than `station`.
An experiment reports a stock-point metric for every stage unless `stock_point=`
names one.

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
| `rejected` | System | Rejected arrivals over the whole run |
| `admitted` | System | Admitted customers over the whole run, including admissions after closing |
| `measurement_rejected` | System | Rejected arrivals in `[warmup, duration)` |
| `measurement_admitted` | System | Admissions in `[warmup, duration)` |
| `abandonment_rate` | System | Share of arrivals in `[warmup, duration)` who abandon before service |
| `mean_total_blocked` | System | Mean time blocked between stations |
| `mean_outside_wait` | System | Mean waiting time outside the first station |
| `mean_wait` | Station | Mean station waiting time |
| `mean_queue` | Station | Time-average customers waiting |
| `utilization` | Station | Occupied share of installed capacity |
| `p95_wait` | Station | 95th percentile station waiting time, interpolated linearly between the two nearest observed waits |
| `processing_utilization` | Station | Processing share of installed capacity |
| `blocking_fraction` | Station | Blocked share of installed capacity |
| `downtime_fraction` | Station | Down share of installed capacity |
| `staffed_utilization` | Station | Processing share of available capacity |
| `mean_scheduled_servers` | Station | Mean number of scheduled servers |
| `mean_available_servers` | Station | Mean number of available servers |
| `mean_outside_queue` | Station | Time-average customers waiting outside the station |
| `bullwhip_ratio` | Stock point | Variance of orders placed divided by variance of orders received |
| `fill_rate` | Stock point | Share of incoming orders filled from stock in the same period |
| `mean_on_hand` | Stock point | Mean end-of-period stock on hand |
| `mean_backorders` | Stock point | Mean end-of-period backorders |
| `lost_units` | Stock point | Lost sales over the measured periods |

The offline comparison viewer shows scenario means and paired differences for
one metric (e.g., `viewer(metric="overtime")`). Comparison exports contain
per-replication system and station metrics (and stock-point metrics for supply
chains), scenario intervals, paired differences, and metadata. Raw customer
records remain in `comparison.experiments[scenario].runs`, and each run has its
own `export()`.
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

## Operations examples

`examples/operations.py` holds two multi-stage models from manufacturing and
logistics, each with a scenario study. `pixi run operations` writes their
comparison reports, one viewer per study, and the network diagrams under
`output/operations/`.

### Machining line

The machining line runs blanks through a saw, two CNC machines, a washer, two
assembly fitters, and a packer during a 480-minute shift. Blanks are released
every 2 minutes, which is faster than the line can work, and the saw has
`buffer=0` with `external_overflow="wait"`, so unsawn blanks wait outside the
line as raw stock. This pattern keeps the line saturated (i.e., it never
starves for blanks), so the parts completed by closing measure one shift's
output from an empty line. The video
[FlowSim: modeling a machining line](https://youtu.be/kY1KzMO9g-I) walks
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

### Truck cross-dock

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

## Supply chain example

`examples/supply_chain.py` builds a four-stage chain in the style of the beer
game (i.e., a retailer, wholesaler, distributor, and factory, each ordering from
the next) and studies the bullwhip effect. Consumer demand averages 100 cases
per week with a standard deviation of 20, every stage receives shipments two
weeks after they are sent, and each stage carries one standard deviation of
safety stock. `bullwhip_study` runs 20 replications of 104 weeks with a 20-week
warm-up and compares forecasting from orders with sharing consumer demand and
with a ten-week moving average. `pixi run supply-chain` writes the comparison
report, the per-replication stock-point table, and the first replication's
records and viewer under `output/supply_chain/`. The video
[FlowSim: the bullwhip effect](https://youtu.be/SbkiDw28vhI) walks through this
study.

`capacity_study` replaces the factory's two-week lead time with a brewhouse
that makes 120, 150, or 200 cases per week in jobs of 25 cases, with a target
that covers two weeks of forecast demand, and a fifth scenario brews 150 cases
per week with three weeks of cover. `pixi run supply-chain` writes its report
under `output/supply_chain/capacity/`.

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
sources, and its cover is stated rather than estimated.

Runs keep every customer, visit, and state record in memory, which suits
classroom-scale examples. There is no streaming or aggregate-only mode, and the
viewer embeds raw records, so it can become large for long runs (approximately
5 MB for one 480-minute day of the first model). Numeric outputs target
classroom tables and plots, and LaTeX numeric exports are not included. FlowSim
schedules events with its own scheduler (`flowsim/scheduler.py`) rather than a
simulation library, and that scheduler was checked against SimPy 4.1.2 at
commit `32e96d3`. The package is released under the MIT license.
