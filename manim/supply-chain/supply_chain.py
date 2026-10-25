"""FlowSim: the bullwhip effect, in four parts.

Each part is a manim-slides Slide, so the same source renders a continuous MP4 per part
(joined into one video by ../render.sh) and a deck with a break at every pause():

    Part1Chain      the four-stage beer game and its order-up-to policy
    Part2Bullwhip   orders amplify up the chain
    Part3Sharing    sharing consumer demand and a longer average
    Part4Capacity   brewing at a station instead of a fixed lead time

Sources: examples/supply_chain.py (beer_game, bullwhip_study, capacity_study,
amplification), snippets/bullwhip.py, snippets/capacity.py, and the README sections
"Inventory and ordering", "Supply chain example", and "Production at stations". capture.py
runs both studies in the project environment and writes captured/numbers.json; the
assertions below recompute every displayed number from the per-run values and check each
README result against the README's own digits. Captions, fonts, and breaks come from
../shared/explainer.py.

    bash ../render.sh supply-chain preview|review|final
"""

import math
import re
from pathlib import Path

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    Create,
    FadeIn,
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
    TICK_SIZE,
    label,
    make_arrow,
    make_bar,
    footnote,
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
SUPPLY = ROOT / "examples" / "supply_chain.py"
GAME_CODE = function_lines(SUPPLY, "beer_game")
GAME = "\n".join(GAME_CODE)
STAGES = module_constant(SUPPLY, "STAGES")
WEEKS = module_constant(SUPPLY, "WEEKS")
WARMUP = module_constant(SUPPLY, "WARMUP")
BATCH = module_constant(SUPPLY, "BATCH")
DEMAND_MEAN, DEMAND_SD = (int(v) for v in re.search(r"rng\.normal\((\d+), (\d+)\)", GAME).groups())
LEAD = int(re.search(r"lead_time: int = (\d+)", GAME)[1])
WINDOW = int(re.search(r"window: int = (\d+)", GAME)[1])
SAFETY = int(re.search(r"safety_factor=(\d+)", GAME)[1])
INITIAL = int(re.search(r"initial=(\d+) \* lead_time", GAME)[1]) * LEAD
assert INITIAL == 200
assert STAGES == ["Retailer", "Wholesaler", "Distributor", "Factory"]
assert (DEMAND_MEAN, DEMAND_SD, LEAD, WINDOW, SAFETY, WEEKS, WARMUP, BATCH) == (100, 20, 2, 5, 1, 104, 20, 25)
readme_states("Consumer demand averages 100 cases per week with a standard deviation of 20")
readme_states("every stage receives shipments two weeks after they are sent")
readme_states("each stage carries one standard deviation of safety stock")
readme_states("`bullwhip_study` runs 20 replications of 104 weeks with a 20-week warm-up")
BULL = CAPTURED["bullwhip"]
assert BULL["warmup"] == [WARMUP] and BULL["duration"] == [WEEKS]
SCENARIOS = BULL["scenarios"]
assert SCENARIOS == ["Forecast from orders", "Share consumer demand", "Ten-week average"]
for scenario in SCENARIOS:
    for stage in STAGES:
        assert BULL["runs"][scenario][stage]["periods"] == [WEEKS - WARMUP] * 20


def interval_of(runs, scenario, stage, metric):
    return t_interval(runs[scenario][stage][metric])


def check(values, captured):
    assert all(close(a, b) for a, b in zip(values, captured)), (values, captured)
    return values


def readme_value(value, text, scale=1, places=None):
    """Assert that a value rounds to the README's digits and return those digits."""
    places = len(text.split(".")[1]) if "." in text else 0
    assert f"{value * scale:.{places}f}" == text, (value, text)
    return text


