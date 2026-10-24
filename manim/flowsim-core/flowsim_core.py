"""FlowSim: the core workflow, in seven parts.

Each part is a manim-slides Slide, so the same source renders a continuous MP4 per part
(joined into one video by ../render.sh) and a deck with a break at every pause():

    Part1Model         Model(), a source, a station, a route, and model.run
    Part2Hand          the deterministic queue timed by hand
    Part3Tables        the customers, visits, stations, and summary tables
    Part4Viewer        the offline viewer and export
    Part5Replications  twenty replications and a 95% confidence interval
    Part6Compare       compare and paired differences
    Part7Extensions    a tour of branches, types, schedules, buffers, priorities and
                       abandonment, failures, and stock points

Sources: examples/models.py, the snippet files in snippets/, and the README sections "A
first model", "Results", "Model features", "Measurement rules", "Replications and scenario
comparisons", and "For maintainers". capture.py runs the snippets and README blocks in the
project environment and writes captured/numbers.json; the assertions below check every
displayed number against the hand calculation and the README. Captions, fonts, and breaks
come from ../shared/explainer.py.

    bash ../render.sh flowsim-core preview|review|final
"""

import ast
import re
from fractions import Fraction
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Create,
    Dot,
    FadeIn,
    FadeOut,
    Group,
    Line,
    Polygon,
    Rectangle,
    VGroup,
)

from explainer import (
    BORDER,
    CONTENT_Y,
    FAINT,
    INK,
    MUTED,
    TICK_SIZE,
    ExplainerScene,
    label,
    make_arrow,
    make_bar,
    make_box,
    number_text,
    same_size_boxes,
    with_backing,
)
from flowsim_video import (
    ROOT,
    CodeScene,
    SERVICE_ORANGE,
    WAIT_BLUE,
    call_keywords,
    close,
    code_panel,
    excerpt,
    file_lines,
    function_lines,
    line_box,
    load_captured,
    readme_block,
    readme_states,
    screenshot,
    t_interval,
)

# ---------------------------------------------------------------------------
# Computation layer. Every number a scene displays is computed or read here and asserted
# against its source. Nothing below depends on how the scenes draw the results.
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
CAPTURED = load_captured(HERE)
MODELS = ROOT / "examples" / "models.py"
SNIPPETS = HERE / "snippets"

# The deterministic queue as examples/models.py defines it.
QUEUE_CODE = function_lines(MODELS, "deterministic_queue")
SOURCE_ARGS = call_keywords(QUEUE_CODE, "source")
STATION_ARGS = call_keywords(QUEUE_CODE, "station")
QUEUE_SNIPPET = file_lines(SNIPPETS / "queue.py")
RUN_ARGS = call_keywords(QUEUE_SNIPPET, "run")
CAPACITY = call_keywords(QUEUE_SNIPPET, "deterministic_queue")["capacity"]
DURATION = RUN_ARGS["duration"]
SERVICE = STATION_ARGS["service_time"]
ARRIVALS = [SOURCE_ARGS["first_arrival"] + k * SOURCE_ARGS["interarrival"] for k in range(SOURCE_ARGS["limit"])]

# One server, first come, first served: each customer starts when it has arrived and the
# server has finished the one before.
STARTS, ENDS = [], []
for arrival in ARRIVALS:
    start = max(arrival, ENDS[-1] if ENDS else arrival)
    STARTS.append(start)
    ENDS.append(start + SERVICE)
WAITS = [start - arrival for start, arrival in zip(STARTS, ARRIVALS)]
FLOWS = [end - arrival for end, arrival in zip(ENDS, ARRIVALS)]
# Each waiting customer adds its wait to the queue's area, in customer-minutes.
QUEUE_AREA = sum(WAITS)
BUSY = sum(min(end, DURATION) - start for start, end in zip(STARTS, ENDS))
MEAN_QUEUE = Fraction(QUEUE_AREA, DURATION)
UTILIZATION = Fraction(BUSY, CAPACITY * DURATION)
MEAN_WAIT = Fraction(sum(WAITS), len(WAITS))
THROUGHPUT = Fraction(sum(end < DURATION for end in ENDS), DURATION)
# Waiting-line length on each interval where it changes, for the step chart.
_times = sorted({0, DURATION, *ARRIVALS, *STARTS})
_steps = [(a, b, sum(arrival <= a < start for arrival, start in zip(ARRIVALS, STARTS))) for a, b in zip(_times, _times[1:])]
QUEUE_STEPS = []
for a, b, n in _steps:
    if QUEUE_STEPS and QUEUE_STEPS[-1][2] == n:
        QUEUE_STEPS[-1] = (QUEUE_STEPS[-1][0], b, n)
    else:
        QUEUE_STEPS.append((a, b, n))
assert QUEUE_STEPS == [(0, 1, 0), (1, 4, 1), (4, 7, 0)]
assert sum((b - a) * n for a, b, n in QUEUE_STEPS) == QUEUE_AREA

# README "For maintainers": arrivals at 0, 1, and 2 minutes, a two-minute service time,
# waits of 0, 1, and 2 minutes, mean queue 3/7 over seven minutes, and utilization 6/7.
readme_states("arrivals at 0, 1, and 2 minutes and a two-minute service time")
readme_states("With one server, waits are 0, 1, and 2 minutes, mean queue length over seven minutes is 3/7, and utilization is 6/7.")
assert ARRIVALS == [0, 1, 2] and SERVICE == 2 and CAPACITY == 1 and DURATION == 7
assert WAITS == [0, 1, 2]
assert MEAN_QUEUE == Fraction(3, 7) and UTILIZATION == Fraction(6, 7)

