# Copied from ~/.claude/skills/manim-video/template on 2026-10-24.
"""Display conventions shared by every video in this folder.

A video module imports from here and adds its own visual pieces (a Gantt chart, a plot, an
equation panel). Nothing here knows about any topic.

    from explainer import INK, MUTED, ExplainerScene, label, markup

render.sh puts this folder on PYTHONPATH.
"""

import contextlib
import functools
import itertools
import json
import os
from pathlib import Path

import manimpango
from manim import (
    DOWN,
    LEFT,
    RIGHT,
    UP,
    WHITE,
    Arrow,
    FadeIn,
    FadeOut,
    Line,
    ManimColor,
    MarkupText,
    Rectangle,
    RoundedRectangle,
    Scene,
    Text,
    VGroup,
    config,
)
from manim.animation.animation import Wait, prepare_animation
from manim_slides import Slide
from manim_slides.slide.base import BaseSlide

config.background_color = WHITE

FONT = "Nimbus Roman"
# Pango silently substitutes a default face for a missing family. Nimbus Roman ships in the
# urw-base35 fonts (Debian and Ubuntu package fonts-urw-base35). It has no ceiling brackets
# or check marks, so check a math glyph with fc-list ":charset=<hex>" before using it.
if FONT not in manimpango.list_fonts():
    raise RuntimeError(f"Font not installed: {FONT} (install fonts-urw-base35)")
INK = ManimColor("#222222")
MUTED = ManimColor("#6B6B6B")
FAINT = ManimColor("#B0B0B0")
ACCEPT = ManimColor("#027A5A")
ALERT = ManimColor("#D55E00")

CAPTION_Y = 3.4
# Captions hang from a fixed top edge, so a second line grows downward and the first line
# never jumps when a caption changes between one and two lines; the top sits 0.38 units
# (about 34 px at 720p) below the frame edge (polish review, 2026-10-15).
CAPTION_TOP = 3.62
CAPTION_SIZE = 30
# 11.8 units is about 83% of the frame; a one-line caption that runs edge to edge looks
# crowded (three-reviewer polish pass, ob-generic-entry pitch, 2026-10-15; was 12.8).
CAPTION_MAX_WIDTH = 11.8
# A caption that would need shrinking below this factor is a copy defect, not a layout one.
CAPTION_MIN_SCALE = 0.9
PANEL_SIZE = 26
FOOTNOTE_Y = -3.6
# A step's final composition centers here, between a two-line caption and the footnote slot,
# and earlier elements start in their final slots so nothing jumps (polish review, 2026-10-15).
CONTENT_Y = -0.45
# A no-break space keeps a numeric range ("30% to 37%") or a short phrase on one caption line.
NBSP = " "

# The house style for drawn pieces (owner's ruling and three-reviewer polish pass on the
# ob-generic-entry pitch, 2026-10-15). Before 2026-10-19 every video redefined these.
# Neutral borders are mid-gray; a colored border means a category.
BORDER = ManimColor("#9A9A9A")
# A thin black outline on every filled bar, so it reads against white and shaded bands.
BAR_STROKE = 1.2
BOX_STROKE = 2
BOX_RADIUS = 0.12
BOX_PAD_X, BOX_PAD_Y = 0.35, 0.3
# A box rebuilt at its own natural width can measure a hair narrower once the padding is
# subtracted again, so the fit checks allow this much rounding (trie-flow, 2026-10-21).
FIT_TOLERANCE = 1e-6
ARROW_TIP = 0.2
# Text sizes by role. Nothing that must be read is smaller than 18.
TITLE_SIZE, BODY_SIZE, SOURCE_SIZE = 26, 22, 18
TICK_SIZE, AXIS_TITLE_SIZE, DATA_LABEL_SIZE = 20, 22, 22

# Seconds a caption stays up before a break, so the continuous MP4 is readable on its own.
# The deck stops at the break anyway.
READ = 2.2

# Every animation, wait, and checkpoint offset runs PACE times as long as the scene code
# says, so a presenter can talk over the motion (1.25 since Oct 12, 2026). A video sets its
# own pace and hold as the scene class attributes `pace` and `read` (2026-10-15).
PACE = 1.25