RATIO = {
    stage: {scenario: check(interval_of(BULL["runs"], scenario, stage, "bullwhip_ratio"), BULL["ratio"][stage][scenario]) for scenario in SCENARIOS}
    for stage in STAGES
}
FILL = {
    stage: {scenario: check(interval_of(BULL["runs"], scenario, stage, "fill_rate"), BULL["fill"][stage][scenario]) for scenario in SCENARIOS}
    for stage in ["Retailer", "Wholesaler"]
}
# Amplification: each stage's order variance over consumer demand variance, which is the
# retailer's incoming variance, averaged over runs (examples/supply_chain.py amplification).
AMPLIFICATION = {}
for scenario in SCENARIOS:
    consumer = BULL["runs"][scenario]["Retailer"]["demand_variance"]
    AMPLIFICATION[scenario] = {
        stage: sum(o / c for o, c in zip(BULL["runs"][scenario][stage]["order_variance"], consumer)) / len(consumer)
        for stage in STAGES
    }
for row in BULL["growth"]:
    for stage in STAGES:
        assert close(AMPLIFICATION[row["scenario"]][stage], row[stage])
paired = [
    b - a
    for a, b in zip(
        BULL["runs"]["Forecast from orders"]["Factory"]["bullwhip_ratio"],
        BULL["runs"]["Share consumer demand"]["Factory"]["bullwhip_ratio"],
    )
]
SHARE_DROP = check(t_interval(paired), BULL["factory_differences"]["Share consumer demand"])

# The closed form for the retailer (README, Chen et al. 1999, equation 14.8).
CLOSED = 1 + 2 * LEAD / WINDOW + 2 * LEAD**2 / WINDOW**2
readme_states("the retailer's ratio is 1 + 2L/p + 2L^2/p^2 (Chen et al. 1999, equation 14.8), i.e., 2.12 for p = 5 and L = 2")
readme_value(CLOSED, "2.12")

# README "Supply chain example", saved bullwhip study.
readme_states("forecasting from orders gives a retailer bullwhip ratio of 2.25 (95% CI 2.18 to 2.32), above the closed-form 2.12")
for value, text in zip(RATIO["Retailer"]["Forecast from orders"], ("2.25", "2.18", "2.32")):
    readme_value(value, text)
readme_states("factory orders vary 37.6 times as much as consumer demand")
readme_value(AMPLIFICATION["Forecast from orders"]["Factory"], "37.6")
readme_states("lowers the factory's own ratio by 0.89 (95% CI 0.77 to 1.00)")
readme_value(-SHARE_DROP[0], "0.89")
readme_value(-SHARE_DROP[2], "0.77")
readme_value(-SHARE_DROP[1], "1.00")
readme_states("cuts factory order variance to 9.7 times consumer demand")
readme_value(AMPLIFICATION["Share consumer demand"]["Factory"], "9.7")
readme_states("(factory order variance 8.6 times consumer demand)")
readme_value(AMPLIFICATION["Ten-week average"]["Factory"], "8.6")
readme_states("raises the retailer's fill rate from 87.0% to 91.4%")
readme_value(FILL["Retailer"]["Forecast from orders"][0], "87.0", scale=100)
readme_value(FILL["Retailer"]["Ten-week average"][0], "91.4", scale=100)
readme_states("Sharing instead lowers the retailer's fill rate to 84.4%")
readme_value(FILL["Retailer"]["Share consumer demand"][0], "84.4", scale=100)
readme_states("its own fill rate falls from 83.4% to 77.9%")
readme_value(FILL["Wholesaler"]["Forecast from orders"][0], "83.4", scale=100)
readme_value(FILL["Wholesaler"]["Share consumer demand"][0], "77.9", scale=100)
# Sharing leaves the retailer unchanged, since the retailer already sees consumer demand.
assert all(
    close(a, b)
    for a, b in zip(
        BULL["runs"]["Share consumer demand"]["Retailer"]["order_variance"],
        BULL["runs"]["Forecast from orders"]["Retailer"]["order_variance"],
    )
)

# The ten-week average fills the most at both stages shown; demand is independent and
# identically distributed each week (rng.normal), so it has no trend or season.
for _stage in ["Retailer", "Wholesaler"]:
    assert max(FILL[_stage], key=lambda name: FILL[_stage][name][0]) == "Ten-week average"