# The simulator's run of the same model (captured from snippets/queue.py).
RUN = CAPTURED["queue"]
assert RUN["arrival_time"] == ARRIVALS and RUN["exit_time"] == ENDS
assert RUN["total_wait"] == WAITS and RUN["flow_time"] == FLOWS
assert RUN["service_start"] == STARTS and RUN["service_end"] == ENDS
assert RUN["server_id"] == [1, 1, 1] and RUN["capacity"] == CAPACITY
assert close(RUN["mean_wait"], float(MEAN_WAIT))
assert close(RUN["mean_queue"], float(MEAN_QUEUE))
assert close(RUN["utilization"], float(UTILIZATION))
assert close(RUN["throughput"], float(THROUGHPUT))
assert RUN["arrivals"] == RUN["completed"] == len(ARRIVALS)
assert close(RUN["mean_flow_time"], sum(FLOWS) / len(FLOWS))
# The viewer's 95th percentile wait interpolates linearly between the sorted waits
# (flowsim/results.py, quantile 0.95 with interpolation="linear"), so waits 0, 1, and 2
# give 1.9 rather than 2.
_rank = 0.95 * (len(WAITS) - 1)
_below = int(_rank)
P95_WAIT = sorted(WAITS)[_below] + (_rank - _below) * (sorted(WAITS)[_below + 1] - sorted(WAITS)[_below])
assert close(P95_WAIT, 1.9)
LIBRARY = ROOT / "flowsim"
assert 'interpolation="linear"' in (LIBRARY / "results.py").read_text()
TIMELINE_CUSTOMER = CAPTURED["timeline_customer"]
TIMELINE_FLOW = FLOWS[TIMELINE_CUSTOMER - 1]
TIMELINE_WAIT = WAITS[TIMELINE_CUSTOMER - 1]

# README "Results": export writes seven CSV files and one metadata file.
readme_states("writes seven CSV files and one metadata file")
EXPORT_FILES = CAPTURED["export_files"]
assert sum(name.endswith(".csv") for name in EXPORT_FILES) == 7 and "metadata.json" in EXPORT_FILES
assert len(EXPORT_FILES) == 8

# Twenty replications of the two-stage network (snippets/replications.py).
REPLICATION_SNIPPET = file_lines(SNIPPETS / "replications.py")
EXPERIMENT_ARGS = call_keywords(REPLICATION_SNIPPET, "experiment")
DAYS = EXPERIMENT_ARGS["replications"]
DAY = EXPERIMENT_ARGS["duration"]
assert EXPERIMENT_ARGS["drain"] is True
NETWORK_CODE = function_lines(MODELS, "service_network")
CHECK_IN_SERVERS = call_keywords(NETWORK_CODE, "station")["capacity"]
# The Service station's server count is the function's default argument.
_network = ast.parse("\n".join(NETWORK_CODE)).body[0]
SERVICE_SERVERS = ast.literal_eval(_network.args.defaults[0])
assert _network.args.args[0].arg == "service_capacity"
# Each random time is a lambda that draws from the run's generator; NumPy's exponential
# scale is a mean (README "A first model").
NETWORK_SERVICE_MEAN = int(re.search(r"service_time=lambda rng: rng\.exponential\(scale=(\d+)\)", "\n".join(NETWORK_CODE))[1])
assert NETWORK_SERVICE_MEAN == 4
readme_states("NumPy's exponential `scale` is a mean duration, not an arrival rate.")
REPS = CAPTURED["replications"]
SERVICE_RUNS = REPS["service_runs"]
assert len(SERVICE_RUNS) == DAYS == REPS["runs"] == REPS["seeds_distinct"] == 20
WAIT_MEAN, WAIT_LOWER, WAIT_UPPER = t_interval(SERVICE_RUNS)
assert close(WAIT_MEAN, REPS["service_mean"], 1e-9)
assert close(WAIT_LOWER, REPS["service_lower"], 1e-9)
assert close(WAIT_UPPER, REPS["service_upper"], 1e-9)
assert REPS["confidence"] == 0.95

# Paired comparison of one, two, and three Service servers (snippets/compare.py).
COMPARE_SNIPPET = file_lines(SNIPPETS / "compare.py")
COMPARED_SERVERS = [int(n) for n in re.findall(r"service_network\(service_capacity=(\d+)\)", "\n".join(COMPARE_SNIPPET))]
assert COMPARED_SERVERS == [1, 2, 3]
COMPARE = CAPTURED["compare"]
SCENARIOS = list(COMPARE["runs"])
assert SCENARIOS == ["One server", "Two servers", "Three servers"]
assert COMPARE["same_seeds"] is True and COMPARE["baseline"] == ["One server"]
MEANS = {}
for name in SCENARIOS:
    MEANS[name] = t_interval(COMPARE["runs"][name])
    assert all(close(a, b, 1e-9) for a, b in zip(MEANS[name], COMPARE["means"][name]))
DIFFERENCES = {}
for name in SCENARIOS[1:]:
    paired = [b - a for a, b in zip(COMPARE["runs"]["One server"], COMPARE["runs"][name])]
    DIFFERENCES[name] = t_interval(paired)
    assert all(close(a, b, 1e-9) for a, b in zip(DIFFERENCES[name], COMPARE["differences"][name]))