# manim-slides stores clip paths as given and resolves them against this folder's parent,
# so render.sh passes an absolute path.
SLIDES_DIR = Path(os.environ.get("SLIDES_DIR", "slides"))

# Pango spaces glyphs unevenly at small sizes, so text is built at SUPERSAMPLE times its
# size and scaled down.
SUPERSAMPLE = 4


@functools.cache
def _line_height(size):
    return Text("Mg", font=FONT, font_size=size).height


def _one_line(kind, text, size, color):
    """Build at SUPERSAMPLE times the size, then fall back to smaller factors if Pango
    wrapped the long string onto a second line."""
    reference = _line_height(size)
    for factor in (SUPERSAMPLE, 2, 1):
        mob = kind(text, font=FONT, font_size=size * factor, color=color).scale(1 / factor)
        if mob.height < 1.6 * reference:
            return mob
    raise ValueError(f"Text wraps even at its natural size: {text!r}")


def label(text, size=24, color=INK):
    return _one_line(Text, text, size, color)


def markup(text, size=24, color=INK):
    """Text with Pango markup, for subscripts such as C<sub>max</sub>."""
    return _one_line(MarkupText, text, size, color)


def make_caption(
    text,
    min_scale=CAPTION_MIN_SCALE,
    max_width=CAPTION_MAX_WIDTH,
    size=CAPTION_SIZE,
    split_words=False,
    max_lines=2,
):
    """One line when it fits, otherwise two lines split at the sentence boundary that
    best balances their widths. With split_words, a caption whose sentences do not fit
    that way splits between words instead, into the fewest lines up to max_lines whose
    longest line fits, for a video whose captions are too large to hold a sentence per
    line (the ob-generic-entry pitch's 1.5x captions, 2026-10-16). Refuses copy that would
    need shrinking below min_scale."""
    line = label(text, size=size)
    if line.width <= max_width:
        return line.move_to([0, CAPTION_TOP, 0], aligned_edge=UP)

    def balanced(parts, count):
        """The split of parts into count lines whose longest line has the fewest characters."""
        splits = (
            [" ".join(parts[a:b]) for a, b in zip((0, *cuts), (*cuts, len(parts)))]
            for cuts in itertools.combinations(range(1, len(parts)), count - 1)
        )
        return min(splits, key=lambda rows: max(len(row) for row in rows))

    def stacked(rows):
        return VGroup(*(label(row, size=size) for row in rows)).arrange(
            DOWN,
            buff=0.12 * size / CAPTION_SIZE,
        )

    sentences = [part.strip() for part in text.replace(". ", ".\n").replace("? ", "?\n").split("\n")]
    lines = stacked(balanced(sentences, 2)) if len(sentences) >= 2 else None
    if split_words and (lines is None or lines.width > max_width):
        # Split on plain spaces only, so a no-break space (U+00A0) keeps a range like
        # "30% to 37%" on one line.
        words = text.split(" ")
        for count in range(2, min(max_lines, len(words)) + 1):
            lines = stacked(balanced(words, count))
            if lines.width <= max_width:
                break
    if lines is None:
        raise ValueError(
            f"Caption is one sentence too wide for one line ({line.width:.1f} > {max_width}): {text!r}",
        )
    if lines.width > max_width:
        if max_width / lines.width < min_scale:
            raise ValueError(
                f"Caption needs a shorter sentence ({lines.width:.1f} > "
                f"{max_width / min_scale:.1f}): {text!r}",
            )
        lines.scale_to_fit_width(max_width)
    return lines.move_to([0, CAPTION_TOP, 0], aligned_edge=UP)


def text_block(lines, size=24, color=INK, buff=0.16):
    """Lines of text stacked and centered on one another. A block placed at the middle of
    the frame reads as ragged when its lines are left-aligned, so center by default; keep
    left alignment for bulleted lists and table columns (user ruling, 2026-10-15).

    Lines sit at an even pitch. Arranging lines by their own bounding boxes spaced "Industry
    / share" unlike "Child labor / rate" (child-labor-rise, 2026-10-19), so each line is built
    with a trailing "|", which spans ascender to descender, stacked, and then stripped of it."""
    rows = [label(f"{line} |", size=size, color=color) for line in lines]
    block = VGroup(*rows).arrange(DOWN, buff=buff)
    # Read the center once: re-reading it per row centers early rows on a group that later
    # rows' struts still widen (h2a upgrade, 2026-10-19).
    center = block.get_x()
    for row in rows:
        row.remove(row.submobjects[-1])
        row.set_x(center)
    return block