assert "per_period=lambda rng: max(0.0, rng.normal(100, 20))" in GAME
readme_states("the retailer's ratio is 1 + 2L/p + 2L^2/p^2")
readme_states("The bullwhip ratio is the variance of a stage's orders divided by the variance of the orders it receives")
readme_states("each stage orders the target minus its inventory position (on hand plus on order minus backorders), or nothing when the position already meets the target")
readme_states("A production station's `service_time` is the time per unit")
readme_states('`shortage` is `"backorder"`')
readme_states('or `"lost"` (unfilled orders disappear')
assert 'shortage="backorder"' in GAME
readme_states("Safety stock is `safety_factor * sqrt(cover)` times")
readme_states("the first weeks carry a startup surge of orders that the warm-up excludes")
readme_states("because the inventory position counts units on order, so receipts never change it")
SUPPLY_LINES = excerpt(GAME_CODE, "    model.supply(", 4)
assert SUPPLY_LINES[1].strip() == "[consumers, *stages, factory],"

# The capacity study (snippets/capacity.py calls capacity_study).
CAP = CAPTURED["capacity"]
CAP_SCENARIOS = CAP["scenarios"]
assert CAP_SCENARIOS == ["Two-week lead time", "Brew 120 per week", "Brew 150 per week", "Brew 200 per week", "Brew 150, cover 3"]
BREW_RATES = {name: int(re.search(r"Brew (\d+)", name)[1]) for name in CAP_SCENARIOS if name.startswith("Brew")}
CAP_FILL = {name: check(interval_of(CAP["runs"], name, "Factory", "fill_rate"), CAP["fill"][name]) for name in CAP_SCENARIOS}
CAP_RATIO = {name: check(interval_of(CAP["runs"], name, "Factory", "bullwhip_ratio"), CAP["ratio"][name]) for name in CAP_SCENARIOS}
JOB_TIME = {}
for name in CAP_SCENARIOS[1:]:
    JOB_TIME[name] = check(t_interval(CAP["job_runs"][name]), CAP["job_time"][name][:3])
assert CAP["job_time"]["Two-week lead time"][3] == 0
# The four scenarios with two weeks of cover place the same factory orders, run by run.
SAME_ORDERS = CAP_SCENARIOS[:4]
for name in SAME_ORDERS[1:]:
    assert all(close(x, y) for x, y in zip(CAP["runs"][name]["Factory"]["order_variance"], CAP["runs"]["Two-week lead time"]["Factory"]["order_variance"]))
    assert all(close(x, y) for x, y in zip(CAP["runs"][name]["Factory"]["bullwhip_ratio"], CAP["runs"]["Two-week lead time"]["Factory"]["bullwhip_ratio"]))
readme_states("the factory fills 83.8% of its incoming orders in the same week with a two-week lead time (95% CI 82.4% to 85.3%)")
for value, text in zip(CAP_FILL["Two-week lead time"], ("83.8", "82.4", "85.3")):
    readme_value(value, text, scale=100)
readme_states("Brewing 120 cases per week lowers that fill rate to 76.5%, since a job then takes 2.29 weeks")
readme_value(CAP_FILL["Brew 120 per week"][0], "76.5", scale=100)
readme_value(JOB_TIME["Brew 120 per week"][0], "2.29")
readme_states("raises it to 88.3% and 94.2% with mean job times of 1.49 and 0.92 weeks")
readme_value(CAP_FILL["Brew 150 per week"][0], "88.3", scale=100)
readme_value(CAP_FILL["Brew 200 per week"][0], "94.2", scale=100)
readme_value(JOB_TIME["Brew 150 per week"][0], "1.49")
readme_value(JOB_TIME["Brew 200 per week"][0], "0.92")
readme_states("The factory's bullwhip ratio is 2.32 in all four scenarios")
readme_value(CAP_RATIO["Two-week lead time"][0], "2.32")
readme_states("Three weeks of cover at 150 cases per week raises the fill rate to 97.1% but also raises the factory's bullwhip ratio to 2.76 (95% CI 2.61 to 2.91)")
readme_value(CAP_FILL["Brew 150, cover 3"][0], "97.1", scale=100)
for value, text in zip(CAP_RATIO["Brew 150, cover 3"], ("2.76", "2.61", "2.91")):
    readme_value(value, text)