# comparison.intervals() and differences() default to mean total wait, and differences()
# subtracts the first named scenario (flowsim/comparison.py).
_comparison = ast.parse((LIBRARY / "comparison.py").read_text())
_defaults = {}
for _node in ast.walk(_comparison):
    if isinstance(_node, ast.FunctionDef) and _node.name in {"intervals", "differences"}:
        _kwonly = dict(zip((a.arg for a in _node.args.kwonlyargs), _node.args.kw_defaults))
        _positional = dict(zip((a.arg for a in _node.args.args[-len(_node.args.defaults):]), _node.args.defaults))
        _defaults[_node.name] = {k: ast.literal_eval(v) for k, v in {**_positional, **_kwonly}.items() if v is not None}
assert _defaults["intervals"]["metric"] == _defaults["differences"]["metric"] == "mean_total_wait"
assert "self.baseline = next(iter(experiments))" in (LIBRARY / "comparison.py").read_text()
# Two servers lower mean total wait on every day's pairing, so the interval sits below 0.
assert DIFFERENCES["Two servers"][2] < 0

# The extension tour quotes README blocks that capture.py ran (load_captured checked
# that each block is unchanged since).
TOUR = [
    ("Branches", "Branches and shared stations", "model.route([arrivals, triage])", 4),
    ("Types", "Customer types", "orders = model.source(", 10),
    ("Schedules", "Demand and staffing schedules", "arrivals = model.source(", 11),
    ("Buffers", "Finite buffers and blocking", "assembly = model.station(", 14),
    ("Priority and patience", "Priorities and abandonment", "doctor = model.station(", 11),
    ("Failures", "Failures and repair", "machine = model.station(", 8),
    ("Stock points", "Inventory and ordering", "    chain.stock_point(", 11),
]
TOUR_CODE = {
    name: excerpt(readme_block(heading).rstrip("\n").split("\n"), first, count) for name, heading, first, count in TOUR
}
assert set(CAPTURED["readme_blocks"]) == {heading for _, heading, _, _ in TOUR}
# README "Model features": schedules, buffers, abandonment, and failures each require an
# explicit behavior argument.
readme_states("Schedules, buffers, abandonment, and failures each require an explicit behavior argument")
# The values each behavior argument accepts, as flowsim/model.py validates them.
_model_text = (LIBRARY / "model.py").read_text()
BEHAVIOR_OPTIONS = {}
for _argument in ("shift_end", "external_overflow", "abandon_from", "failure_clock"):
    _match = re.search(rf"if {_argument} not in \{{([^}}]*)\}}", _model_text)
    BEHAVIOR_OPTIONS[_argument] = [ast.literal_eval(v.strip()) for v in _match[1].split(",")]
assert BEHAVIOR_OPTIONS == {
    "shift_end": ["finish", "pause"],
    "external_overflow": ["reject", "wait"],
    "abandon_from": ["waiting", "waiting_and_outside"],
    "failure_clock": ["available", "busy"],
}
TOUR_VALUES = {"shift_end": "finish", "external_overflow": "reject", "abandon_from": "waiting", "failure_clock": "available"}
for _argument, _value in TOUR_VALUES.items():
    assert _value in BEHAVIOR_OPTIONS[_argument]
    assert f'{_argument}="{_value}"' in "\n".join(line for lines in TOUR_CODE.values() for line in lines)
readme_states("The shift rule is required with staffing.")
readme_states("the first scenario unless `baseline=` names")
readme_states("Abandoned customers stay out of wait and flow averages, as rejected arrivals do")
readme_states("A schedule is a list of (time, value) pairs")
readme_states("Arrival `rates` are customers per model time unit")
readme_states("Service is not preemptive")
readme_states("`lead_time` is the delay from the supplier's shipment to this stage's receipt")
readme_states("advances while a server is up and scheduled, including idle and blocked time and time an off-duty server spends finishing its job")


def fraction_text(value):
    return f"{value.numerator}/{value.denominator}"


def minutes(value):
    return f"{value:g}"


def signed(value, places=1):
    return number_text(f"{value:.{places}f}")


# ---------------------------------------------------------------------------
# Display layer. Colors, layout, captions, and timing live here; fonts and caption rules
# come from ../shared/explainer.py.
# ---------------------------------------------------------------------------

SOURCE_NOTE = "examples/models.py"
QUEUE_NOTE = "manim/flowsim-core/snippets/queue.py"


def code_lines_of(lines, first, count):
    return excerpt(lines, first, count)


def network_row(y=1.65):
    """The source, station, and exit boxes of the deterministic queue."""
    boxes = same_size_boxes(
        [
            (("Customers", ("source",)), {}),
            (("Service", ("station",)), {}),
            (("Exit", ("model.exit",)), {}),
        ],
    )
    row = VGroup(*boxes).arrange(RIGHT, buff=2.0).move_to([0, y, 0])
    arrows = VGroup(
        make_arrow(boxes[0].get_right(), boxes[1].get_left()),
        make_arrow(boxes[1].get_right(), boxes[2].get_left()),
    )
    return row, arrows


CoreScene = CodeScene