def with_backing(mob, buff=0.05):
    """Put a white plate behind text that sits over gridlines, shading, or a reference
    line, so the line does not strike the glyphs through (polish review, 2026-10-15)."""
    plate = Rectangle(
        width=mob.width + 2 * buff,
        height=mob.height + 2 * buff,
        stroke_width=0,
        fill_color=WHITE,
        fill_opacity=1,
    ).move_to(mob)
    return VGroup(plate, mob)


def footnote(text):
    """A source or disclosure note in the one footnote slot, centered at the frame's
    bottom (polish review, 2026-10-15)."""
    return label(text, size=18, color=MUTED).move_to([0, FOOTNOTE_Y, 0])


def number_text(value):
    """A tick or data label with a true minus sign (U+2212, which Nimbus Roman has)."""
    return str(value).replace("-", "−")


def make_bar(width, height, color):
    """A filled bar with the house outline."""
    return Rectangle(
        width=width,
        height=height,
        stroke_color=INK,
        stroke_width=BAR_STROKE,
        fill_color=color,
        fill_opacity=1,
    )


def make_arrow(start, end, color=INK):
    """A connector with the house arrowhead. Run it from the parent's bottom center to the
    child's top center, and put any annotation beside it, not in its path."""
    return Arrow(
        start,
        end,
        buff=0.08,
        color=color,
        stroke_width=3,
        tip_length=ARROW_TIP,
        max_tip_length_to_length_ratio=0.5,
    )


def make_box(title, body=(), source=None, color=BORDER, title_color=INK, width=None, height=None):
    """A rounded box with up to three text roles, each centered: a title (a string, or a
    tuple of lines for a long one), body lines, and a muted source line. Boxes in one row or
    column pass a shared width and height, and a fixed size must still hold the text inside
    its padding (the ob-generic-entry pitch's funnel box overflowed after one word was added)."""
    titles = (title,) if isinstance(title, str) else title
    # Every line, title through source, carries the "|" strut while the stack is arranged, so
    # the title-to-body gap matches the gaps between body lines (h2a upgrade, 2026-10-19).
    roles = [(line, TITLE_SIZE, title_color) for line in titles]
    roles += [(line, BODY_SIZE, INK) for line in body]
    if source:
        roles.append((source, SOURCE_SIZE, MUTED))
    rows = [label(f"{line} |", size=size, color=color) for line, size, color in roles]
    text = VGroup(*rows).arrange(DOWN, buff=0.08)
    # Place by the strutted stack, not the bare glyphs, or a one-line title with no
    # descenders sits low in its box (tijuana upgrade, 2026-10-19).
    strut_center = text.get_center()
    for row in rows:
        row.remove(row.submobjects[-1])
        row.set_x(strut_center[0])
    name = (titles or body or ("",))[0]
    if width is not None and text.width > width - 2 * BOX_PAD_X + FIT_TOLERANCE:
        raise ValueError(f"Box is {width} wide, too narrow for {name!r} ({text.width + 2 * BOX_PAD_X:.2f})")
    if height is not None and text.height > height + FIT_TOLERANCE:
        raise ValueError(f"Box is {height} tall, too short for {name!r} ({text.height:.2f})")
    frame = RoundedRectangle(
        corner_radius=BOX_RADIUS,
        width=width or text.width + 2 * BOX_PAD_X,
        height=height or text.height + 2 * BOX_PAD_Y,
        stroke_color=color,
        stroke_width=BOX_STROKE,
        fill_color=WHITE,
        fill_opacity=1,
    )
    text.shift(frame.get_center() - strut_center)
    return VGroup(frame, text)