readme_states("the mean job time rises from 1.49 to 1.71 weeks")
readme_value(JOB_TIME["Brew 150, cover 3"][0], "1.71")
readme_states("(120 cases is 20% above it)")
assert BREW_RATES["Brew 120 per week"] == 1.2 * DEMAND_MEAN
readme_states("capacity above mean demand (120 cases is 20% above it) is not enough when orders arrive amplified, and a longer cover buys service with more variable orders")
assert CAP["brewing_station"] == "Brewhouse"


def pct(value, places=1):
    return f"{value * 100:.{places}f}%"


def ci(values, places=2, scale=1):
    _, lower, upper = values
    return f"{lower * scale:.{places}f} to {upper * scale:.{places}f}"


# ---------------------------------------------------------------------------
# Display layer. Colors, layout, captions, and timing live here; fonts and caption rules
# come from ../shared/explainer.py.
# ---------------------------------------------------------------------------

GAME_NOTE = "examples/supply_chain.py, beer_game"
SCENARIO_COLORS = {"Forecast from orders": ALERT, "Share consumer demand": WAIT_BLUE, "Ten-week average": ACCEPT}
CAP_COLORS = {
    "Two-week lead time": BORDER,
    "Brew 120 per week": ALERT,
    "Brew 150 per week": WAIT_BLUE,
    "Brew 200 per week": ACCEPT,
    "Brew 150, cover 3": ManimColor("#CC79A7"),
}
ORDER_RED = ManimColor("#9A6700")


def chain_row(y=1.2):
    specs = [(("Consumers", ("demand",)), {})] + [((stage, ("stock point",)), {}) for stage in STAGES]
    boxes = same_size_boxes(specs)
    row = VGroup(*boxes).arrange(RIGHT, buff=0.75)
    if row.width > 13.0:
        row.scale_to_fit_width(13.0)
    row.move_to([0, y, 0])
    up, down = VGroup(), VGroup()
    for a, b in zip(boxes, boxes[1:]):
        up.add(make_arrow(a.get_right() + 0.15 * UP, b.get_left() + 0.15 * UP, color=ORDER_RED))
        down.add(make_arrow(b.get_left() + 0.15 * DOWN, a.get_right() + 0.15 * DOWN, color=WAIT_BLUE))
    return row, up, down


class AmplificationChart:
    """Order variance over consumer demand variance, by stage, on a log scale (each
    gridline is ten times the one below), with one bar group per scenario."""

    BASE, TOP = -2.7, 1.1

    def __init__(self, scenarios):
        self.scenarios = scenarios
        self.xs = [-4.2 + 2.8 * index for index in range(len(STAGES))]

    def y(self, value):
        return self.BASE + (self.TOP - self.BASE) * math.log10(value) / 2

    def axes(self):
        group = VGroup(Line([-5.7, self.BASE, 0], [5.6, self.BASE, 0], color=INK, stroke_width=2))
        for value in (1, 10, 100):
            grid = Line([-5.7, self.y(value), 0], [5.6, self.y(value), 0], color=BORDER, stroke_width=1)
            grid.set_z_index(-2)
            group.add(grid)
            group.add(label(str(value), size=TICK_SIZE).move_to([-6.0, self.y(value), 0]))
        for x, stage in zip(self.xs, STAGES):
            group.add(label(stage, size=22).move_to([x, self.BASE - 0.18, 0], aligned_edge=UP))
        group.add(
            label("Order variance ÷ consumer demand variance (log scale)", size=22).move_to([-5.7, self.TOP + 0.45, 0], aligned_edge=LEFT),
        )
        return group

    def bar(self, scenario, stage):
        index = STAGES.index(stage)
        width = 2.1 / len(self.scenarios)
        offset = (self.scenarios.index(scenario) - (len(self.scenarios) - 1) / 2) * width
        value = AMPLIFICATION[scenario][stage]
        height = max(0.04, self.y(value) - self.BASE)
        bar = make_bar(width * 0.9, height, SCENARIO_COLORS[scenario]).move_to([self.xs[index] + offset, self.BASE + height / 2, 0])
        # Three significant figures, so the retailer's bar reads 2.25 as in the ratio chart.
        text = with_backing(label(f"{value:.3g}", size=20)).next_to(bar, UP, buff=0.08)
        return VGroup(bar, text)

    def legend(self):
        items = VGroup(
            *(
                VGroup(make_bar(0.32, 0.22, SCENARIO_COLORS[name]), label(name, size=22)).arrange(RIGHT, buff=0.15, aligned_edge=UP)
                for name in self.scenarios
            ),
        ).arrange(RIGHT, buff=0.5, aligned_edge=UP)
        return items.move_to([0, self.TOP + 0.95, 0])