class Part1Model(CoreScene):
    def construct(self):
        self.title_card(1, "A model in five calls")
        row, arrows = network_row()
        self.play(FadeIn(row), run_time=0.8)
        self.say("FlowSim simulates customers who arrive, wait for servers, and leave.")
        self.pause("network")

        source_lines = code_lines_of(QUEUE_CODE, '    model = Model(time_unit="minutes")', 7)
        self.say("Model() holds the sources, stations, and routes of one system.")
        self.show_code(source_lines, SOURCE_NOTE + ", deterministic_queue", top=-0.15)
        self.highlight(0)
        self.pause("model")

        self.say("A source creates customers. Interarrival is the time between arrivals.")
        self.highlight(1, 6)
        arrivals_text = ", ".join(minutes(a) for a in ARRIVALS)
        note_y = row.get_bottom()[1] - 0.4
        arrival_note = label(f"arrive at {arrivals_text}", size=22).move_to([row[0].get_x(), note_y, 0])
        self.pause("source")
        self.say(
            f"The first arrives at minute {minutes(SOURCE_ARGS['first_arrival'])}, then one every "
            f"{minutes(SOURCE_ARGS['interarrival'])} minute. The source stops after {SOURCE_ARGS['limit']} customers.",
        )
        self.highlight(3, 5)
        self.play(FadeIn(arrival_note, shift=0.1 * DOWN), run_time=0.6)
        self.pause("arrivals")

        station_lines = code_lines_of(QUEUE_CODE, "    service = model.station(", 6)
        self.say("A station has parallel servers and one waiting line.")
        self.show_code(station_lines, SOURCE_NOTE + ", deterministic_queue", top=-0.15)
        self.highlight(0, 4)
        self.pause("station")
        self.say(f"Capacity is the number of servers. Each service here takes {minutes(SERVICE)} minutes.")
        self.highlight(2, 3)
        service_note = label(f"{minutes(SERVICE)} minutes each", size=22).move_to([row[1].get_x(), note_y, 0])
        self.play(FadeIn(service_note, shift=0.1 * DOWN), run_time=0.6)
        self.pause("capacity")

        self.say("A route lists the stations in order and ends at model.exit.")
        self.highlight(5)
        self.play(Create(arrows[0]), Create(arrows[1]), run_time=0.8)
        self.pause("route")

        run_lines = code_lines_of(QUEUE_SNIPPET, "model = deterministic_queue(capacity=1)", 2)
        self.say(f"model.run admits arrivals and serves customers for {DURATION} minutes.")
        self.show_code(run_lines, QUEUE_NOTE, top=-0.15)
        self.highlight(1)
        server_note = label(f"{CAPACITY} server", size=22).move_to([row[1].get_x(), note_y - 0.38, 0])
        self.play(FadeIn(server_note, shift=0.1 * DOWN), run_time=0.6)
        self.pause("run")
        self.say(f"seed={RUN_ARGS['seed']} fixes any random draws, so a rerun repeats the results.")
        self.pause("end", hold=3.5)


class Gantt:
    """A minute axis with one row per customer, a waiting-line step chart, and a server
    row, for the deterministic queue."""

    X0 = -3.9
    UNIT = 1.25
    ROWS = [1.75, 0.9, 0.05]
    BAR = 0.42
    QUEUE_BASE = -1.3
    QUEUE_UNIT = 0.7
    SERVER_Y = -2.0
    AXIS_Y = -2.55

    def x(self, minute):
        return self.X0 + self.UNIT * minute

    def axis(self):
        line = Line([self.x(0), self.AXIS_Y, 0], [self.x(DURATION), self.AXIS_Y, 0], color=INK, stroke_width=2)
        ticks = VGroup()
        for minute in range(DURATION + 1):
            ticks.add(Line([self.x(minute), self.AXIS_Y, 0], [self.x(minute), self.AXIS_Y - 0.1, 0], color=INK, stroke_width=2))
            ticks.add(label(str(minute), size=TICK_SIZE).move_to([self.x(minute), self.AXIS_Y - 0.32, 0]))
        title = label("Minutes", size=22).move_to([self.x(DURATION / 2), self.AXIS_Y - 0.75, 0])
        grid = VGroup(
            *(
                Line([self.x(m), self.AXIS_Y, 0], [self.x(m), self.ROWS[0] + 0.35, 0], color=FAINT, stroke_width=1)
                for m in range(DURATION + 1)
            ),
        )
        grid.set_z_index(-2)
        return VGroup(grid, line, ticks, title)

    def row_labels(self):
        rows = VGroup(
            *(
                label(f"Customer {index + 1}", size=22).move_to([self.X0 - 0.35, y, 0], aligned_edge=RIGHT)
                for index, y in enumerate(self.ROWS)
            ),
        )
        rows.add(label("Waiting line", size=22).move_to([self.X0 - 0.35, self.QUEUE_BASE + 0.3, 0], aligned_edge=RIGHT))
        rows.add(label("Server", size=22).move_to([self.X0 - 0.35, self.SERVER_Y, 0], aligned_edge=RIGHT))
        return rows

    def arrival_marks(self):
        return VGroup(
            *(
                Polygon(
                    [self.x(a) - 0.11, y + self.BAR / 2 + 0.2, 0],
                    [self.x(a) + 0.11, y + self.BAR / 2 + 0.2, 0],
                    [self.x(a), y + self.BAR / 2 + 0.02, 0],
                    color=INK,
                    fill_color=INK,
                    fill_opacity=1,
                    stroke_width=1,
                )
                for a, y in zip(ARRIVALS, self.ROWS)
            ),
        )

    def bar(self, start, end, y, color, height=None):
        height = self.BAR if height is None else height
        return make_bar(self.UNIT * (end - start), height, color).move_to([self.x((start + end) / 2), y, 0])

    def service_bars(self):
        return [self.bar(s, e, y, SERVICE_ORANGE) for s, e, y in zip(STARTS, ENDS, self.ROWS)]

    def wait_bars(self):
        return [self.bar(a, s, y, WAIT_BLUE) for a, s, y in zip(ARRIVALS, STARTS, self.ROWS) if s > a]

    def wait_labels(self):
        return VGroup(
            *(
                label(f"wait {minutes(w)}", size=22).move_to([self.x(e) + 0.2, y, 0], aligned_edge=LEFT)
                for w, e, y in zip(WAITS, ENDS, self.ROWS)
            ),
        )

    def queue_chart(self):
        base = Line([self.x(0), self.QUEUE_BASE, 0], [self.x(DURATION), self.QUEUE_BASE, 0], color=INK, stroke_width=1.5)
        steps = VGroup(
            *(
                make_bar(self.UNIT * (b - a), self.QUEUE_UNIT * n, WAIT_BLUE).move_to(
                    [self.x((a + b) / 2), self.QUEUE_BASE + self.QUEUE_UNIT * n / 2, 0],
                )
                for a, b, n in QUEUE_STEPS
                if n
            ),
        )
        return base, steps

    def server_bar(self):
        return self.bar(STARTS[0], ENDS[-1], self.SERVER_Y, SERVICE_ORANGE)

    def legend(self):
        items = VGroup()
        for color, text in [(WAIT_BLUE, "Waiting"), (SERVICE_ORANGE, "In service")]:
            items.add(VGroup(make_bar(0.32, 0.22, color), label(text, size=22)).arrange(RIGHT, buff=0.15, aligned_edge=UP))
        return items.arrange(RIGHT, buff=0.5, aligned_edge=UP).move_to([self.x(5.5), 2.24, 0])