def make_card(headline, lines, source, color, width, height=None):
    """A statistic card: a large headline number, body lines, and a muted source line."""
    content = VGroup(
        label(headline, size=64, color=color),
        text_block(lines, size=BODY_SIZE, buff=0.1),
        label(source, size=SOURCE_SIZE, color=MUTED),
    ).arrange(DOWN, buff=0.24)
    # The same fit check as make_box (filtering-effects upgrade, 2026-10-19).
    if content.width > width - 2 * BOX_PAD_X + FIT_TOLERANCE:
        raise ValueError(f"Card is {width} wide, too narrow for {headline!r} ({content.width + 2 * BOX_PAD_X:.2f})")
    if height is not None and content.height > height + FIT_TOLERANCE:
        raise ValueError(f"Card is {height} tall, too short for {headline!r} ({content.height:.2f})")
    frame = RoundedRectangle(
        corner_radius=BOX_RADIUS,
        width=width,
        height=height or content.height + 2 * BOX_PAD_Y + 0.1,
        stroke_color=BORDER,
        stroke_width=BOX_STROKE,
    )
    content.move_to(frame)
    return VGroup(frame, content)


def same_size_boxes(specs):
    """Boxes for one row or grid at one shared width and height. Each spec is the
    (args, kwargs) of a make_box call; every box is built once to measure, then again at
    the largest width and height, since box_row matches heights only (trie-flow,
    2026-10-21)."""
    natural = [make_box(*args, **kwargs) for args, kwargs in specs]
    width = max(box[0].width for box in natural)
    height = max(box[0].height for box in natural)
    return [make_box(*args, **kwargs, width=width, height=height) for args, kwargs in specs]


def box_row(*boxes, gap=0.5, y=CONTENT_Y):
    """Boxes or cards (each a VGroup of frame and text) side by side at one shared height,
    centered on y, since parallel items get parallel containers."""
    height = max(box[0].height for box in boxes)
    for box in boxes:
        box[0].stretch_to_fit_height(height)
    return VGroup(*boxes).arrange(RIGHT, buff=gap).move_to([0, y, 0])


def title_block(title, subtitle=None, people=(), note=None):
    """The text of an opening or closing title card for a video sent to someone cold: the
    title, an optional subtitle, (name, affiliation) pairs, and a muted note such as the work
    it builds on."""
    rows = [label(title, size=52)]
    if subtitle:
        rows.append(label(subtitle, size=34, color=MUTED))
    heading = VGroup(*rows).arrange(DOWN, buff=0.22)
    parts = [heading]
    if people:
        parts.append(Line([-3.2, 0, 0], [3.2, 0, 0], color=BORDER, stroke_width=1.5))
        parts.append(
            VGroup(
                *(
                    VGroup(label(name, size=26), label(place, size=18, color=MUTED)).arrange(DOWN, buff=0.08)
                    for name, place in people
                )
            ).arrange(DOWN, buff=0.28),
        )
    if note:
        parts.append(label(note, size=20, color=MUTED))
    return VGroup(*parts).arrange(DOWN, buff=0.4).move_to([0, 0, 0])


def formula_panel(lines, x, top_y, size=PANEL_SIZE):
    """Left-aligned lines of markup, top edge at top_y."""
    group = VGroup(*(markup(line, size=size) for line in lines)).arrange(
        DOWN,
        aligned_edge=LEFT,
        buff=0.22,
    )
    return group.move_to([x, top_y, 0], aligned_edge=UP + LEFT)


def _whole_frames(seconds):
    """Round a run time to whole frames. A run time between frames renders a frame longer
    than self.time records, and over a part the checkpoints drift behind the video."""
    return max(1, round(seconds * config.frame_rate)) / config.frame_rate


def _fades_out(animation):
    """True for a FadeOut, alone or inside a group such as LaggedStart."""
    if isinstance(animation, FadeOut):
        return True
    return any(_fades_out(part) for part in getattr(animation, "animations", []))