class Part1Chain(CodeScene):
    def construct(self):
        self.title_card(1, "Modeling the beer game chain")
        row, up, down = chain_row()
        self.play(FadeIn(row), run_time=0.8)
        self.say("A stock point holds inventory and fills orders. It reorders from upstream.")
        self.pause("chain")
        self.say("model.supply lists the beer game's chain in order. Each week, orders flow up and shipments flow down.")
        notes = VGroup(
            label("orders", size=22, color=ALERT).next_to(up[0], UP, buff=0.4),
            label(f"shipments between stages, {LEAD}-week lead time", size=22, color=WAIT_BLUE).move_to(
                [VGroup(*down[1:]).get_x(), row.get_bottom()[1] - 0.35, 0],
            ),
        )
        notes[0].set_color(ORDER_RED).set_x(up.get_x()).set_y(row.get_top()[1] + 0.3)
        self.play(Create(up), Create(down), FadeIn(notes), run_time=1.0)
        self.show_code(SUPPLY_LINES, GAME_NOTE, top=notes.get_bottom()[1] - 0.45, size=20)
        self.highlight(1)
        self.pause("flows")

        lines = excerpt(GAME_CODE, "    consumers = model.demand(", 4)
        self.say(f"lambda rng: draws each week's demand, {DEMAND_MEAN} cases on average. The standard deviation is {DEMAND_SD}.")
        self.show_code(lines, GAME_NOTE, top=0.0, size=20)
        self.highlight(2)
        self.pause("demand")

        lines = excerpt(GAME_CODE, "        model.stock_point(", 11)
        self.say(f'Each stage starts with {INITIAL} cases. shortage="backorder" ships unfilled orders later, and "lost" drops them.')
        self.clear_stage()
        self.panel = self.band = None
        self.show_code(lines, GAME_NOTE, y=CONTENT_Y, size=22)
        self.highlight(2, 4)
        self.pause("stock-point")
        self.say("order_up_to orders target minus inventory position, never below zero. Position is on hand plus on order minus backorders.")
        self.highlight(5, 8)
        self.pause("policy")
        self.say(
            f"The target covers {LEAD} weeks at the {WINDOW}-week average of incoming orders. "
            f"Safety stock adds {SAFETY} × √{LEAD} standard deviations, √{LEAD} for the {LEAD} weeks.",
        )
        self.pause("target")
        self.say(f"Each run lasts {WEEKS} weeks. Stock-point measures skip the first {WARMUP}, the warm-up.")
        self.pause("end", hold=3.5)