class Part2Hand(CoreScene):
    def construct(self):
        self.title_card(2, "Timing by hand")
        chart = Gantt()
        axis, rows, marks = chart.axis(), chart.row_labels(), chart.arrival_marks()
        self.play(FadeIn(axis), FadeIn(rows[:3]), run_time=0.8)
        self.play(FadeIn(marks, shift=0.1 * DOWN), run_time=0.6)
        arrivals_text = ", ".join(minutes(a) for a in ARRIVALS[:-1]) + f", and {minutes(ARRIVALS[-1])}"
        self.say(f"Customers arrive at minutes {arrivals_text}. Each needs {minutes(SERVICE)} minutes of service.")
        self.pause("arrivals")

        self.say("One server takes them first come, first served.")
        self.play(FadeIn(chart.legend()), run_time=0.5)
        for bar in chart.service_bars():
            self.play(FadeIn(bar), run_time=0.6)
        self.pause("service")

        self.say(f"Customer 2 waits {minutes(WAITS[1])} minute, and customer 3 waits {minutes(WAITS[2])}.")
        for bar in chart.wait_bars():
            self.play(FadeIn(bar), run_time=0.6)
        self.play(FadeIn(chart.wait_labels()), run_time=0.6)
        self.pause("waits")

        first_wait = next(a for a, b, n in QUEUE_STEPS if n)
        last_wait = max(b for a, b, n in QUEUE_STEPS if n)
        self.say(f"The waiting line holds one customer at a time, minutes {minutes(first_wait)} to {minutes(last_wait)}.")
        base, steps = chart.queue_chart()
        self.play(FadeIn(rows[3]), Create(base), run_time=0.6)
        self.play(FadeIn(steps), run_time=0.8)
        area = label(f"area {QUEUE_AREA} customer-minutes", size=22)
        area.move_to([steps.get_right()[0] + 0.25, chart.QUEUE_BASE + 0.6, 0], aligned_edge=LEFT)
        self.play(FadeIn(area), run_time=0.5)
        self.pause("queue")

        self.say(
            f"Mean queue is the time-average line length, here {fraction_text(MEAN_QUEUE)}.",
        )
        mean_queue = label(f"mean queue {fraction_text(MEAN_QUEUE)}", size=22)
        mean_queue.next_to(area, DOWN, buff=0.1, aligned_edge=LEFT)
        self.play(FadeIn(mean_queue), run_time=0.5)
        self.pause("mean-queue")

        self.say(f"Utilization is the occupied share of server time, here {BUSY} of {DURATION} minutes.")
        server = chart.server_bar()
        self.play(FadeIn(rows[4]), FadeIn(server), run_time=0.8)
        util = label(f"utilization {fraction_text(UTILIZATION)}", size=22)
        util.next_to(server, RIGHT, buff=0.25)
        self.play(FadeIn(util), run_time=0.5)
        self.pause("end", hold=3.5)


