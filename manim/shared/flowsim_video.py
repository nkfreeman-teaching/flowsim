"""Pieces the four FlowSim videos share: captured numbers, code panels, and screenshots.

The capture step (shared/capture_tools.py, run in the project environment) executes each
video's code and writes <slug>/captured/numbers.json with PNG screenshots. This module runs
in the manim environment. It checks that the captured files match the code on disk, reads
the code a panel shows from the real files, and builds the panels and screenshot frames.
"""

import ast
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

import numpy as np
from PIL import Image

from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    WHITE,
    Code,
    DashedLine,
    Dot,
    FadeIn,
    FadeOut,
    Group,
    ImageMobject,
    Line,
    ManimColor,
    Rectangle,
    RoundedRectangle,
    VGroup,
    config,
)

from explainer import (
    AXIS_TITLE_SIZE,
    BORDER,
    BOX_RADIUS,
    BOX_STROKE,
    CONTENT_Y,
    DATA_LABEL_SIZE,
    FAINT,
    INK,
    MUTED,
    TICK_SIZE,
    ExplainerScene,
    label,
    number_text,
    with_backing,
)

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CODE_FONT = "Nimbus Mono PS"
CODE_SIZE = 22
CODE_FILL = ManimColor("#F6F8FA")
HIGHLIGHT = ManimColor("#FFE9A8")
# A panel never shows more than this many lines (owner's format choice for these videos).
MAX_CODE_LINES = 15
# Student t quantiles for two-sided 95% intervals, keyed by degrees of freedom, from
# scipy.stats.t.ppf(0.975, df). The videos recompute every interval from run values.
T95 = {19: 2.093024054408263, 38: 2.0243941639119694}
# Colors the FlowSim viewers use for waiting and service, kept so a drawn chart and a
# screenshot of the viewer agree.
WAIT_BLUE = ManimColor("#0072B2")
SERVICE_ORANGE = ManimColor("#D55E00")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_captured(folder):
    """The captured numbers, after checking that every snippet and example file still
    matches the copy that ran, so a stale capture stops the render."""
    numbers = json.loads((Path(folder) / "captured" / "numbers.json").read_text())
    for name, digest in numbers["sources"].items():
        assert sha256(ROOT / name) == digest, f"{name} changed since capture; rerun capture.py"
    for heading, digest in numbers.get("readme_blocks", {}).items():
        assert text_sha256(readme_block(heading)) == digest, f"README block {heading!r} changed; rerun capture.py"
    for name, image in numbers["images"].items():
        assert (Path(folder) / "captured" / image["file"]).exists(), f"Missing screenshot {name}"
    return numbers


def readme_block(heading, index=0):
    """A README Python block, by the nearest heading above it (as capture_tools reads it)."""
    blocks = {}
    current = None
    lines = README.read_text().splitlines()
    position = 0
    while position < len(lines):
        line = lines[position]
        if line.startswith("#"):
            current = line.lstrip("#").strip()
        if line.strip() == "```python":
            end = lines.index("```", position + 1)
            blocks.setdefault(current, []).append("\n".join(lines[position + 1 : end]) + "\n")
            position = end
        position += 1
    return blocks[heading][index]


def readme_text():
    return README.read_text()


def readme_states(phrase):
    """Assert that the README states a phrase (whitespace-normalized) and return it."""
    flat = re.sub(r"\s+", " ", README.read_text())
    assert phrase in flat, f"README does not state {phrase!r}"
    return phrase


def file_lines(path):
    return Path(path).read_text().rstrip("\n").split("\n")


def function_lines(path, name):
    """The source lines of one top-level function in a file."""
    text = Path(path).read_text()
    for node in ast.parse(text).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return text.split("\n")[node.lineno - 1 : node.end_lineno]
    raise KeyError(f"No function {name} in {path}")


def excerpt(lines, first, count=None, last=None):
    """A contiguous run of lines starting at the one line equal to first, either count
    lines long or ending at the first later line equal to last."""
    matches = [index for index, line in enumerate(lines) if line == first]
    assert len(matches) == 1, f"{first!r} occurs {len(matches)} times"
    start = matches[0]
    if last is not None:
        end = next(index for index in range(start, len(lines)) if lines[index] == last) + 1
    else:
        end = start + count
    chosen = lines[start:end]
    assert len(chosen) == (end - start) and chosen, "Excerpt runs past the end"
    return dedent(chosen)