class Part2Bullwhip(CodeScene):
    def construct(self):
        self.title_card(2, "Measuring the bullwhip effect")
        shot = screenshot(HERE, CAPTURED, "orders", width=11.5, height=5.6)
        shot.move_to([0, CONTENT_Y - 0.25, 0])
        self.play(FadeIn(shot), run_time=0.6)
        self.say("In the first run, factory orders swing far more than consumer demand.")
        self.pause("orders")
        self.say("The dashed line marks the end of the warm-up. Orders surge at startup, before it.")
        self.pause("warmup")

        mean, lower, upper = RATIO["Retailer"]["Forecast from orders"]
        self.say("Variance measures how widely orders swing. The bullwhip ratio divides placed-order by received-order variance.")
        self.clear_stage()
        chart = RowChart(["Closed form", "Simulated, 20 runs"], 3.0, [1.0, 1.5, 2.0, 2.5, 3.0], "Retailer bullwhip ratio", left=-1.4, top=1.2, x_min=1.0)
        self.play(FadeIn(chart.axes(tick_text=lambda v: f"{v:.1f}")), run_time=0.6)
        self.pause("ratio")
        self.say(f"Theory without safety stock gives 1 + 2L/p + 2L²/p² = {CLOSED:.2f}. L = {LEAD} is the lead time, and p = {WINDOW} is the averaging window.")
        dot = chart.interval(0, CLOSED, CLOSED, CLOSED, INK)
        self.play(FadeIn(dot), FadeIn(chart.value_label(0, chart.x(CLOSED), f"{CLOSED:.2f}")), run_time=0.6)
        self.pause("closed")
        self.say(f"The simulation, with safety stock, gives {mean:.2f}. Its 95% confidence interval (CI) is {lower:.2f} to {upper:.2f}.")
        self.play(
            FadeIn(chart.interval(1, mean, lower, upper, ALERT)),
            FadeIn(chart.value_label(1, chart.x(mean), f"{mean:.2f}")),
            run_time=0.6,
        )
        self.pause("simulated")

        amp = AmplificationChart(["Forecast from orders"])
        self.say("Each stage multiplies the swing it receives. Orders vary more at every stage up the chain.")
        self.clear_stage()
        self.play(FadeIn(amp.axes()), FadeIn(footnote("Each gridline is ten times the one below.")), run_time=0.6)
        for stage in STAGES:
            self.play(FadeIn(amp.bar("Forecast from orders", stage)), run_time=0.5)
        self.pause("compound")
        factory = AMPLIFICATION["Forecast from orders"]["Factory"]
        self.say(f"Factory orders vary {factory:.1f} times as much as consumer demand.")
        self.pause("end", hold=3.5)


