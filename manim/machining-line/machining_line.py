"""FlowSim: modeling a machining line, in four parts.

Each part is a manim-slides Slide, so the same source renders a continuous MP4 per part
(joined into one video by ../render.sh) and a deck with a break at every pause():

    Part1Line       the line, the blank release, and the saw's zero buffer
    Part2Capacity   rough capacity per station, the assembly lunch, and the CNC failures
    Part3Buffers    the buffer plans and parts per shift
    Part4Failures   the no-failure scenario and the CNC down share

Sources: examples/operations.py (machining_line, BUFFER_PLANS, SHIFT, line_study),
snippets/line.py, and the README section "Machining line". capture.py runs the
study in the project environment and writes captured/numbers.json; the assertions below
recompute every displayed number from the per-run values or the model's own parameters and
check it against the README. Captions, fonts, and breaks come from ../shared/explainer.py.

    bash ../render.sh machining-line preview|review|final
"""

import ast
from fractions import Fraction
from pathlib import Path

from manim import (
    LEFT,
    RIGHT,
    UP,
    Create,
    FadeIn,
    FadeOut,
    Line,
    ManimColor,
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
    number_text,
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
OPERATIONS = ROOT / "examples" / "operations.py"
LINE_CODE = function_lines(OPERATIONS, "machining_line")
OPERATIONS_LINES = file_lines(OPERATIONS)
SHIFT = module_constant(OPERATIONS, "SHIFT")
BUFFER_PLANS = module_constant(OPERATIONS, "BUFFER_PLANS")


def sampler_mean(node):
    """The mean of a constant or of a lambda that draws uniform, gamma, or exponential."""
    if isinstance(node, ast.Constant):
        return Fraction(str(node.value))
    call = node.body
    method = call.func.attr
    args = [Fraction(str(ast.literal_eval(arg))) for arg in call.args]
    kwargs = {kw.arg: Fraction(str(ast.literal_eval(kw.value))) for kw in call.keywords}
    if method == "uniform":
        return (args[0] + args[1]) / 2
    if method == "gamma":
        return kwargs["shape"] * kwargs["scale"]
    if method == "exponential":
        return kwargs["scale"]
    raise ValueError(method)


_tree = ast.parse("\n".join(LINE_CODE))
STATIONS = {}
SOURCE = {}
BREAKDOWNS = {}
for node in ast.walk(_tree):
    if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in {"station", "source"}:
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        name = ast.literal_eval(keywords["name"])
        if node.func.attr == "source":
            SOURCE = {key: ast.literal_eval(value) for key, value in keywords.items()}
            continue
        STATIONS[name] = {
            "capacity": ast.literal_eval(keywords["capacity"]),
            "mean": sampler_mean(keywords["service_time"]),
            "staffing": ast.literal_eval(keywords["staffing"]) if "staffing" in keywords else None,
            "buffer": keywords["buffer"],
            "overflow": ast.literal_eval(keywords["external_overflow"]),
        }
    if isinstance(node, ast.Dict) and any(getattr(key, "value", None) == "time_to_failure" for key in node.keys):
        for key, value in zip(node.keys, node.values):
            BREAKDOWNS[key.value] = value
NAMES = ["Saw", "CNC", "Wash", "Assembly", "Pack"]
assert list(STATIONS) == NAMES
assert SOURCE["interarrival"] == 2 and SOURCE["first_arrival"] == 0
assert ast.literal_eval(STATIONS["Saw"]["buffer"]) == 0 and STATIONS["Saw"]["overflow"] == "wait"
# The saw's cutting time is drawn uniformly from this range.
_saw_call = next(
    node.body for node in ast.walk(_tree)
    if isinstance(node, ast.Lambda) and getattr(node.body.func, "attr", None) == "uniform" and STATIONS["Saw"]["mean"] == sampler_mean(node)
)
SAW_RANGE = tuple(ast.literal_eval(arg) for arg in _saw_call.args)
assert SAW_RANGE == (2.5, 3.5)
RELEASED = SHIFT // SOURCE["interarrival"]
MTTF = sampler_mean(BREAKDOWNS["time_to_failure"])
REPAIR = sampler_mean(BREAKDOWNS["repair_time"])
FAILURE_CLOCK = ast.literal_eval(BREAKDOWNS["failure_clock"])
assert (MTTF, REPAIR, FAILURE_CLOCK) == (90, 20, "busy")
_repair_call = BREAKDOWNS["repair_time"].body
REPAIR_RANGE = tuple(ast.literal_eval(arg) for arg in _repair_call.args)
assert REPAIR_RANGE == (10, 30)

# Average scheduled fitters over the shift, from the staffing list.
STAFFING = STATIONS["Assembly"]["staffing"]
_changes = [*STAFFING, (SHIFT, None)]
MEAN_FITTERS = sum(Fraction(value * (end - start)) for (start, value), (end, _) in zip(_changes, _changes[1:])) / SHIFT
LUNCH = (STAFFING[1][0], STAFFING[2][0])
assert MEAN_FITTERS == Fraction(15, 8) and LUNCH == (240, 300)

# Rough capacity in parts per shift: shift minutes times average servers over mean minutes
# per part. With failures on a busy clock, each cutting minute brings REPAIR / MTTF minutes
# of repair on average, so a part costs mean * (1 + REPAIR / MTTF) machine-minutes. This
# ignores variability, blocking, and the time to fill the line, so the simulated output sits
# below it. The README states the bottleneck but no capacities (unsourced here).
SERVERS = {name: STATIONS[name]["capacity"] for name in NAMES}
SERVERS["Assembly"] = MEAN_FITTERS
CNC_PART = STATIONS["CNC"]["mean"] * (1 + REPAIR / MTTF)
CAPACITY = {name: SHIFT * SERVERS[name] / STATIONS[name]["mean"] for name in NAMES}
CNC_WITH_FAILURES = SHIFT * SERVERS["CNC"] / CNC_PART
# Assembly with both fitters all shift, before the lunch hour is counted.
ASSEMBLY_FULL = SHIFT * STATIONS["Assembly"]["capacity"] / STATIONS["Assembly"]["mean"]
assert round(float(ASSEMBLY_FULL)) == 148
assert {name: float(value) for name, value in CAPACITY.items()} == {
    "Saw": 160,
    "CNC": 160,
    "Wash": 192,
    "Assembly": 138.46153846153845,
    "Pack": 160,
}
assert round(float(CNC_PART), 2) == 7.33 and round(float(CNC_WITH_FAILURES)) == 131
WITH_FAILURES = {**CAPACITY, "CNC": CNC_WITH_FAILURES}
BOTTLENECK = min(WITH_FAILURES, key=WITH_FAILURES.get)
readme_states("The CNC machines are the bottleneck")
# Every blank takes one route, saw to pack: no branch sends a part elsewhere, and FlowSim
# has no rework loops (README "Operations examples" and "Scope and limits").
readme_states("every blank follows the same routing")
readme_states("rework loops are not implemented")
_line_text = "\n".join(LINE_CODE)
assert _line_text.count("model.route(") == 1 and "model.branch(" not in _line_text
# The CNC resource chart is captured zoomed to these minutes of day 1.
CNC_WINDOW = CAPTURED["cnc_window"]
assert CNC_WINDOW == [250, 400] and CNC_WINDOW[1] <= SHIFT
assert BOTTLENECK == "CNC"
assert RELEASED > max(WITH_FAILURES.values())

# The study's results (snippets/line.py calls line_study).
SCENARIOS = CAPTURED["scenarios"]
assert SCENARIOS == [*BUFFER_PLANS, "Two each, no CNC failures"]
assert CAPTURED["durations"] == [SHIFT] and CAPTURED["drain"] == [False] and CAPTURED["replications"] == [20]
COMPLETED = CAPTURED["completed"]
OUTPUT = {}
for name in SCENARIOS:
    OUTPUT[name] = t_interval(COMPLETED[name])
    assert all(close(a, b) for a, b in zip(OUTPUT[name], CAPTURED["output"][name]))


def paired(scenario, baseline):
    return t_interval([b - a for a, b in zip(COMPLETED[baseline], COMPLETED[scenario])])


GAINS = {name: paired(name, "No buffers") for name in SCENARIOS[1:]}
for name in SCENARIOS[1:]:
    assert all(close(a, b) for a, b in zip(GAINS[name], CAPTURED["gains"][name]))
MOVE = paired("Five before Assembly", "Two each")
NO_FAILURES = paired("Two each, no CNC failures", "Two each")
# snippets/line.py also asks FlowSim for these pairings against two each.
MOVED = CAPTURED["moved"]
assert list(MOVED) == ["No buffers", "Five before Assembly", "Two each, no CNC failures"]
assert all(close(a, b) for a, b in zip(MOVE, MOVED["Five before Assembly"]))
assert all(close(a, b) for a, b in zip(NO_FAILURES, MOVED["Two each, no CNC failures"]))
assert close(MOVED["No buffers"][0], -GAINS["Two each"][0])
# README "Machining line": two spaces in front of each station add more than ten
# parts per shift relative to no buffers, moving those spaces in front of assembly changes
# output by less than one part, and removing the CNC failures adds about as many parts again.
readme_states("two spaces in front of each station add more than ten parts per shift relative to no buffers")
readme_states("moving those spaces in front of assembly changes output by less than one part")
readme_states("removing the CNC failures adds about as many parts again")
readme_states("since there is no shared repair crew")
# The no-failure row in the gains table pairs with no buffers, so it holds both gains.
BOTH = GAINS["Two each, no CNC failures"][0]
assert close(BOTH, GAINS["Two each"][0] + NO_FAILURES[0])
# Pairing on common shifts gives the buffer gain a narrower interval than either plan's own.
_width = lambda values: values[2] - values[1]
assert _width(GAINS["Two each"]) < min(_width(OUTPUT["No buffers"]), _width(OUTPUT["Two each"]))
assert GAINS["Two each"][0] > 10
assert abs(MOVE[0]) < 1
# The relocation interval spans zero, so placement makes no clear difference.
assert MOVE[1] < 0 < MOVE[2]
assert 0.8 < NO_FAILURES[0] / GAINS["Two each"][0] < 1.25


def station_mean(scenario, station, metric):
    values = CAPTURED["stations"][scenario][station][metric]
    assert len(values) == 20
    return sum(values) / len(values)


# The saw is occupied (cutting or holding a blocked blank) all shift, so it never starves.
for name in SCENARIOS:
    assert station_mean(name, "Saw", "utilization") >= 0.999
    assert close(station_mean(name, "Assembly", "mean_scheduled_servers"), float(MEAN_FITTERS))
# The viewer screenshots show day 1 of the "Two each" plan (snippets/line.py).
assert close(CAPTURED["stations"]["Two each"]["Assembly"]["mean_scheduled_servers"][0], float(MEAN_FITTERS))
# Both relocation plans hold the same number of waiting spaces (examples/operations.py).
SPACES = sum(BUFFER_PLANS["Two each"])
assert SPACES == sum(BUFFER_PLANS["Five before Assembly"]) == 8
CNC_BLOCKED = {name: station_mean(name, "CNC", "blocking_fraction") for name in SCENARIOS}
CNC_DOWN = {name: station_mean(name, "CNC", "downtime_fraction") for name in SCENARIOS}
assert CNC_DOWN["Two each, no CNC failures"] == 0
assert CNC_BLOCKED["No buffers"] > CNC_BLOCKED["Two each"]


def parts(value):
    return f"{float(value):.0f}"


def percent(value):
    return f"{value:.0%}"


def interval_text(values, places=1):
    mean, lower, upper = values
    return f"{mean:.{places}f} (95% CI {lower:.{places}f} to {upper:.{places}f})"


# ---------------------------------------------------------------------------
# Display layer. Colors, layout, captions, and timing live here; fonts and caption rules
# come from ../shared/explainer.py.
# ---------------------------------------------------------------------------

OPS_NOTE = "examples/operations.py"
NO_FAILURE_PURPLE = ManimColor("#CC79A7")
SNIPPET_NOTE = "manim/machining-line/snippets/line.py"
PLAN_COLORS = {
    "No buffers": ALERT,
    "Two each": WAIT_BLUE,
    "Five before Assembly": ACCEPT,
    "Two each, no CNC failures": NO_FAILURE_PURPLE,
}


def line_row(y=1.65):
    specs = [(("Blanks", ("source",)), {})]
    for name in NAMES:
        servers = STATIONS[name]["capacity"]
        noun = "fitters" if name == "Assembly" else ("machines" if servers > 1 else "server")
        specs.append(((name, (f"{servers} {noun}",)), {}))
    boxes = same_size_boxes(specs)
    row = VGroup(*boxes).arrange(RIGHT, buff=0.42)
    # Six boxes and five arrows must stay 0.5 units inside the 14.2-unit frame.
    if row.width > 13.0:
        row.scale_to_fit_width(13.0)
    row.move_to([0, y, 0])
    arrows = VGroup(*(make_arrow(a.get_right(), b.get_left()) for a, b in zip(boxes, boxes[1:])))
    return row, arrows


class CapacityChart:
    """Rough capacity per station as vertical bars, with the blanks released for scale."""

    BASE, TOP = -2.7, 1.4

    def __init__(self):
        self.top_value = 200
        self.xs = [-4.4 + 2.2 * index for index in range(len(NAMES))]

    def y(self, value):
        return self.BASE + (self.TOP - self.BASE) * float(value) / self.top_value

    def axes(self):
        group = VGroup(Line([-5.6, self.BASE, 0], [5.4, self.BASE, 0], color=INK, stroke_width=2))
        for value in (0, 50, 100, 150, 200):
            grid = Line([-5.6, self.y(value), 0], [5.4, self.y(value), 0], color=BORDER, stroke_width=1)
            grid.set_z_index(-2)
            group.add(grid)
            group.add(label(str(value), size=TICK_SIZE).move_to([-5.9, self.y(value), 0]))
        # Each station's name, then its mean minutes per part, top-aligned so the baselines
        # line up.
        for x, name in zip(self.xs, NAMES):
            group.add(label(name, size=22).move_to([x, self.BASE - 0.18, 0], aligned_edge=UP))
            minutes = label(f"{float(STATIONS[name]['mean']):g} min", size=20, color=MUTED)
            group.add(minutes.move_to([x, self.BASE - 0.56, 0], aligned_edge=UP))
        group.add(label("Rough capacity (parts per shift)", size=22).move_to([-5.6, self.TOP + 0.45, 0], aligned_edge=LEFT))
        return group

    def bar(self, name, value, color):
        index = NAMES.index(name)
        bar = make_bar(1.3, self.y(value) - self.BASE, color).move_to([self.xs[index], (self.y(value) + self.BASE) / 2, 0])
        text = with_backing(label(parts(value), size=22)).next_to(bar, UP, buff=0.1)
        return VGroup(bar, text)


class Part1Line(CodeScene):
    def construct(self):
        self.title_card(1, "Modeling the machining line")
        row, arrows = line_row()
        self.play(FadeIn(row), Create(arrows), run_time=1.0)
        self.say(f"Each blank, a raw part, is one FlowSim customer. It visits {len(NAMES)} stations, saw to pack.")
        self.pause("line")
        self.say("A station has identical servers and one line. CNC (computer numerical control) is automated cutting.")
        self.pause("station")
        self.say("Every blank follows this one routing. No part is scrapped or reworked.")
        self.pause("routing")

        lines = excerpt(LINE_CODE, "    blanks = model.source(", 12)
        self.say(f"A blank is released every {SOURCE['interarrival']} minutes, {RELEASED} in a {SHIFT}-minute shift.")
        self.show_code(lines, OPS_NOTE + ", machining_line", top=0.75, size=18)
        self.highlight(2, 3)
        self.pause("release")
        self.say(f"Each lambda rng: draws a random time. The saw takes {SAW_RANGE[0]} to {SAW_RANGE[1]} minutes.")
        self.highlight(8)
        self.pause("saw-time")
        self.say("A buffer is the waiting space in front of a station. The saw has none.")
        self.highlight(9)
        self.pause("buffer")
        self.say('external_overflow="wait" holds released blanks outside the line. They enter when the saw is free.')
        self.highlight(10)
        self.pause("raw-stock")
        self.say("A finished part blocks its machine while the next buffer is full.")
        self.drop_code()
        self.pause("blocking")
        self.say("The saw never runs short of blanks, so the line is saturated.")
        self.pause("saturated")
        self.say(f"completed_at_close counts parts done by minute {SHIFT}. It measures one shift's output from an empty line.")
        self.pause("end", hold=3.5)


class Part2Capacity(CodeScene):
    def construct(self):
        self.title_card(2, "Finding the bottleneck")
        chart = CapacityChart()
        self.play(FadeIn(chart.axes()), run_time=0.6)
        bars = {name: chart.bar(name, CAPACITY[name], BORDER) for name in NAMES}
        bars["Assembly"] = chart.bar("Assembly", ASSEMBLY_FULL, BORDER)
        self.play(*(FadeIn(bar) for bar in bars.values()), run_time=0.8)
        self.say("Rough capacity is shift minutes × servers ÷ mean minutes per part.")
        self.pause("rough")
        self.say("It ignores variability, blocking, and filling an empty line. Simulated output falls below it.")
        self.pause("ignores")

        lines = excerpt(LINE_CODE, "    assembly = model.station(", 9)
        self.say(f"Assembly has one fitter from minute {LUNCH[0]} to {LUNCH[1]}, for lunch.")
        self.clear_stage()
        self.show_code(lines, OPS_NOTE + ", machining_line", y=CONTENT_Y, size=22)
        self.highlight(4, 5)
        self.pause("lunch")
        self.say(f"A saved viewer page shows day 1's scheduled fitters, {float(MEAN_FITTERS):.3f} on average.")
        shot = screenshot(HERE, CAPTURED, "resources_assembly", width=11.0, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.drop_code()
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("fitters")

        lines = excerpt(LINE_CODE, "    breakdowns = (", 9)
        self.say(f"A CNC machine fails after {parts(MTTF)} busy minutes on average.")
        self.show_code(lines, OPS_NOTE + ", machining_line", y=CONTENT_Y, size=22, drop=(shot,))
        self.highlight(2)
        self.pause("failures")
        self.say(f"Repair takes {REPAIR_RANGE[0]} to {REPAIR_RANGE[1]} minutes, {parts(REPAIR)} on average. There is no shared repair crew.")
        self.highlight(3)
        self.pause("repair")
        self.say('failure_clock="busy" counts only cutting time toward the next failure.')
        self.highlight(4)
        self.pause("clock")
        self.say(
            f"Minutes {CNC_WINDOW[0]} to {CNC_WINDOW[1]} of day 1, with two buffer spaces each. "
            "Black marks broken CNC machines, green blocked ones.",
        )
        shot = screenshot(HERE, CAPTURED, "resources_cnc", width=11.0, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.2, 0])
        self.drop_code()
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("cnc-chart")

        self.say(f"With lunch counted, assembly's rough capacity falls to about {parts(CAPACITY['Assembly'])} parts.")
        self.clear_stage()
        bars["Assembly"] = chart.bar("Assembly", CAPACITY["Assembly"], BORDER)
        self.play(FadeIn(chart.axes()), *(FadeIn(bar) for bar in bars.values()), run_time=0.8)
        self.pause("lunch-chart")
        self.say(
            f"Repairs add {parts(REPAIR)} minutes per {parts(MTTF)} busy minutes. A {parts(STATIONS['CNC']['mean'])}-minute part costs "
            f"{parts(STATIONS['CNC']['mean'])} × (1 + {parts(REPAIR)}/{parts(MTTF)}), about {float(CNC_PART):.1f} machine-minutes.",
        )
        cnc_bar = chart.bar("CNC", CNC_WITH_FAILURES, ALERT)
        self.play(FadeOut(bars["CNC"]), run_time=0.4)
        self.play(FadeIn(cnc_bar), run_time=0.6)
        self.pause("cnc")
        self.say(f"CNC, at about {parts(CNC_WITH_FAILURES)} parts, has the least capacity. It is the bottleneck.")
        self.pause("end", hold=3.5)


class Part3Buffers(CodeScene):
    def construct(self):
        self.title_card(3, "Comparing buffer plans")
        lines = excerpt(OPERATIONS_LINES, "# Machining line buffer plans, as waiting spaces in front of CNC, Wash,", 8)
        self.show_code(lines, OPS_NOTE, top=2.3, size=20)
        self.highlight(3, 7)
        self.say("Each plan sets the spaces before CNC, wash, assembly, and pack.")
        self.pause("plans")
        self.say(f'Both "Two each" and "Five before Assembly" place {SPACES} spaces. They put them at different stations.')
        self.pause("budget")

        rows = SCENARIOS[:3]
        chart = RowChart(rows, 140, [90, 100, 110, 120, 130, 140], "Parts finished by closing", left=-1.6, top=1.5, x_min=90)
        self.say(
            f"With no buffers, the line finishes {OUTPUT['No buffers'][0]:.1f} parts per shift on average. "
            f"Whiskers are 95% confidence intervals (CIs) over {len(COMPLETED['No buffers'])} shifts.",
        )
        self.drop_code()
        self.play(FadeIn(chart.axes()), run_time=0.6)
        self.play(FadeIn(chart.interval(0, *OUTPUT["No buffers"], PLAN_COLORS["No buffers"])), run_time=0.6)
        self.pause("none")
        mean, lower, upper = GAINS["Two each"]
        self.say(f"Two spaces each add {mean:.1f} parts per shift over no buffers. Both plans run the same shifts, so the gain is paired.")
        self.play(FadeIn(chart.interval(1, *OUTPUT["Two each"], PLAN_COLORS["Two each"])), run_time=0.6)
        self.pause("two")
        self.say(
            f"Moving the spaces before assembly changes output by {MOVE[0]:.2f} parts. "
            f"Against two each, the 95% CI is {number_text(f'{MOVE[1]:.2f}')} to {MOVE[2]:.2f}, so no clear difference.",
        )
        self.play(FadeIn(chart.interval(2, *OUTPUT["Five before Assembly"], PLAN_COLORS["Five before Assembly"])), run_time=0.6)
        self.pause("five")
        lines = excerpt(file_lines(HERE / "snippets" / "line.py"), "moved = comparison.differences(", 9)
        self.say('baseline="Two each" subtracts that plan\'s output from each plan\'s. It pairs them shift by shift.')
        self.clear_stage()
        self.code_and_table(lines, SNIPPET_NOTE, HERE, CAPTURED, "moved", size=20, max_width=8.0, side=True)
        self.pause("moved")

        self.say(
            f"Buffers cut CNC blocked time from {percent(CNC_BLOCKED['No buffers'])} to {percent(CNC_BLOCKED['Two each'])}. "
            f"Machine time is {STATIONS['CNC']['capacity']} machines × {SHIFT} minutes.",
        )
        self.clear_stage()
        blocked = RowChart(rows, 0.2, [0, 0.05, 0.1, 0.15, 0.2], "CNC blocked share of machine time", left=-1.6, top=1.5)
        self.play(FadeIn(blocked.axes(tick_text=lambda v: f"{v:.0%}")), run_time=0.6)
        for index, name in enumerate(rows):
            bar = make_bar(blocked.x(CNC_BLOCKED[name]) - blocked.left, 0.42, PLAN_COLORS[name])
            bar.move_to([(blocked.x(CNC_BLOCKED[name]) + blocked.left) / 2, blocked.y(index), 0])
            text = label(percent(CNC_BLOCKED[name]), size=22).next_to(bar, RIGHT, buff=0.15)
            self.play(FadeIn(bar), FadeIn(text), run_time=0.5)
        self.pause("blocked")

        lines = excerpt(file_lines(HERE / "snippets" / "line.py"), "comparison = line_study()", 10)
        self.say(
            f"Pairing narrows the gain's 95% CI to {GAINS['Two each'][1]:.1f} to {GAINS['Two each'][2]:.1f}. "
            f"The last row also ends CNC failures.",
        )
        self.clear_stage()
        self.code_and_table(lines, SNIPPET_NOTE, HERE, CAPTURED, "gains", size=20, max_width=8.0, side=True)
        self.pause("end", hold=3.5)


class Part4Failures(CodeScene):
    def construct(self):
        self.title_card(4, "Measuring the cost of CNC failures")
        chart = RowChart(SCENARIOS, 140, [90, 100, 110, 120, 130, 140], "Parts finished by closing", left=-1.6, top=1.5, x_min=90)
        self.play(FadeIn(chart.axes()), run_time=0.6)
        self.play(
            *(FadeIn(chart.interval(index, *OUTPUT[name], PLAN_COLORS[name])) for index, name in enumerate(SCENARIOS[:3])),
            run_time=0.6,
        )
        name = SCENARIOS[3]
        self.say(f"Without CNC failures, two spaces each finish {OUTPUT[name][0]:.1f} parts.")
        self.play(FadeIn(chart.interval(3, *OUTPUT[name], PLAN_COLORS[name])), run_time=0.6)
        self.pause("no-failures")
        self.say(
            f"That is {NO_FAILURES[0]:.1f} more than with failures (95% CI {NO_FAILURES[1]:.1f} to {NO_FAILURES[2]:.1f}). "
            f"The buffers added {GAINS['Two each'][0]:.1f}.",
        )
        self.pause("compare")
        self.say(f"Under two each, CNC machines are down {percent(CNC_DOWN['Two each'])} of machine time.")
        self.pause("down")

        self.say("comparison.viewer saves each plan's paired gain as an offline page.")
        self.clear_stage()
        shot = screenshot(HERE, CAPTURED, "comparison_differences", width=11.0, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.3, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("viewer")
        self.say(f"Buffers add parts by cutting CNC blocking. Ending CNC failures too adds about as many again, {BOTH:.1f} parts in all.")
        self.pause("end", hold=3.5)