class Part3Tables(CoreScene):
    def show_table(self, name, first, count, drop=()):
        lines = code_lines_of(QUEUE_SNIPPET, first, count)
        self.table = self.code_and_table(lines, QUEUE_NOTE, HERE, CAPTURED, name, size=18, x=-3.2, drop=(self.table, *drop))

    def construct(self):
        self.title_card(3, "Four result tables")
        self.table = None
        self.show_table("customers", "customers = results.customers.select(", 7)
        self.say("results.customers has one row per customer. Flow time runs from arrival to exit.")
        self.pause("customers")
        self.say("shape gives rows and columns. Under each name, i64 marks whole numbers and f64 decimals.")
        self.pause("types")

        self.say("results.visits has one row per station visit.")
        self.show_table("visits", "visits = results.visits.select(", 7)
        self.pause("visits")
        servers = sorted({int(server) for server in RUN["server_id"]})
        assert servers == [1]
        self.say("server_id says which server took a visit, numbered within its station.")
        self.pause("server")

        self.say("results.stations has one row per station.")
        self.show_table("stations", "stations = results.stations.select(", 7)
        self.pause("stations")
        self.say("Its mean wait, mean queue, and utilization equal the hand values.")
        hand = make_box(
            "By hand",
            (
                f"mean wait {fraction_text(MEAN_WAIT) if MEAN_WAIT.denominator != 1 else MEAN_WAIT.numerator}",
                f"mean queue {fraction_text(MEAN_QUEUE)} = {float(MEAN_QUEUE):.4f}",
                f"utilization {fraction_text(UTILIZATION)} = {float(UTILIZATION):.4f}",
            ),
        )
        hand.move_to([3.4, self.panel.get_center()[1], 0])
        self.play(FadeIn(hand), run_time=0.6)
        self.pause("match")

        self.say(
            f"results.summary has one row per run. Throughput is exits per minute, "
            f"{THROUGHPUT.numerator} in {THROUGHPUT.denominator}.",
        )
        self.show_table("summary", "summary = results.summary.select(", 6, drop=(hand,))
        self.pause("end", hold=3.5)