class Part3Sharing(CodeScene):
    def construct(self):
        self.title_card(3, "Sharing consumer demand")
        study = excerpt(function_lines(SUPPLY, "bullwhip_study"), "    return compare(", 11)
        self.show_code(study, "examples/supply_chain.py, bullwhip_study", top=2.3, size=22)
        self.highlight(3)
        self.say('forecast_from="end_demand" shares consumer demand. Every stage forecasts from it.')
        self.pause("share")
        self.say("The third scenario averages ten weeks instead of five.")
        self.highlight(4)
        self.pause("ten")

        amp = AmplificationChart(SCENARIOS)
        self.say("Sharing leaves retailer orders unchanged. The retailer already sees consumer demand.")
        self.drop_code()
        self.play(FadeIn(amp.axes()), FadeIn(amp.legend()), FadeIn(footnote("Each gridline is ten times the one below.")), run_time=0.6)
        for scenario in SCENARIOS[:2]:
            self.play(*(FadeIn(amp.bar(scenario, stage)) for stage in STAGES), run_time=0.6)
        self.pause("shared")
        self.say(f"A ten-week average lowers every stage's ratio. Factory orders vary {AMPLIFICATION[SCENARIOS[2]]['Factory']:.1f} times as much as consumer demand.")
        self.play(*(FadeIn(amp.bar(SCENARIOS[2], stage)) for stage in STAGES), run_time=0.6)
        self.pause("ten-chart")
        self.say(
            f"Sharing lowers the factory's own ratio by {-SHARE_DROP[0]:.2f}. "
            f"Paired on the same demand, the 95% CI is {-SHARE_DROP[2]:.2f} to {-SHARE_DROP[1]:.2f}.",
        )
        self.clear_stage()
        own = RowChart(SCENARIOS[:2], 3.0, [1.0, 1.5, 2.0, 2.5, 3.0], "Factory bullwhip ratio (its own incoming orders)", left=-1.4, top=1.2, x_min=1.0)
        self.play(FadeIn(own.axes(tick_text=lambda v: f"{v:.1f}")), run_time=0.6)
        for index, name in enumerate(SCENARIOS[:2]):
            mean, lower, upper = RATIO["Factory"][name]
            self.play(
                FadeIn(own.interval(index, mean, lower, upper, SCENARIO_COLORS[name])),
                FadeIn(own.value_label(index, own.x(mean), f"{mean:.2f}")),
                run_time=0.5,
            )
        self.pause("drop")

        self.say("Fill rate is the share of incoming cases filled in the week they arrive.")
        self.clear_stage()
        rows = [f"{stage}, {name.lower()}" for stage in ["Retailer", "Wholesaler"] for name in SCENARIOS]
        # The value labels sit right of the chart, so its right edge leaves room for them
        # inside the 0.45-unit frame margin (Codex review, 2026-10-24).
        chart = RowChart(rows, 1.0, [0.7, 0.8, 0.9, 1.0], "Fill rate", left=-0.6, right=5.3, top=1.4, bottom=-2.4, x_min=0.7)
        self.play(FadeIn(chart.axes(tick_text=lambda v: f"{v:.0%}")), run_time=0.6)
        index = 0
        for stage in ["Retailer", "Wholesaler"]:
            for name in SCENARIOS:
                mean, lower, upper = FILL[stage][name]
                value = label(pct(mean), size=20).move_to([chart.right + 0.35, chart.y(index), 0], aligned_edge=LEFT)
                self.inside_frame(value)
                self.play(
                    FadeIn(chart.interval(index, mean, lower, upper, SCENARIO_COLORS[name])),
                    FadeIn(value),
                    run_time=0.4,
                )
                index += 1
        retail = FILL["Retailer"]
        self.say(
            f"Sharing lowers the retailer's fill rate to {pct(retail[SCENARIOS[1]][0])}.",
        )
        self.pause("retail")
        whole = FILL["Wholesaler"]
        self.say(
            f"The wholesaler plans from consumer demand but fills retailer orders. "
            f"Its fill rate falls to {pct(whole[SCENARIOS[1]][0])}.",
        )
        self.pause("wholesale")
        self.say("The ten-week average fills the most. Demand here has no trend or season.")
        self.pause("end", hold=3.5)


