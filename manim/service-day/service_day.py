"""FlowSim: staffing a service day, in five parts.

Each part is a manim-slides Slide, so the same source renders a continuous MP4 per part
(joined into one video by ../render.sh) and a deck with a break at every pause():

    Part1Predict   the two-stage network and its offered loads, before any simulation
    Part2Day       day 1's Service queue with one and with two servers, from the viewers
    Part3Targets   the exercise's wait and overtime targets
    Part4Compare   one to three Service servers over 20 days
    Part5Decide    the decision table and the lowest staffing that meets both targets

Sources: examples/models.py (service_network), examples/service_day.py (the targets and
staffing_exercise), snippets/exercise.py, and the README section "Classroom exercise".
capture.py runs the exercise in the project environment and writes captured/numbers.json;
the assertions below recompute every displayed number from the per-day values and check
it against the exercise's own table and the README. Captions, fonts, and breaks come from
../shared/explainer.py.

    bash ../render.sh service-day preview|review|final
"""

import math
import re
from fractions import Fraction
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Create,
    FadeIn,
    Line,
    VGroup,
)

from explainer import (
    ACCEPT,
    ALERT,
    BORDER,
    CONTENT_Y,
    INK,
    MUTED,
    TICK_SIZE,
    label,
    make_arrow,
    make_bar,
    make_box,
    make_card,
    same_size_boxes,
    with_backing,
)
from flowsim_video import (
    ROOT,
    WAIT_BLUE,
    CodeScene,
    RowChart,
    close,
    excerpt,
    file_lines,
    function_lines,
    load_captured,
    module_constant,
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
EXERCISE = ROOT / "examples" / "service_day.py"

# The two-stage network's distributions, read from service_network's own lines.
NETWORK_CODE = function_lines(MODELS, "service_network")
_network = "\n".join(NETWORK_CODE)
INTERARRIVAL_MEAN = int(re.search(r"interarrival=lambda rng: rng\.exponential\(scale=(\d+)\)", _network)[1])
_low, _high = (int(v) for v in re.search(r"rng\.uniform\((\d+), (\d+)\)", _network).groups())
CHECK_IN_MEAN = Fraction(_low + _high, 2)
SERVICE_MEAN = int(re.search(r"service_time=lambda rng: rng\.exponential\(scale=(\d+)\)", _network)[1])
CHECK_IN_SERVERS = int(re.search(r'name="Check-in",\n\s+capacity=(\d+)', _network)[1])

# Offered load per server is the arrival rate times the mean service time, divided by the
# number of servers (README "Classroom exercise").
RATE = Fraction(1, INTERARRIVAL_MEAN)
STAFFING = module_constant(EXERCISE, "STAFFING")
CHECK_IN_LOAD = RATE * CHECK_IN_MEAN / CHECK_IN_SERVERS
SERVICE_LOAD = {servers: RATE * SERVICE_MEAN / servers for servers in STAFFING}
readme_states("Customers arrive every three minutes on average, check-in takes one to two minutes with one server, and service takes four minutes on average.")
readme_states("One service server has an offered load of 4/3")
readme_states("two service servers have an offered load of 2/3 per server")
assert (INTERARRIVAL_MEAN, _low, _high, CHECK_IN_SERVERS, SERVICE_MEAN) == (3, 1, 2, 1, 4)
assert SERVICE_LOAD[1] == Fraction(4, 3) and SERVICE_LOAD[2] == Fraction(2, 3)
# The bottleneck is the station with the highest load per server. Service stays the
# bottleneck with one or two servers; with three, check-in's 1/2 is higher than 4/9.
BOTTLENECK = {servers: "Service" if load > CHECK_IN_LOAD else "Check-in" for servers, load in SERVICE_LOAD.items()}
assert BOTTLENECK == {1: "Service", 2: "Service", 3: "Check-in"}

# The targets, as examples/service_day.py states them once.
DAY_LENGTH = module_constant(EXERCISE, "DAY_LENGTH")
DAYS = module_constant(EXERCISE, "DAYS")
WAIT_TARGET = module_constant(EXERCISE, "WAIT_TARGET")
OVERTIME_LIMIT = module_constant(EXERCISE, "OVERTIME_LIMIT")
ON_TIME_SHARE = module_constant(EXERCISE, "ON_TIME_SHARE")
REQUIRED_DAYS = math.ceil(ON_TIME_SHARE * DAYS)
readme_states("The exercise runs 20 days per staffing level, closes arrivals at 480 minutes, and serves every customer to completion.")
readme_states("a mean total wait of at most 5 minutes and completion within 30 minutes after closing on at least 90% of days (18 of 20)")
readme_states("These are adjustable teaching targets, not empirical service standards.")
readme_states("the observed day count is not a confidence bound on a population probability")
assert (DAY_LENGTH, DAYS, WAIT_TARGET, OVERTIME_LIMIT, REQUIRED_DAYS) == (480, 20, 5, 30, 18)
assert CAPTURED["drain"] is True and CAPTURED["durations"] == [DAY_LENGTH]

# The exercise's results, recomputed from each day's values.
SCENARIOS = list(STAFFING.values())
DECISION = {row["scenario"]: row for row in CAPTURED["decision"]}
assert list(DECISION) == SCENARIOS == list(CAPTURED["days"])
WAITS, ON_TIME, MEETS = {}, {}, {}
for servers, name in STAFFING.items():
    days = CAPTURED["days"][name]
    assert len(days["mean_total_wait"]) == DAYS and set(days["remaining"]) == {0}
    WAITS[name] = t_interval(days["mean_total_wait"])
    row = DECISION[name]
    assert all(close(a, b) for a, b in zip(WAITS[name], (row["mean_wait_minutes"], row["wait_lower"], row["wait_upper"])))
    ON_TIME[name] = sum(overtime <= OVERTIME_LIMIT for overtime in days["overtime"])
    assert ON_TIME[name] == row["days_finished_on_time"] and row["days"] == DAYS and row["servers"] == servers
    MEETS[name] = WAITS[name][0] <= WAIT_TARGET and ON_TIME[name] >= REQUIRED_DAYS
    assert MEETS[name] == row["meets_targets"]
CHOICE = next(name for name in SCENARIOS if MEETS[name])
assert CHOICE == "Two servers"
OVERTIMES = {name: CAPTURED["days"][name]["overtime"] for name in SCENARIOS}
# Even the largest staff runs past closing on some days.
THREE_MAX_OVERTIME = max(OVERTIMES["Three servers"])
assert 0 < THREE_MAX_OVERTIME <= OVERTIME_LIMIT
# Day 1 of one and two servers, as the saved viewers show it. Both days share one seed, so
# the same customers arrive.
FIRST_DAY = CAPTURED["first_day"]
for name, day in FIRST_DAY.items():
    assert day["max_queue"] == day["replication_max_queue"]
    assert close(day["mean_queue"], day["replication_mean_queue"])
    assert close(day["overtime"], OVERTIMES[name][0])
assert FIRST_DAY["One server"]["seed"] == FIRST_DAY["Two servers"]["seed"]
assert FIRST_DAY["One server"]["max_queue"] > FIRST_DAY["Two servers"]["max_queue"]
# A what-if on the adjustable wait target: the same days judged against a stricter one.
STRICT_WAIT = 2
STRICT_CHOICE = next(
    name for name in SCENARIOS if WAITS[name][0] <= STRICT_WAIT and ON_TIME[name] >= REQUIRED_DAYS
)
assert STRICT_CHOICE == "Three servers"
OVERTIME_MAX = max(max(values) for values in OVERTIMES.values())


def fraction_text(value):
    return f"{value.numerator}/{value.denominator}" if value.denominator != 1 else str(value.numerator)


# ---------------------------------------------------------------------------
# Display layer. Colors, layout, captions, and timing live here; fonts and caption rules
# come from ../shared/explainer.py.
# ---------------------------------------------------------------------------

MODELS_NOTE = "examples/models.py, service_network"
EXERCISE_NOTE = "examples/service_day.py"
LEVEL_COLORS = {"One server": ALERT, "Two servers": WAIT_BLUE, "Three servers": ACCEPT}


def network_row(y=1.75):
    boxes = same_size_boxes(
        [
            (("Customers", ("source",)), {}),
            (("Check-in", ("station",)), {}),
            (("Service", ("station",)), {}),
            (("Exit", ("model.exit",)), {}),
        ],
    )
    row = VGroup(*boxes).arrange(RIGHT, buff=1.1).move_to([0, y, 0])
    arrows = VGroup(*(make_arrow(a.get_right(), b.get_left()) for a, b in zip(boxes, boxes[1:])))
    return row, arrows


class LoadChart:
    """Offered load per server as vertical bars, with a line at 1."""

    BASE, UNIT = -2.6, 2.6
    NAMES = ["Check-in", *(f"Service, {servers} server{'s' if servers > 1 else ''}" for servers in STAFFING)]

    def __init__(self):
        self.loads = [CHECK_IN_LOAD, *SERVICE_LOAD.values()]
        self.xs = [-4.2 + 2.6 * index for index in range(len(self.loads))]

    def base(self):
        group = VGroup(Line([-5.6, self.BASE, 0], [4.9, self.BASE, 0], color=INK, stroke_width=2))
        for x, name in zip(self.xs, self.NAMES):
            group.add(label(name, size=22).move_to([x, self.BASE - 0.32, 0]))
        group.add(label("Offered load per server", size=22).move_to([-5.6, self.BASE + self.UNIT * 1.45 + 0.1, 0], aligned_edge=LEFT))
        return group

    def one_line(self):
        y = self.BASE + self.UNIT
        line = Line([-5.6, y, 0], [4.9, y, 0], color=MUTED, stroke_width=2)
        note = label("1", size=TICK_SIZE, color=MUTED).move_to([-5.85, y, 0])
        return VGroup(line, note)

    def bar(self, index, color):
        load = self.loads[index]
        bar = make_bar(1.3, self.UNIT * float(load), color).move_to([self.xs[index], self.BASE + self.UNIT * float(load) / 2, 0])
        value = with_backing(label(fraction_text(load), size=22)).next_to(bar, UP, buff=0.12)
        return VGroup(bar, value)


class Part1Predict(CodeScene):
    def construct(self):
        self.title_card(1, "Predicting the bottleneck")
        row, arrows = network_row()
        self.play(FadeIn(row), Create(arrows), run_time=0.8)
        self.say("A source creates customers. Each station has servers and one waiting line.")
        self.pause("network")

        note_y = row.get_bottom()[1] - 0.4
        arrival_note = label(f"every {INTERARRIVAL_MEAN} min on average", size=20).move_to([row[0].get_x(), note_y, 0])
        check_note = label(f"{_low} to {_high} min, {CHECK_IN_SERVERS} server", size=20).move_to([row[1].get_x(), note_y, 0])
        lines = excerpt(NETWORK_CODE, "    arrivals = model.source(", 9)
        self.say(
            f"lambda rng: draws random arrival gaps, {INTERARRIVAL_MEAN} minutes on average, all day.",
        )
        self.show_code(lines, MODELS_NOTE, top=-0.05, size=18, add=(arrival_note, check_note))
        self.highlight(2)
        self.pause("arrivals")
        self.say(f"Check-in takes {_low} to {_high} minutes, any time in that range equally likely.")
        self.highlight(7)
        self.pause("check-in")

        service_note = label(f"{SERVICE_MEAN} min on average", size=20).move_to([row[2].get_x(), note_y, 0])
        lines = excerpt(NETWORK_CODE, "    service = model.station(", 5)
        self.say(f"Service takes {SERVICE_MEAN} minutes on average. service_capacity sets its servers.")
        self.show_code(lines, MODELS_NOTE, top=-0.15, size=20, add=(service_note,))
        self.highlight(2, 3)
        self.pause("service")

        chart = LoadChart()
        self.say("Offered load is arrival rate times mean service time, per server.")
        self.clear_stage()
        self.panel = self.band = None
        formula = label(
            f"load = (1/{INTERARRIVAL_MEAN} per minute) × (mean minutes) ÷ servers",
            size=24,
        ).move_to([0, 1.9, 0])
        self.play(FadeIn(chart.base()), FadeIn(chart.one_line()), FadeIn(formula), run_time=0.8)
        self.play(FadeIn(chart.bar(0, BORDER)), run_time=0.6)
        self.pause("load")
        self.say("The bottleneck is the station with the highest offered load per server.")
        self.pause("bottleneck")

        self.say(
            f"One Service server gets {fraction_text(SERVICE_LOAD[1])}, so work arrives faster "
            f"than it can finish.",
        )
        self.play(FadeIn(chart.bar(1, LEVEL_COLORS[STAFFING[1]])), run_time=0.6)
        self.pause("one")
        self.say("Above 1, the line tends to grow until arrivals stop at closing.")
        self.pause("above-one")
        self.say(
            f"Two servers get {fraction_text(SERVICE_LOAD[2])} each. Service is still the "
            f"bottleneck, the busiest station.",
        )
        self.play(FadeIn(chart.bar(2, LEVEL_COLORS[STAFFING[2]])), run_time=0.6)
        self.pause("two")
        self.say(
            f"With three, Service drops to {fraction_text(SERVICE_LOAD[3])}. Check-in, at "
            f"{fraction_text(CHECK_IN_LOAD)}, becomes the bottleneck.",
        )
        self.play(FadeIn(chart.bar(3, LEVEL_COLORS[STAFFING[3]])), run_time=0.6)
        self.pause("end", hold=3.5)


class Part2Day(CodeScene):
    def construct(self):
        self.title_card(2, "Simulating one day")
        lines = excerpt(file_lines(HERE / "snippets" / "exercise.py"), "comparison, decision = staffing_exercise()", 5)
        self.show_code(lines, "manim/service-day/snippets/exercise.py", top=2.3, size=20)
        self.highlight(2)
        self.say(
            f"staffing_exercise runs {DAYS} days per level. Day 1's saved web page marks closing with a dashed line.",
        )
        self.pause("code")

        one, two = FIRST_DAY["One server"], FIRST_DAY["Two servers"]
        shots = [
            screenshot(HERE, CAPTURED, "day_one-server", width=11.0, height=5.0),
            screenshot(HERE, CAPTURED, "day_two-servers", width=11.0, height=5.0),
        ]
        for shot in shots:
            shot.move_to([0, -0.9, 0])
        names = [
            label(name, size=22).next_to(shot, UP, buff=0.15)
            for name, shot in zip(("One server, day 1, Service line", "Two servers, day 1, Service line"), shots)
        ]
        self.say(
            f"With one server, day 1's line peaks at {one['max_queue']} customers. "
            f"Everyone is served {one['overtime']:.0f} minutes after closing.",
        )
        self.drop_code()
        self.play(FadeIn(shots[0]), FadeIn(names[0]), run_time=0.6)
        self.pause("one")
        self.say(
            f"Two servers see the same arrivals and peak at {two['max_queue']}. "
            f"They finish {two['overtime']:.0f} minutes after closing.",
        )
        self.fade_out(shots[0], names[0])
        self.play(FadeIn(shots[1]), FadeIn(names[1]), run_time=0.6)
        self.pause("two")
        self.say(f"This chart's vertical axis tops out near {two['max_queue']}, not {one['max_queue']}.")
        self.pause("end", hold=3.5)


class Part3Targets(CodeScene):
    def construct(self):
        self.title_card(3, "Setting the wait and overtime targets")
        lines = excerpt(file_lines(EXERCISE), "DAY_LENGTH = 480  # operating minutes per simulated day", 7)
        self.show_code(lines, EXERCISE_NOTE, top=2.3, size=20)
        self.highlight(0, 1)
        self.say(f"Each staffing level runs {DAYS} simulated days. Arrivals stop at minute {DAY_LENGTH}.")
        self.pause("days")

        cards = [
            make_card(f"{WAIT_TARGET} min", ["or less mean total wait"], "WAIT_TARGET", WAIT_BLUE, width=5.2),
            make_card(
                f"{REQUIRED_DAYS} of {DAYS}",
                [f"days finish within {OVERTIME_LIMIT} min"],
                "OVERTIME_LIMIT, ON_TIME_SHARE",
                ACCEPT,
                width=5.2,
            ),
        ]
        VGroup(*cards).arrange(RIGHT, buff=0.6).move_to([0, -2.0, 0])
        self.say("Total wait adds a customer's waits at both stations.")
        self.highlight(2)
        self.play(FadeIn(cards[0]), run_time=0.6)
        self.pause("wait")
        self.say("Overtime is the time after closing needed to finish every customer.")
        self.highlight(3)
        self.pause("overtime")
        self.say(
            f"The overtime target is {OVERTIME_LIMIT} minutes or less on "
            f"{ON_TIME_SHARE:.0%} of days ({REQUIRED_DAYS} of {DAYS}).",
        )
        self.highlight(3, 4)
        self.play(FadeIn(cards[1]), run_time=0.6)
        self.pause("on-time")
        self.say("Both are adjustable teaching targets, not service standards.")
        self.pause("end", hold=3.5)


class Part4Compare(CodeScene):
    def construct(self):
        self.title_card(4, "Comparing staffing levels")
        lines = excerpt(function_lines(EXERCISE, "staffing_exercise"), "    scenarios = {", 11)
        self.show_code(lines, EXERCISE_NOTE + ", staffing_exercise", top=2.3, size=20)
        self.highlight(0, 3)
        self.say("staffing_exercise builds one scenario per server count.")
        self.pause("scenarios")
        self.say(f"A seed fixes a run's random draws. compare reuses the same {DAYS} seeds per level.")
        self.highlight(4, 10)
        self.pause("compare")

        upper = max(WAITS[name][2] for name in SCENARIOS)
        top = 20 * math.ceil(upper / 20)
        chart = RowChart(SCENARIOS, top, list(range(0, top + 1, 20)), "Mean total wait (minutes)", top=1.5)
        self.say(f"One server averages {WAITS['One server'][0]:.1f} minutes. Whiskers are 95% confidence intervals (CIs) over the {DAYS} days.")
        self.drop_code()
        target = chart.reference(WAIT_TARGET, f"target {WAIT_TARGET}", MUTED, text_color=INK)
        self.play(FadeIn(chart.axes()), FadeIn(target), run_time=0.8)
        self.play(FadeIn(chart.interval(0, *WAITS["One server"], ALERT)), run_time=0.6)
        self.pause("wait-one")
        two, three = WAITS["Two servers"][0], WAITS["Three servers"][0]
        self.say(f"Two servers average {two:.1f} and three {three:.1f}, both under the target.")
        for index, name in enumerate(SCENARIOS[1:], start=1):
            self.play(FadeIn(chart.interval(index, *WAITS[name], LEVEL_COLORS[name])), run_time=0.6)
        self.pause("wait-rest")

        zoom_top = math.ceil(max(WAITS[name][2] for name in SCENARIOS[1:]) + 1)
        zoom = RowChart(SCENARIOS[1:], max(zoom_top, WAIT_TARGET + 1), list(range(0, max(zoom_top, WAIT_TARGET + 1) + 1)), "Mean total wait (minutes)", top=1.3)
        self.say(f"Zoomed in, both intervals sit below the {WAIT_TARGET}-minute target.")
        self.clear_stage()
        target = zoom.reference(WAIT_TARGET, f"target {WAIT_TARGET}", MUTED, text_color=INK)
        self.play(FadeIn(zoom.axes()), FadeIn(target), run_time=0.8)
        for index, name in enumerate(SCENARIOS[1:]):
            self.play(FadeIn(zoom.interval(index, *WAITS[name], LEVEL_COLORS[name])), run_time=0.6)
        self.pause("wait-zoom")

        top = 50 * math.ceil(OVERTIME_MAX / 50)
        strip = RowChart(SCENARIOS, top, list(range(0, top + 1, 50)), "Overtime (minutes)", top=1.5, right=4.1)
        self.say(f"Each dot is one day's overtime. The line marks the {OVERTIME_LIMIT}-minute limit.")
        self.clear_stage()
        limit = strip.reference(OVERTIME_LIMIT, f"limit {OVERTIME_LIMIT}", MUTED, text_color=INK)
        self.play(FadeIn(strip.axes()), FadeIn(limit), run_time=0.8)
        counts = VGroup()
        for index, name in enumerate(SCENARIOS):
            dots = strip.strip(index, OVERTIMES[name], LEVEL_COLORS[name])
            self.play(FadeIn(dots, lag_ratio=0.05), run_time=0.8)
        self.pause("overtime")
        for index, name in enumerate(SCENARIOS):
            counts.add(
                label(f"{ON_TIME[name]} of {DAYS} on time", size=22).move_to([strip.right + 0.3, strip.y(index), 0], aligned_edge=LEFT),
            )
        self.say("The target counts on-time days, not mean overtime.")
        self.play(FadeIn(counts), run_time=0.6)
        self.pause("counts")
        self.say(f"Even three servers run up to {THREE_MAX_OVERTIME:.0f} minutes past closing on some days.")
        self.pause("three-late")

        self.say('comparison.viewer(metric="overtime") saves this comparison. It shows each level\'s mean overtime and 95% CI.')
        self.clear_stage()
        shot = screenshot(HERE, CAPTURED, "overtime_viewer", width=11.0, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.3, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("end", hold=3.5)


class Part5Decide(CodeScene):
    def construct(self):
        self.title_card(5, "Choosing the staffing level")
        lines = excerpt(file_lines(HERE / "snippets" / "exercise.py"), "targets = decision.select(", 6)
        table = self.code_and_table(lines, "manim/service-day/snippets/exercise.py", HERE, CAPTURED, "decision", size=20, max_width=10.5)
        self.say("The decision table tests each level's mean total wait and on-time days.")
        self.pause("table")

        choice, strict = same_size_boxes(
            [
                (
                    ("Lowest staffing meeting both targets", (f"{CHOICE}: {WAITS[CHOICE][0]:.1f} min mean total wait",
                     f"{ON_TIME[CHOICE]} of {DAYS} days on time")),
                    {"color": ACCEPT},
                ),
                (
                    (f"With a {STRICT_WAIT}-minute wait target", (f"{STRICT_CHOICE}: {WAITS[STRICT_CHOICE][0]:.1f} min mean total wait",
                     f"{ON_TIME[STRICT_CHOICE]} of {DAYS} days on time")),
                    {},
                ),
            ],
        )
        self.say(f"{CHOICE} is the lowest staffing that meets both targets.")
        top = self.panel.get_center()[1]
        choice.move_to([-3.25, top, 0])
        strict.move_to([3.25, top, 0])
        self.drop_code()
        self.play(FadeIn(choice), run_time=0.6)
        self.pause("choice")
        self.say(f"The {ON_TIME[CHOICE]} of {DAYS} on-time days are a count from these runs. They are not a probability for future days.")
        self.pause("scope")
        self.say(f"With a {STRICT_WAIT}-minute wait target, the same days would call for {STRICT_CHOICE.lower()}.")
        self.fade_out(table)
        self.play(FadeIn(strict), run_time=0.6)
        self.pause("end", hold=3.5)