class Part4Viewer(CoreScene):
    def construct(self):
        self.title_card(4, "The offline viewer and export")
        lines = code_lines_of(QUEUE_SNIPPET, 'results.viewer("output/queue/viewer.html")', 2)
        self.show_code(lines, QUEUE_NOTE, top=2.3, size=22)
        self.highlight(0)
        shot = screenshot(HERE, CAPTURED, "viewer_top", width=11.0, height=3.6)
        shot.move_to([0, -1.55, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.say("results.viewer saves one hypertext markup language (HTML) page. It holds the data and charts.")
        self.pause("viewer")
        self.say(
            f"It opens without internet. Averages omit the warm-up, an opening stretch, "
            f"here {minutes(RUN['warmup'])} minutes.",
        )
        self.pause("offline")
        self.say(f"The 95th percentile wait interpolates between sorted waits. Waits 0, 1, and 2 give {P95_WAIT:g}.")
        self.pause("percentile")

        self.say("Its charts show the line over time. The slider below them zooms in.")
        self.drop_code(shot)
        shot = screenshot(HERE, CAPTURED, "viewer_queues", width=11.0, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.3, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("queues")

        self.say(
            f"The timeline splits customer {TIMELINE_CUSTOMER}'s {minutes(TIMELINE_FLOW)} minutes "
            f"into waiting and service.",
        )
        self.play(FadeOut(shot), run_time=0.4)
        shot = screenshot(HERE, CAPTURED, "viewer_timeline", width=11.0, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.3, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("timeline")

        self.say(f"results.export writes {sum(name.endswith('.csv') for name in EXPORT_FILES)} tables as comma-separated values (CSV) files. It adds metadata.json.")
        self.show_code(lines, QUEUE_NOTE, top=2.3, size=22, drop=(shot,))
        self.highlight(1)
        files = make_box(
            "output/queue/",
            tuple(name for name in EXPORT_FILES),
        )
        files.move_to([0, -1.5, 0])
        self.play(FadeIn(files), run_time=0.6)
        self.pause("export")
        self.say("metadata.json records the duration, warm-up, seed, and routes.")
        self.pause("end", hold=3.5)


class DotPlot:
    """Each day's Service mean wait as a dot, with the mean and its 95% interval."""

    LEFT_X, RIGHT_X = -5.2, 5.6
    BASE_Y, TOP_Y = -2.6, 1.6

    def __init__(self, values):
        self.values = values
        self.y_max = max(2, int(max(values)) + 1)

    def x(self, day):
        return self.LEFT_X + (self.RIGHT_X - self.LEFT_X) * (day - 0.5) / len(self.values)

    def y(self, value):
        return self.BASE_Y + (self.TOP_Y - self.BASE_Y) * value / self.y_max

    def axes(self):
        group = VGroup()
        group.add(Line([self.LEFT_X, self.BASE_Y, 0], [self.RIGHT_X, self.BASE_Y, 0], color=INK, stroke_width=2))
        group.add(Line([self.LEFT_X, self.BASE_Y, 0], [self.LEFT_X, self.TOP_Y, 0], color=INK, stroke_width=2))
        for value in range(self.y_max + 1):
            y = self.y(value)
            if value:
                grid = Line([self.LEFT_X, y, 0], [self.RIGHT_X, y, 0], color=FAINT, stroke_width=1)
                grid.set_z_index(-2)
                group.add(grid)
            group.add(label(str(value), size=TICK_SIZE).move_to([self.LEFT_X - 0.25, y, 0], aligned_edge=RIGHT))
        for day in (1, 5, 10, 15, 20):
            group.add(label(str(day), size=TICK_SIZE).move_to([self.x(day), self.BASE_Y - 0.3, 0]))
        group.add(label("Day (replication)", size=22).move_to([(self.LEFT_X + self.RIGHT_X) / 2, self.BASE_Y - 0.72, 0]))
        title = label("Mean wait at Service (minutes)", size=22).move_to([self.LEFT_X, self.TOP_Y + 0.4, 0], aligned_edge=LEFT)
        group.add(title)
        return group

    def dots(self):
        return VGroup(
            *(
                Dot([self.x(day), self.y(value), 0], radius=0.09, color=WAIT_BLUE)
                for day, value in enumerate(self.values, start=1)
            ),
        )

    def interval(self, mean, lower, upper):
        band = Rectangle(
            width=self.RIGHT_X - self.LEFT_X,
            height=self.y(upper) - self.y(lower),
            stroke_width=0,
            fill_color=WAIT_BLUE,
            fill_opacity=0.16,
        ).move_to([(self.LEFT_X + self.RIGHT_X) / 2, (self.y(upper) + self.y(lower)) / 2, 0])
        band.set_z_index(-1)
        line = Line([self.LEFT_X, self.y(mean), 0], [self.RIGHT_X, self.y(mean), 0], color=INK, stroke_width=3)
        return band, line


class Part5Replications(CoreScene):
    def construct(self):
        self.title_card(5, "Replications and intervals")
        lines = code_lines_of(REPLICATION_SNIPPET, "from examples.models import service_network", 8)
        self.show_code(lines, "manim/flowsim-core/snippets/replications.py", top=2.3, size=22)
        self.highlight(2)
        self.say(
            f"service_network is a check-in with {CHECK_IN_SERVERS} server, then service with {SERVICE_SERVERS}.",
        )
        self.pause("network")
        # The def line carries service_capacity's default of 2; the body keeps its indent.
        _start = NETWORK_CODE.index("    arrivals = model.source(")
        network = [NETWORK_CODE[0], *NETWORK_CODE[_start : _start + 14]]
        self.say(
            f"Each lambda rng: draws a new random time. exponential(scale={NETWORK_SERVICE_MEAN}) "
            f"has mean {NETWORK_SERVICE_MEAN} minutes.",
        )
        self.show_code(network, SOURCE_NOTE + ", service_network", top=2.3, size=20)
        self.highlight(13)
        self.pause("random")
        self.say(f"A replication is one independent run with its own draws, here {DAYS} days.")
        self.show_code(lines, "manim/flowsim-core/snippets/replications.py", top=2.3, size=22)
        self.highlight(4)
        self.pause("replications")
        self.say(f"drain=True serves past the {DAY}-minute close until everyone is done.")
        self.highlight(6)
        self.pause("drain")

        plot = DotPlot(SERVICE_RUNS)
        self.say("Each dot is one day's mean wait. Their average counts every day equally.")
        self.drop_code()
        self.play(FadeIn(plot.axes()), run_time=0.6)
        self.play(FadeIn(plot.dots(), lag_ratio=0.1), run_time=1.2)
        self.pause("dots")

        self.say(f"The band is a {REPS['confidence']:.0%} confidence interval (CI) for the mean. It is not a range for single days.")
        band, line = plot.interval(WAIT_MEAN, WAIT_LOWER, WAIT_UPPER)
        self.play(FadeIn(band), Create(line), run_time=0.8)
        note = with_backing(
            label(f"mean {WAIT_MEAN:.2f}, 95% CI {WAIT_LOWER:.2f} to {WAIT_UPPER:.2f}", size=22),
        ).move_to([plot.RIGHT_X, plot.TOP_Y + 0.4, 0], aligned_edge=RIGHT)
        self.play(FadeIn(note), run_time=0.5)
        self.pause("interval")

        self.say("experiment.intervals reports these Student t limits by station.")
        self.clear_stage()
        lines = code_lines_of(REPLICATION_SNIPPET, 'waits = experiment.intervals("mean_wait").select(', 7)
        self.code_and_table(lines, "manim/flowsim-core/snippets/replications.py", HERE, CAPTURED, "waits", size=20, max_width=8.0)
        self.pause("table")
        self.say("The interval covers days that start empty, not long-run behavior.")
        self.pause("end", hold=3.5)


class Part6Compare(CoreScene):
    def construct(self):
        self.title_card(6, "Comparing scenarios")
        compare_lines = file_lines(SNIPPETS / "compare.py")
        lines = code_lines_of(compare_lines, "comparison = compare(", 11)
        self.show_code(lines, "manim/flowsim-core/snippets/compare.py", top=2.3, size=22)
        self.highlight(1, 5)
        servers = ", ".join(str(n) for n in COMPARED_SERVERS[:-1]) + f", or {COMPARED_SERVERS[-1]}"
        self.say(f"compare runs each named scenario. These staff Service with {servers} servers.")
        self.pause("scenarios")
        self.say(f"Each scenario uses the same {DAYS} seeds, so day k has the same arrivals.")
        self.highlight(7, 8)
        self.pause("seeds")

        lines = code_lines_of(compare_lines, "means = comparison.intervals().select(", 6)
        self.say("intervals() reports mean total wait by default. Total wait adds a customer's waits at both stations.")
        table = self.code_and_table(lines, "manim/flowsim-core/snippets/compare.py", HERE, CAPTURED, "means", size=20, max_width=7.5)
        self.pause("means")
        one, two = MEANS["One server"][0], MEANS["Two servers"][0]
        self.say(f"One server averages {one:.1f} minutes of total wait, and two servers {two:.1f}.")
        self.pause("means-read")

        lines = code_lines_of(compare_lines, "paired = comparison.differences().select(", 7)
        self.say(f"differences subtracts the first scenario, {SCENARIOS[0]}, within each day. baseline= names another.")
        table = self.code_and_table(lines, "manim/flowsim-core/snippets/compare.py", HERE, CAPTURED, "paired", size=20, max_width=9.5, drop=(table,))
        self.pause("paired")
        self.say("A negative difference means less waiting than with one server.")
        self.pause("pairing")
        mean, lower, upper = DIFFERENCES["Two servers"]
        self.say(
            f"Two servers change mean total wait by {signed(mean)} minutes. "
            f"The {REPS['confidence']:.0%} CI is {signed(lower)} to {signed(upper)}.",
        )
        self.pause("paired-read")

        self.say(f"comparison.viewer saves these intervals as one offline page. Both rows compare with {SCENARIOS[0]}, not with each other.")
        self.clear_stage()
        self.panel = None
        self.band = None
        shot = screenshot(HERE, CAPTURED, "comparison_differences", width=11.5, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.25, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("end", hold=3.5)


class Part7Extensions(CoreScene):
    CAPTIONS = {
        "Branches": ["A branch picks one destination per customer with fixed probabilities."],
        "Types": ["A customer type is a label each arrival draws. Service times may depend on it."],
        "Schedules": [
            "A schedule is a list of (time, value) pairs. Values are arrivals per minute or servers.",
            'shift_end="finish" lets a server going off duty finish its customer.',
        ],
        "Buffers": [
            'A buffer caps the waiting line. "reject" turns away arrivals that find it full.',
            "A served customer blocks its server while the next line is full.",
        ],
        "Priority and patience": [
            "A priority ranks types in the waiting line. Lower ranks go first but never interrupt service.",
            "Patience is how long a customer waits before abandoning the line.",
            'abandon_from="waiting" starts that clock in the waiting line.',
            "Abandoned and rejected customers are left out of the mean wait.",
        ],
        "Failures": [
            "time_to_failure and repair_time make servers break down and return.",
            'failure_clock="available" counts up time on shift, idle or busy. It also counts finishing a customer after the shift.',
        ],
        "Stock points": [
            "A stock point holds stock, fills orders, and reorders every period.",
            "lead_time runs from the supplier's shipment to receipt. Backorders wait for new stock.",
        ],
    }
    # Lines to highlight under each caption, by position in the excerpt.
    BANDS = {
        "Branches": [(1, 1)],
        "Types": [(3, 8)],
        "Schedules": [(2, 8), (9, 9)],
        "Buffers": [(4, 5), (11, 11)],
        "Priority and patience": [(4, 4), (5, 8), (9, 9), (5, 9)],
        "Failures": [(4, 5), (6, 6)],
        "Stock points": [(0, 10), (3, 4)],
    }

    def strip(self, current):
        """The tour's extension names, with the current one (a name) or several (a set)
        in ink. Labels align on their tops, which share a capital height, so their
        baselines line up."""
        names = [name for name, *_ in TOUR]
        chosen = current if isinstance(current, set) else {current}
        items = VGroup(
            *(label(name, size=20, color=INK if name in chosen else BORDER) for name in names),
        ).arrange(RIGHT, buff=0.42, aligned_edge=UP)
        items.move_to([0, -3.55, 0])
        if not isinstance(current, set):
            index = names.index(current)
            underline = Line(items[index].get_corner(DOWN + LEFT), items[index].get_corner(DOWN + RIGHT), color=INK)
            underline.shift(0.08 * DOWN)
            return VGroup(items, underline)
        return VGroup(items)

    def construct(self):
        self.title_card(7, "Beyond one line")
        strip = None
        for name, heading, _, _ in TOUR:
            captions = self.CAPTIONS[name]
            bands = self.BANDS[name]
            assert len(captions) == len(bands)
            for index, (caption, (first, last)) in enumerate(zip(captions, bands)):
                self.say(caption)
                if index == 0:
                    old, strip = strip, self.strip(name)
                    self.show_code(
                        TOUR_CODE[name],
                        f"README.md, {heading}",
                        top=2.3,
                        size=20,
                        width=11.5,
                        drop=(old,),
                        add=(strip,),
                    )
                self.highlight(first, last)
                self.pause(f"{name}-{index}")
        self.say("Four of these extensions require an explicit behavior argument.")
        self.drop_code(strip)
        strip = self.strip({"Schedules", "Buffers", "Priority and patience", "Failures"})
        # Each box shows the value the tour explained; BEHAVIOR_OPTIONS checks it is one of
        # the values flowsim/model.py accepts.
        boxes = same_size_boxes(
            [
                ((title, (f'{argument}="{TOUR_VALUES[argument]}"',)), {})
                for title, argument in (
                    ("Staffing", "shift_end"),
                    ("Buffers", "external_overflow"),
                    ("Patience", "abandon_from"),
                    ("Failures", "failure_clock"),
                )
            ],
        )
        # Two by two, so each box keeps its full text size and its allowed values fit.
        row = VGroup(*boxes).arrange_in_grid(rows=2, cols=2, buff=(0.5, 0.35))
        row.move_to([0, CONTENT_Y, 0])
        self.inside_frame(row)
        self.play(FadeIn(row, lag_ratio=0.15), FadeIn(strip), run_time=1.0)
        self.pause("end", hold=3.5)