class Part4Capacity(CodeScene):
    def construct(self):
        self.title_card(4, "Modeling brewing capacity")
        lines = excerpt(GAME_CODE, "    if brews:", 7)
        self.show_code(lines, GAME_NOTE, top=2.3, size=22)
        self.highlight(1, 5)
        self.say("capacity_study swaps the factory's lead time for a brewhouse station.")
        self.pause("brewhouse")
        self.say(f"Each order splits into jobs of up to {BATCH} cases. service_time is weeks per case, not per job.")
        self.pause("jobs")
        rates = [BREW_RATES[name] for name in CAP_SCENARIOS[1:4]]
        self.say(f"The scenarios brew {rates[0]}, {rates[1]}, or {rates[2]} cases a week. Targets cover two weeks.")
        self.pause("rates")

        self.say(f"brewing.viewer saves one run as a web page. It shows the brewhouse queue at {rates[1]} a week.")
        shot = screenshot(HERE, CAPTURED, "production", width=11.0, height=5.4)
        shot.move_to([0, CONTENT_Y - 0.25, 0])
        self.drop_code()
        self.play(FadeIn(shot), run_time=0.6)
        self.pause("queue")

        rows = CAP_SCENARIOS
        chart = RowChart(rows, 1.0, [0.7, 0.8, 0.9, 1.0], "Factory fill rate", left=-2.4, right=3.0, top=1.4, x_min=0.7)
        columns = (3.95, 5.75)
        # The job column's header names its unit on a second line, bottom-aligned with the
        # one-line ratio header.
        job_header = VGroup(label("Mean job time", size=20), label("(weeks)", size=20)).arrange(DOWN, buff=0.08)
        header = [
            job_header.move_to([columns[0], chart.top + 0.3, 0], aligned_edge=DOWN),
            VGroup(label("Factory", size=20), label("bullwhip ratio", size=20)).arrange(DOWN, buff=0.08).move_to(
                [columns[1], chart.top + 0.3, 0],
                aligned_edge=DOWN,
            ),
        ]

        def job_text(index):
            name = rows[index]
            text = f"{JOB_TIME[name][0]:.2f}" if name in JOB_TIME else "none"
            # Bottom-aligned with the ratio column, so "none" shares the numbers' baseline.
            return label(text, size=20, color=INK if name in JOB_TIME else BORDER).move_to([columns[0], chart.y(index) - 0.12, 0], aligned_edge=DOWN)

        def ratio_text(index):
            return label(f"{CAP_RATIO[rows[index]][0]:.2f}", size=20).move_to([columns[1], chart.y(index) - 0.12, 0], aligned_edge=DOWN)

        two = CAP_FILL["Two-week lead time"]
        self.say(f"A two-week lead time fills {pct(two[0])} (95% CI {ci(two, 1, 100)}%).")
        self.clear_stage()
        self.play(FadeIn(chart.axes(tick_text=lambda v: f"{v:.0%}")), FadeIn(header[0]), run_time=0.6)
        self.play(FadeIn(chart.interval(0, *two, CAP_COLORS[rows[0]])), FadeIn(job_text(0)), run_time=0.5)
        self.pause("two-week")
        slow = CAP_FILL["Brew 120 per week"][0]
        self.say(
            f"Brewing {rates[0]}, 20% above mean demand, fills only {pct(slow)}. "
            f"Jobs average {JOB_TIME['Brew 120 per week'][0]:.2f} weeks from release to finish.",
        )
        self.play(FadeIn(chart.interval(1, *CAP_FILL[rows[1]], CAP_COLORS[rows[1]])), FadeIn(job_text(1)), run_time=0.5)
        self.pause("slow")
        self.say(
            f"Brewing {rates[1]} or {rates[2]} raises it to {pct(CAP_FILL[rows[2]][0])} "
            f"and {pct(CAP_FILL[rows[3]][0])}.",
        )
        for index in (2, 3):
            self.play(FadeIn(chart.interval(index, *CAP_FILL[rows[index]], CAP_COLORS[rows[index]])), FadeIn(job_text(index)), run_time=0.5)
        self.pause("fast")
        ratio = CAP_RATIO["Two-week lead time"][0]
        self.say(f"Position counts units on order, so brew speed cannot change orders. The factory's ratio is {ratio:.2f} in all four.")
        self.play(FadeIn(header[1]), *(FadeIn(ratio_text(index)) for index in range(4)), run_time=0.6)
        self.pause("same-orders")
        cover = CAP_RATIO["Brew 150, cover 3"]
        self.say(
            f"Three weeks of cover fill {pct(CAP_FILL[rows[4]][0])}. "
            f"The ratio rises to {cover[0]:.2f} (95% CI {ci(cover)}).",
        )
        self.play(FadeIn(chart.interval(4, *CAP_FILL[rows[4]], CAP_COLORS[rows[4]])), FadeIn(job_text(4)), run_time=0.5)
        self.play(FadeIn(ratio_text(4)), run_time=0.4)
        self.pause("cover")
        self.say("Faster brewing raises the fill rate and leaves orders unchanged. Three weeks of cover raises the fill rate and the factory's ratio.")
        self.pause("end", hold=3.5)