def dedent(lines):
    indent = min(len(line) - len(line.lstrip()) for line in lines if line.strip())
    return [line[indent:] for line in lines]


def module_constant(path, name):
    """A literal module-level constant from a source file (e.g., DAYS = 20)."""
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(f"No constant {name} in {path}")


def call_keywords(lines, method):
    """The literal keyword arguments of the first call to method (a function or a .method)
    in some code lines. Arguments that are not literals (lambdas) are skipped."""
    tree = ast.parse("\n".join(dedent(lines)))
    for node in ast.walk(tree):
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None) if isinstance(node, ast.Call) else None
        if name == method:
            found = {}
            for keyword in node.keywords:
                try:
                    found[keyword.arg] = ast.literal_eval(keyword.value)
                except ValueError:
                    pass
            return found
    raise KeyError(f"No call to .{method}( in the given lines")


def t_interval(values, confidence=0.95):
    """Mean and Student t limits across run values, recomputed here so each interval on
    screen is checked against the library's."""
    assert confidence == 0.95
    count = len(values)
    mean = statistics.fmean(values)
    half = T95[count - 1] * statistics.stdev(values) / math.sqrt(count)
    return mean, mean - half, mean + half


def close(a, b, tolerance=1e-9):
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def code_panel(lines, width=None, size=CODE_SIZE, source=None):
    """Syntax-highlighted code in the house box style, with an optional muted source line
    (the file it came from) above it. At most MAX_CODE_LINES lines."""
    assert len(lines) <= MAX_CODE_LINES, f"Code panel has {len(lines)} lines"
    code = Code(
        code_string="\n".join(lines) + "\n",
        language="python",
        formatter_style="friendly",
        add_line_numbers=False,
        background="rectangle",
        background_config={
            "fill_color": CODE_FILL,
            "fill_opacity": 1,
            "stroke_color": BORDER,
            "stroke_width": BOX_STROKE,
            "buff": 0.3,
            "corner_radius": BOX_RADIUS,
        },
        paragraph_config={"font": CODE_FONT, "font_size": size},
    )
    if width is not None and code.width > width:
        code.scale_to_fit_width(width)
    code.source_lines = list(lines)
    if source is None:
        return code
    note = label(source, size=18, color=MUTED).next_to(code, UP, buff=0.12, aligned_edge=LEFT)
    group = Group(note, code)
    group.code = code
    return group


def line_box(code, first, last=None, color=HIGHLIGHT):
    """A highlight band behind lines first..last (zero-based) of a Code object. Blank lines
    have no glyphs, so positions come from the pitch between the first and last nonblank
    lines."""
    last = first if last is None else last
    rows = code.code_lines
    filled = [index for index, row in enumerate(rows) if len(row)]
    top_index, bottom_index = filled[0], filled[-1]
    pitch = (rows[top_index].get_y() - rows[bottom_index].get_y()) / max(1, bottom_index - top_index)
    y_first = rows[top_index].get_y() - pitch * (first - top_index)
    y_last = rows[top_index].get_y() - pitch * (last - top_index)
    background = code.background
    band = Rectangle(
        width=background.width - 0.12,
        height=abs(y_first - y_last) + pitch * 0.98,
        stroke_width=0,
        fill_color=color,
        fill_opacity=1,
    ).move_to([background.get_x(), (y_first + y_last) / 2, 0])
    band.set_z_index(-1)
    return band


def screenshot(folder, numbers, name, width=None, height=None):
    """A captured screenshot in a thin gray frame, fitted within width and height (frame
    units). The PNG is resampled with Lanczos to its pixel size at 1080p before manim
    draws it, since manim's own image transform aliases small text when it shrinks a
    2x screenshot."""
    path = Path(folder) / "captured" / numbers["images"][name]["file"]
    picture = Image.open(path).convert("RGBA")
    # Frame units per pixel at 1080p, where the frame is 8 units tall.
    unit = 8 / 1080
    # A 2x screenshot shown pixel for pixel at 1080p shows CSS text at twice its size.
    natural_width, natural_height = picture.width * unit, picture.height * unit
    scale = 1.0
    if width is not None:
        scale = min(scale, width / natural_width)
    if height is not None:
        scale = min(scale, height / natural_height)
    pixels = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
    image = ImageMobject(np.array(picture.resize(pixels, Image.Resampling.LANCZOS)), scale_to_resolution=1080)
    frame = RoundedRectangle(
        corner_radius=0.06,
        width=image.width + 0.08,
        height=image.height + 0.08,
        stroke_color=BORDER,
        stroke_width=1.5,
        fill_opacity=0,
    ).move_to(image)
    group = Group(image, frame)
    group.image = image
    return group