class ExplainerScene(Slide):
    """Caption, checkpoint, and break helpers for one part of a video.

    Every caption change and break records a checkpoint time, and tear_down writes them to
    $CHECKPOINT_DIR/<Scene>.json so review_frames.py can pull settled and mid-transition
    stills. pause() places a checkpoint and a slide break in one call, so the two lists
    cannot drift apart.

    Nothing leaves the screen without a click. say() and clear_stage() add a break first
    when anything has played since the last one, and a dry run (render.sh check) lists
    every other FadeOut that would play without a click, so the scene can add one.
    rolling() exempts animations that finish a placement.

    manim-slides 5.7.0 predates manim 0.22, which removed config["write_to_movie"] and
    config["flush_cache"] and made max_files_cached integer-only. __init__ and render
    below replace the two Slide methods that touch those settings. Remove them once
    manim-slides supports manim 0.22.
    """

    # The HTML deck plays each slide forward only, so the reversed clips the Qt player
    # uses are not worth their render time.
    skip_reversing = True
    # Run-time multiplier and hold before a break; a faster cut (a pitch) lowers both.
    pace = PACE
    read = READ
    # Reading speed in caption characters per second. When set, a break holds until the
    # current caption has been on screen for len(caption) / cps seconds of video, never less
    # than `read`, so a long caption is not cut off when `pace` is low. None keeps the
    # fixed hold (2026-10-15).
    cps = None
    # Widest one-line caption, in frame units. The ob-generic-entry pitch used 12.4 with
    # 45-point captions (2026-10-16).
    caption_max_width = CAPTION_MAX_WIDTH
    # Caption type size, and whether a caption may split between words rather than only
    # between sentences. Larger captions (a pitch shown on a projector) need both; the
    # ob-generic-entry pitch set 45, True, and 3 (2026-10-16).
    caption_size = CAPTION_SIZE
    caption_split_words = False
    # More than two lines only where a video allows it; check lists every such caption.
    caption_max_lines = 2
    # Least gap, in frame units, between the caption's bottom and the highest other object
    # at every break. check lists each violation and a render stops on one. None turns the
    # check off, e.g., for a video with a full-frame background object.
    caption_gap = 0.4
    # Whether a part's title card shows "Part N" above the title. A pitch or a walkthrough
    # with plain section headers turns it off (2026-10-19).
    part_label = True
    # A section card's heading size and the size of the sentence under it.
    section_size = 60
    section_body_size = 34

    def __init__(self, *args, **kwargs):
        # manim 0.22 copies max_files_cached into the file writer's settings in
        # Scene.__init__, so the override in render() comes too late, and a part with more
        # than 100 animations loses its oldest partial files before manim-slides reads them
        # (st-geo-robust-siting, 2026-10-14). -1 leaves the cache unlimited.
        config["max_files_cached"] = -1
        # BaseSlide.__init__ continues to Scene.__init__ through the MRO, skipping the
        # write_to_movie line in Slide.__init__.
        BaseSlide.__init__(self, *args, output_folder=SLIDES_DIR, **kwargs)

    def render(self, *args, **kwargs):
        max_files_cached = config["max_files_cached"]
        config["max_files_cached"] = -1  # manim-slides reads every partial movie file
        try:
            Scene.render(self, *args, **kwargs)
        finally:
            config["max_files_cached"] = max_files_cached
        if config["dry_run"]:
            return  # render.sh check: nothing was written, so there are no slides to save
        self._save_slides(
            use_cache=not (config["disable_caching"] or self.disable_caching),
            flush_cache=self.flush_cache,
            skip_reversing=self.skip_reversing,
        )

    def setup(self):
        self.caption = None
        self.caption_chars = 0
        self.caption_shown_at = 0.0
        self.checkpoints = []
        self.caption_errors = []
        self.caption_warnings = []
        # What has played since the last break: a caption, and anything else.
        self.caption_since_break = False
        self.content_since_break = False
        self.helper_playing = False
        self.click_warnings = []

    def play(self, *animations, **kwargs):
        """Scale every run time by PACE, and in a dry run note any FadeOut that would play
        after other content without a break in between. Scene.wait() plays a Wait, so
        waits are scaled here too, and a wait alone shows nothing new."""
        prepared = [prepare_animation(animation) for animation in animations]
        if "run_time" in kwargs:
            kwargs["run_time"] = _whole_frames(kwargs["run_time"] * self.pace)
        else:
            for animation in prepared:
                animation.run_time = _whole_frames(animation.run_time * self.pace)
        if config["dry_run"] and not self.helper_playing and self.content_since_break:
            if any(_fades_out(animation) for animation in prepared):
                shown = getattr(self.caption, "text", None) or "(two-line caption)"
                self.click_warnings.append(f"FadeOut without a click, under caption {shown!r}")
        super().play(*prepared, **kwargs)
        if not self.helper_playing and not all(isinstance(a, Wait) for a in prepared):
            self.content_since_break = True

    @contextlib.contextmanager
    def rolling(self):
        """Animations that finish a placement (a block moving into its slot, a highlight
        clearing after it) roll through without a click, since they add to the picture
        rather than take words away. Use it only for that."""
        self.helper_playing = True
        try:
            yield
        finally:
            self.helper_playing = False
            self.content_since_break = True

    def mark(self, name, offset=0.0):
        self.checkpoints.append({"name": name, "time": round(float(self.time) + offset * self.pace, 3)})

    def pause(self, name, hold=None):
        """Hold for viewers of the continuous MP4, then end the slide here, after checking
        that the settled frame keeps its content caption_gap below the caption."""
        if self.caption_gap is not None and self.caption is not None and self.caption in self.mobjects:
            floor = self.caption.get_bottom()[1] - self.caption_gap
            top = max((mob.get_top()[1] for mob in self.mobjects if mob is not self.caption), default=floor)
            if top > floor:
                message = f"Content reaches y = {top:.2f}, above {floor:.2f} under the caption, at {name}"
                if not config["dry_run"]:
                    raise AssertionError(message)
                self.caption_errors.append(message)
        if hold is None:
            hold = self.read
        # An explicit hold (a part's end) is a minimum as well, so the last caption still
        # gets its reading time (Codex review of the ob-generic-entry pitch, 2026-10-16).
        if self.cps and self.caption is not None:
            on_screen = float(self.time) - self.caption_shown_at
            hold = max(hold, (self.caption_chars / self.cps - on_screen) / self.pace)
        if hold:
            self.wait(hold)
        self.mark(f"break-{name}", offset=-0.1)
        self.next_slide()
        self.caption_since_break = False
        self.content_since_break = False

    def tear_down(self):
        destination = Path(os.environ.get("CHECKPOINT_DIR", "build/checkpoints"))
        destination.mkdir(parents=True, exist_ok=True)
        path = destination / f"{type(self).__name__}.json"
        path.write_text(json.dumps(self.checkpoints, indent=2))
        for suffix, lines in (
            ("caption-errors", self.caption_errors),
            ("caption-warnings", self.caption_warnings),
            ("click-warnings", self.click_warnings),
        ):
            if lines:
                notes = destination / f"{type(self).__name__}.{suffix}"
                notes.write_text("".join(f"{type(self).__name__}: {line}\n" for line in lines))

    def title_card(self, number, title):
        """The part's opening card, which the click that starts the part also clears."""
        rows = [label(f"Part {number}", size=30, color=MUTED)] if self.part_label else []
        card = VGroup(*rows, label(title, size=52)).arrange(DOWN, buff=0.3)
        self.helper_playing = True
        self.play(FadeIn(card, shift=0.2 * UP), run_time=0.8)
        self.mark("title", offset=0.0)
        self.wait(1.2)
        self.play(FadeOut(card), run_time=0.5)
        self.helper_playing = False

    def say(self, text, hold=0.0):
        """Show a caption. Replacing one takes a click first if anything has played since
        the last break, so the presenter decides when the old words leave."""
        try:
            new = make_caption(
                text,
                max_width=self.caption_max_width,
                size=self.caption_size,
                split_words=self.caption_split_words,
                max_lines=self.caption_max_lines,
            )
        except ValueError as error:
            # render.sh check collects every caption defect in one pass instead of
            # stopping at the first; a real render still stops here.
            if not config["dry_run"]:
                raise
            self.caption_errors.append(str(error))
            new = label("(caption too wide)", size=self.caption_size).move_to([0, CAPTION_Y, 0])
        else:
            if config["dry_run"]:
                try:
                    make_caption(
                        text,
                        min_scale=1,
                        max_width=self.caption_max_width,
                        size=self.caption_size,
                        split_words=self.caption_split_words,
                        max_lines=self.caption_max_lines,
                    )
                except ValueError:
                    self.caption_warnings.append(f"Caption shrinks to fit: {text!r}")
                # A one-line caption is a Text, whose members are glyphs, so test the type.
                if type(new) is VGroup and len(new) > 2:
                    self.caption_warnings.append(f"Caption takes {len(new)} lines: {text!r}")
        if self.caption is not None and (self.caption_since_break or self.content_since_break):
            self.pause(f"before-caption-{len(self.checkpoints):02d}")
        self.helper_playing = True
        if self.caption is None:
            self.play(FadeIn(new, shift=0.15 * DOWN), run_time=0.6)
        else:
            self.play(
                FadeOut(self.caption, shift=0.15 * UP),
                FadeIn(new, shift=0.15 * UP),
                run_time=0.6,
            )
        self.helper_playing = False
        self.caption = new
        self.caption_chars = len(text)
        self.caption_shown_at = float(self.time)
        self.caption_since_break = True
        self.mark(f"caption-{len(self.checkpoints):02d}", offset=0.3)
        if hold:
            self.wait(hold)

    def clear_stage(self, run_time=0.6):
        """Fade out everything except the caption, after a click if anything has played
        since the last break. When only a caption has played since the break, that
        caption's click also clears the stage, so a new caption never sits over the old
        picture (OM-522 shifting bottleneck video, Oct 18, 2026)."""
        others = [mob for mob in self.mobjects if mob is not self.caption]
        if not others:
            return
        if self.content_since_break:
            self.pause(f"before-clear-{len(self.checkpoints):02d}")
        self.helper_playing = True
        self.play(*(FadeOut(mob) for mob in others), run_time=run_time)
        self.helper_playing = False

    def close_all(self):
        """Clear the whole frame, caption included, after a click (before a section card
        or a closing title card)."""
        self.pause(f"before-close-{len(self.checkpoints):02d}")
        self.helper_playing = True
        self.play(*(FadeOut(mob) for mob in self.mobjects), run_time=0.6)
        self.helper_playing = False
        self.caption = None

    def section_card(self, heading, lines=(), source=None):
        """A section card on a clear frame (a large heading with an optional sentence under
        it and a source in the footnote slot), held long enough to read, then cleared by the
        next click. The pitch used it to mark where background ends and the new study begins
        (ob-generic-entry, 2026-10-16). Call close_all() first if a caption is up."""
        rows = [label(heading, size=self.section_size)]
        if lines:
            rows.append(text_block(lines, size=self.section_body_size, buff=0.14))
        card = VGroup(*rows).arrange(DOWN, buff=0.45).move_to([0, 0.2, 0])
        shown = [FadeIn(card, shift=0.15 * UP)]
        if source:
            shown.append(FadeIn(footnote(source)))
        self.helper_playing = True
        self.play(*shown, run_time=0.6)
        self.helper_playing = False
        name = f"section-{len(self.checkpoints):02d}"
        self.mark(name, offset=0.2)
        hold = self.read
        if self.cps:
            hold = max(hold, (len(heading) + sum(len(line) for line in lines)) / self.cps / self.pace)
        self.pause(name, hold=hold)
        self.clear_stage()

    def show_title_block(self, block, hold=3.0, closing=False):
        """Play a title_block() card. An opening card fades out on its own, like a part's
        title card; a closing card stays up and ends the part on a break."""
        self.helper_playing = True
        self.play(FadeIn(block, shift=0.2 * UP), run_time=0.8)
        self.mark("closing" if closing else "title")
        if closing:
            self.helper_playing = False
            self.pause("end", hold=hold)
            return
        self.wait(hold)
        self.play(FadeOut(block), run_time=0.5)
        self.helper_playing = False


class PitchScene(ExplainerScene):
    """The pitch profile: a short cut sent to an outside audience who watch the MP4 on their
    own, so it runs faster, holds each caption for its reading time, and uses captions
    1.5 times the default size, which viewers read as each slide's headline. These are the
    settings the ob-generic-entry pitch shipped with (2026-10-16); a video changes any of
    them as class attributes. See references/pitch.md."""

    pace = 0.85
    read = 1.5
    cps = 17
    caption_size = 45
    caption_max_width = 12.4
    caption_split_words = True
    caption_max_lines = 3
    part_label = False
    section_size = 72
    section_body_size = 45
