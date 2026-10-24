"""Run a video's code in the project environment and capture what it produces.

Each video's capture.py runs here, in FlowSim's own pixi environment, since the manim
environment does not have FlowSim installed:

    pixi run python manim/<slug>/capture.py

It executes the snippet files and README blocks a video shows, writes the numbers the
video displays to <slug>/captured/numbers.json, and screenshots tables and saved viewers
with Playwright and Chrome into <slug>/captured/. The video module then reads that JSON
and asserts every number against the examples' constants or the README's hand values.

Nothing here imports manim, and nothing in the manim environment imports this file.
"""

import contextlib
import hashlib
import html
import io
import json
import os
import runpy
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
CHROME = shutil.which("google-chrome") or "/usr/bin/google-chrome"
# Screenshots are taken at twice the CSS pixel size, so a table shown 9 frame units wide
# (about 1,200 pixels at 1080p) stays sharp.
SCALE = 2

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def digest(path):
    """The SHA-256 of a file, so the video can assert it shows the code that ran."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def relative(path):
    return str(Path(path).resolve().relative_to(ROOT))


def readme_blocks():
    """Every Python block in the README, keyed by the nearest heading above it."""
    blocks = {}
    heading = None
    lines = README.read_text().splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        if line.strip() == "```python":
            end = lines.index("```", index + 1)
            blocks.setdefault(heading, []).append("\n".join(lines[index + 1 : end]) + "\n")
            index = end
        index += 1
    return blocks


@contextlib.contextmanager
def quiet_figures():
    """Blocks call Figure.show(), which would open a browser."""
    import plotly.graph_objects as go

    show = go.Figure.show
    go.Figure.show = lambda self, *args, **kwargs: None
    try:
        yield
    finally:
        go.Figure.show = show


def run_readme_block(heading, index=0):
    """Execute one README block in a scratch directory, as tests/test_readme.py does, and
    return its namespace and printed output."""
    source = readme_blocks()[heading][index]
    namespace = {}
    printed = io.StringIO()
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as scratch, quiet_figures():
        os.chdir(scratch)
        try:
            with contextlib.redirect_stdout(printed):
                exec(compile(source, f"README block under {heading!r}", "exec"), namespace)
        finally:
            os.chdir(previous)
    return namespace, printed.getvalue(), source


def run_snippet(path):
    """Execute a snippet file from the project root, so relative output paths land under
    the project's output/ folder as they would for a student."""
    previous = Path.cwd()
    printed = io.StringIO()
    os.chdir(ROOT)
    try:
        with quiet_figures(), contextlib.redirect_stdout(printed):
            namespace = runpy.run_path(str(path), run_name="__main__")
    finally:
        os.chdir(previous)
    return namespace, printed.getvalue()


def _number(value):
    return None if value is None else float(value)


def column(frame, name):
    return [_number(value) if not isinstance(value, str) else value for value in frame.get_column(name).to_list()]


TABLE_CSS = """
body { margin: 0; background: #ffffff; font-family: "Nimbus Sans", Arial, sans-serif; }
#shot { display: inline-block; padding: 14px 16px; }
#shot .title { font: 600 15px "Nimbus Mono PS", monospace; color: #444; margin: 0 0 6px 2px; }
table.dataframe { border-collapse: collapse; font-size: 17px; }
table.dataframe th, table.dataframe td { border: 1px solid #c9c9c9; padding: 5px 11px; text-align: right; white-space: nowrap; }
table.dataframe thead th { background: #f1f3f5; font-family: "Nimbus Mono PS", monospace; }
table.dataframe tbody tr:nth-child(even) { background: #fafafa; }
small { color: #555; font-size: 14px; }
"""


def frame_html(frame, title=None):
    """The HTML a notebook shows for a Polars DataFrame (its own _repr_html_), with a
    larger table font so it reads on a slide."""
    heading = f'<p class="title">{html.escape(title)}</p>' if title else ""
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{TABLE_CSS}</style></head>"
        f"<body><div id='shot'>{heading}{frame._repr_html_()}</div></body></html>"
    )


def _browser(driver):
    return driver.chromium.launch(executable_path=CHROME, headless=True, args=["--no-sandbox"])


def shoot(page_path, png, selector=None, viewport=(1100, 800), wait_ready=False, before=None, full_page=False):
    """Screenshot a saved HTML page offline. Every network request is blocked, so the
    picture shows what a student sees without internet. selector picks one element (the
    first match); before(page) may click controls first."""
    from playwright.sync_api import sync_playwright

    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as driver:
        browser = _browser(driver)
        page = browser.new_page(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=SCALE,
        )
        page.route("http*://**/*", lambda route: route.abort())
        page.goto(Path(page_path).resolve().as_uri())
        if wait_ready:
            page.wait_for_function("window.flowsimReady !== undefined")
            page.evaluate("window.flowsimReady")
        if before is not None:
            before(page)
        page.wait_for_timeout(400)
        if selector:
            page.locator(selector).first.screenshot(path=str(png))
        else:
            page.screenshot(path=str(png), full_page=full_page)
        browser.close()
    return png


def frame_png(frame, png, title=None):
    """Screenshot a DataFrame as a notebook would display it."""
    png = Path(png)
    page = png.with_suffix(".html")
    page.write_text(frame_html(frame, title))
    shoot(page, png, selector="#shot")
    page.unlink()
    return png


def write_numbers(folder, numbers):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "numbers.json"
    path.write_text(json.dumps(numbers, indent=2) + "\n")
    print(f"Wrote {relative(path)}")
    return path


def png_size(path):
    """Pixel width and height from a PNG header, so the JSON records each screenshot's
    shape without a Pillow dependency in the project environment."""
    data = Path(path).read_bytes()[16:24]
    return int.from_bytes(data[:4], "big"), int.from_bytes(data[4:], "big")


def code_lines(text):
    """Lines of a snippet without trailing blank lines."""
    return text.rstrip("\n").split("\n")


def contains_lines(block, lines):
    """True when lines appear as one contiguous run in block."""
    rows = code_lines(block)
    width = len(lines)
    return any(rows[start : start + width] == lines for start in range(len(rows) - width + 1))


def find_heading_block(heading):
    blocks = readme_blocks()
    if heading not in blocks:
        raise KeyError(f"No Python block under README heading {heading!r}")
    return blocks[heading]