def stack(*mobjects, buff=0.25):
    return Group(*mobjects).arrange(DOWN, buff=buff)


class RowChart:
    """A horizontal chart with one row per scenario: intervals (a mean with 95% limits),
    strips of per-replication dots, and dashed reference lines. It only builds mobjects;
    the scene animates them."""

    def __init__(self, rows, x_max, ticks, title, left=-3.0, right=5.9, top=1.7, bottom=-2.3, x_min=0.0):
        self.rows = list(rows)
        self.x_min, self.x_max = x_min, x_max
        self.ticks = ticks
        self.title = title
        self.left, self.right, self.top, self.bottom = left, right, top, bottom

    def x(self, value):
        return self.left + (self.right - self.left) * (value - self.x_min) / (self.x_max - self.x_min)

    def y(self, index):
        if len(self.rows) == 1:
            return (self.top + self.bottom) / 2
        pitch = (self.top - self.bottom - 0.6) / (len(self.rows) - 1)
        return self.top - 0.3 - pitch * index

    def axes(self, tick_text=str):
        group = VGroup()
        group.add(Line([self.left, self.bottom, 0], [self.right, self.bottom, 0], color=INK, stroke_width=2))
        for value in self.ticks:
            x = self.x(value)
            grid = Line([x, self.bottom, 0], [x, self.top, 0], color=FAINT, stroke_width=1)
            grid.set_z_index(-2)
            group.add(grid)
            group.add(label(number_text(tick_text(value)), size=TICK_SIZE).move_to([x, self.bottom - 0.3, 0]))
        group.add(
            label(self.title, size=AXIS_TITLE_SIZE).move_to([(self.left + self.right) / 2, self.bottom - 0.75, 0]),
        )
        for index, name in enumerate(self.rows):
            group.add(label(name, size=22).move_to([self.left - 0.3, self.y(index), 0], aligned_edge=RIGHT))
        return group

    def interval(self, index, mean, lower, upper, color):
        y = self.y(index)
        line = Line([self.x(lower), y, 0], [self.x(upper), y, 0], color=color, stroke_width=4)
        caps = VGroup(
            *(Line([self.x(v), y - 0.12, 0], [self.x(v), y + 0.12, 0], color=color, stroke_width=4) for v in (lower, upper)),
        )
        dot = Dot([self.x(mean), y, 0], radius=0.1, color=color, stroke_color=INK, stroke_width=1.5)
        return VGroup(line, caps, dot)

    def strip(self, index, values, color, inside=None):
        """One dot per value; dots outside the window inside(value) are drawn hollow."""
        y = self.y(index)
        dots = VGroup()
        for position, value in enumerate(values):
            jitter = ((position * 7) % 5 - 2) * 0.07
            dot = Dot([self.x(value), y + jitter, 0], radius=0.075, color=color)
            if inside is not None and not inside(value):
                dot.set_fill(WHITE, opacity=1).set_stroke(color, width=2)
            dots.add(dot)
        return dots

    def reference(self, value, text, color, text_color=None):
        x = self.x(value)
        line = DashedLine([x, self.bottom, 0], [x, self.top + 0.15, 0], color=color, stroke_width=3, dash_length=0.12)
        note = label(text, size=22, color=text_color or color).move_to([x, self.top + 0.42, 0])
        return VGroup(line, note)

    def value_label(self, index, value_x, text, color=INK):
        """A data label above a row's marker, on a white plate."""
        return with_backing(label(text, size=DATA_LABEL_SIZE, color=color)).move_to([value_x, self.y(index) + 0.36, 0])


def frame_problems(*mobs, margin=0.45):
    """Code panels and screenshots that come within margin of the frame edge, which the
    template's caption check does not cover (a supply-chain panel ran off the bottom,
    2026-10-24)."""
    problems = []
    for mob in mobs:
        if mob.get_bottom()[1] < -4 + margin:
            problems.append(f"bottom at {mob.get_bottom()[1]:.2f}")
        if mob.get_left()[0] < -7.11 + margin or mob.get_right()[0] > 7.11 - margin:
            problems.append(f"sides at {mob.get_left()[0]:.2f} and {mob.get_right()[0]:.2f}")
    return problems


class CodeScene(ExplainerScene):
    """An ExplainerScene with one code panel at a time: show it, swap it, and move its
    highlight band. Every swap removes the old pieces in one fade, after the caption's
    click, so the deck needs no extra break."""

    # A break holds until the caption has been on screen for its length over this many
    # characters per second, so a long or formula caption gets its reading time in the
    # MP4 (Codex review, 2026-10-24). The deck stops at the break anyway.
    cps = 17

    def setup(self):
        super().setup()
        self.panel = None
        self.band = None

    def inside_frame(self, *mobs):
        """Stop a render, or list the frame in render.sh check, when a panel or screenshot
        reaches the frame edge."""
        problems = frame_problems(*mobs)
        if not problems:
            return
        message = f"Content near the frame edge ({'; '.join(problems)}) under caption {getattr(self.caption, 'text', '(two lines)')!r}"
        if config["dry_run"]:
            self.caption_errors.append(message)
        else:
            raise AssertionError(message)

    def fade_out(self, *mobs):
        gone = [mob for mob in mobs if mob is not None]
        if gone:
            self.play(*(FadeOut(mob) for mob in gone), run_time=0.4)

    def show_code(self, lines, source, y=None, x=0.0, width=12.0, size=22, top=None, drop=(), add=()):
        """Replace the code panel (and anything in drop) in one fade, then bring in the new
        panel with anything in add."""
        panel = code_panel(lines, width=width, size=size, source=source)
        if top is not None:
            panel.move_to([x, top, 0], aligned_edge=UP)
        else:
            panel.move_to([x, CONTENT_Y if y is None else y, 0])
        # Items added with a panel may sit in the footnote slot, which hugs the bottom edge.
        self.inside_frame(panel)
        panel.code.code_lines.set_z_index(2)
        self.fade_out(self.band, self.panel, *drop)
        self.band = None
        self.play(FadeIn(panel), *(FadeIn(mob) for mob in add), run_time=0.6)
        self.panel = panel
        return panel

    def code_and_table(self, lines, source, folder, numbers, name, size=20, max_width=11.5, x=0.0, drop=(), side=False):
        """A code panel at the top and the screenshot of its result directly under it,
        sized to the room left above the footnote slot, swapped in on one click. With side,
        the panel sits at the left and the screenshot beside it, for a tall panel."""
        panel = code_panel(lines, width=12.0, size=size, source=source)
        if side:
            panel.move_to([-6.6, CONTENT_Y + 0.2, 0], aligned_edge=LEFT)
            room = 6.5 - (panel.get_right()[0] + 0.35)
            table = screenshot(folder, numbers, name, width=min(max_width, room), height=4.8)
            table.next_to(panel, RIGHT, buff=0.35)
        else:
            panel.move_to([x, 2.3, 0], aligned_edge=UP)
            room = panel.get_bottom()[1] - 0.3 - (-3.4)
            table = screenshot(folder, numbers, name, width=max_width, height=room)
            table.next_to(panel, DOWN, buff=0.3)
            table.set_x(0)
        self.inside_frame(panel, table)
        panel.code.code_lines.set_z_index(2)
        self.fade_out(self.band, self.panel, *drop)
        self.band = None
        self.play(FadeIn(panel), FadeIn(table), run_time=0.6)
        self.panel = panel
        return table

    def highlight(self, first, last=None, drop=()):
        band = line_box(self.panel.code, first, last)
        band.set_z_index(1)
        self.fade_out(self.band, *drop)
        self.play(FadeIn(band), run_time=0.4)
        self.band = band

    def drop_code(self, *others):
        self.fade_out(self.band, self.panel, *others)
        self.band = None
        self.panel = None
