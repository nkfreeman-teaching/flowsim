"""The model builder page: its schema, its file, and its generated code."""

import inspect
import json
import re
import runpy
import shutil
import subprocess

import pytest
from polars.testing import assert_frame_equal

import flowsim
from flowsim.builder_page import schema
from tests.models import branching_service, deterministic_queue

# Public distribution constructors the builder leaves out: sequence data
# (empirical, discrete), helpers/wrappers (shifted, from_scv), and demand counts.
NOT_IN_BUILDER = {
    "empirical",
    "discrete",
    "shifted",
    "from_scv",
    "poisson",
    "negative_binomial",
}

SCHEMA_SCRIPT = r'<script id="schema" type="application/json">(.*?)</script>'


def test_schema_lists_every_duration_constructor_with_its_parameters():
    constructors = {
        name
        for name, member in vars(flowsim.distributions).items()
        if inspect.isfunction(member)
        and not name.startswith("_")
        and member.__module__ == "flowsim.distributions"
    }
    listed = {entry["name"]: entry for entry in schema()["distributions"]}
    assert set(listed) == constructors - NOT_IN_BUILDER
    assert set(listed) == {
        "exponential",
        "uniform",
        "triangular",
        "pert",
        "normal",
        "lognormal",
        "gamma",
        "weibull",
        "erlang",
        "beta",
    }
    for name, entry in listed.items():
        constructor = getattr(flowsim, name)
        signature = inspect.signature(constructor).parameters
        assert [item["name"] for item in entry["parameters"]] == list(signature)
        # The page fills a new distribution from the docstring example.
        constructor(**entry["example"])
    beta = {item["name"]: item for item in listed["beta"]["parameters"]}
    assert (beta["low"]["default"], beta["high"]["default"]) == (0, 1)
    assert beta["a"]["required"] and not beta["low"]["required"]
    mean = listed["exponential"]["parameters"][0]
    assert (mean["minimum"], mean["exclusive"]) == (0, True)
    k = listed["erlang"]["parameters"][0]
    assert (k["kind"], k["minimum"], k["exclusive"]) == ("integer", 1, False)


def test_a_docstring_example_skips_a_keyword_that_is_not_a_literal(monkeypatch):
    # The page can write only literal values, so a NumPy call in an example is
    # skipped and the literal keyword is kept, instead of raising.
    monkeypatch.setattr(
        target=flowsim.distributions.exponential,
        name="__doc__",
        value="Exponential.\n\nExample\n-------\n>>> exponential(mean=2, scale=np.float64(1))\n",
    )
    (entry,) = [
        item for item in schema()["distributions"] if item["name"] == "exponential"
    ]
    assert entry["example"] == {"mean": 2}
    assert "<!doctype html>" in flowsim.builder().html.lower()


def test_schema_reads_model_arguments_from_their_signatures():
    data = schema()
    for kind, method in [
        ("source", flowsim.Model.source),
        ("station", flowsim.Model.station),
    ]:
        names = [item["name"] for item in data[kind]]
        assert names == [name for name in inspect.signature(method).parameters][1:]
        assert list(data["supported"][kind]) == names
    station = {item["name"]: item for item in data["station"]}
    assert station["shift_end"]["choices"] == ["finish", "pause"]
    assert station["service_time"]["kind"] == "duration"
    assert (station["capacity"]["kind"], station["capacity"]["minimum"]) == (
        "integer",
        1,
    )
    source = {item["name"]: item for item in data["source"]}
    assert source["interarrival"]["exclusive"] is True
    assert source["limit"]["kind"] == "integer"
    run = {item["name"]: item for item in data["run"]}
    assert run["seed"]["default"] == 42
    assert data["model"][0]["default"] == "minutes"
    assert {"model", "results", "print", "exponential", "class"} <= set(
        data["reserved"]
    )


def test_builder_page_embeds_the_schema_and_requests_nothing():
    page = flowsim.builder()
    assert isinstance(page, flowsim.Viewer)
    document = page.html
    embedded = re.search(SCHEMA_SCRIPT, document, re.DOTALL).group(1)
    assert json.loads(embedded) == json.loads(json.dumps(schema()))
    tags = re.findall(r"<(?:script|link|img|iframe)\b[^>]*>", document)
    assert tags and not any("http" in tag for tag in tags)
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", document, re.DOTALL)
    assert not any(re.search(r"https?:", script) for script in scripts)
    assert 'sandbox="allow-scripts allow-downloads"' in page._repr_html_()
    assert "model builder page" in repr(page)


# Browser helpers. Each drives the page through its controls.


def add_node(page, kind, name, fields=None, durations=None):
    """Add a node, fill its panel, and return its id."""
    page.click(f"#add-{kind}")
    node_id = page.locator("#panel").get_attribute("data-node-id")
    page.fill("#field-name", name)
    for field, (distribution, values) in (durations or {}).items():
        page.select_option(f"#field-{field}-kind", distribution)
        for key, value in values.items():
            page.fill(f"#field-{field}-{key}", str(value))
    for field, value in (fields or {}).items():
        page.fill(f"#field-{field}", str(value))
    return node_id


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def drag(page, start, end):
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=8)
    page.mouse.up()


def node_box(page, node_id):
    return page.locator(f'g.node[data-node-id="{node_id}"] rect.body').bounding_box()


def drag_route(page, origin, target):
    """Draw a route by dragging from the origin's handle to the target."""
    handle = page.locator(f'g.node[data-node-id="{origin}"] .handle').bounding_box()
    drag(page, center(handle), center(node_box(page, target)))


def panel_route(page, origin, target):
    """Add a route from the side panel of the selected origin."""
    page.locator(f'g.node[data-node-id="{origin}"] rect.body').click(
        position={"x": 8, "y": 8}
    )
    page.select_option("#route-target", target)
    page.click("#add-route")


def node_state(page, node_id):
    nodes = page.evaluate("window.flowsimBuilder.state()")["nodes"]
    return next(node for node in nodes if node["id"] == node_id)


def run_script(code, tmp_path, monkeypatch):
    """Run generated code as a script in a temporary folder; return its results."""
    script = tmp_path / "generated" / "model.py"
    script.parent.mkdir()
    script.write_text(code, encoding="utf-8")
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.fail(
            "ruff is not on PATH; run the tests through pixi so the formatting check runs."
        )
    formatted = subprocess.run(
        [ruff, "format", "--diff", str(script)],
        capture_output=True,
        text=True,
    )
    assert formatted.returncode == 0, formatted.stdout + formatted.stderr
    monkeypatch.chdir(script.parent)
    return runpy.run_path(str(script), run_name="__main__")["results"]


def assert_same_run(results, expected):
    for table in ("customers", "visits", "stations", "summary"):
        assert_frame_equal(getattr(results, table), getattr(expected, table))


def open_builder(tmp_path, engine_page):
    path = tmp_path / "builder.html"
    flowsim.builder(path)
    return engine_page(path)


def build_branching_service(page):
    """Draw tests.models.branching_service with named distributions and a branch."""
    page.fill("#run-duration", "120")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("exponential", {"mean": 3})},
    )
    triage = add_node(
        page,
        kind="station",
        name="Triage",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    routine = add_node(
        page,
        kind="station",
        name="Routine",
        fields={"capacity": 2},
        durations={"service_time": ("gamma", {"shape": 2, "scale": 2})},
    )
    specialist = add_node(
        page,
        kind="station",
        name="Specialist",
        fields={"capacity": 1},
        durations={"service_time": ("uniform", {"low": 5, "high": 8})},
    )
    # Move Specialist below Routine by dragging it.
    before = node_state(page, specialist)
    below = center(node_box(page, routine))
    drag(page, center(node_box(page, specialist)), (below[0], below[1] + 150))
    after = node_state(page, specialist)
    assert after["y"] > before["y"] + 100 and after["x"] < before["x"]
    drag_route(page, customers, triage)
    drag_route(page, triage, routine)
    drag_route(page, triage, specialist)
    # A second route from Triage makes a branch with probabilities on the arrows.
    arrow = f'.edge-prob[data-from="{triage}"][data-to="{routine}"]'
    assert page.locator(arrow).input_value() == "0.5"
    page.fill(arrow, "0.7")
    assert "sum to 1.2" in page.locator("#problems").inner_text()
    page.locator(f'g.node[data-node-id="{triage}"] rect.body').click(
        position={"x": 8, "y": 8}
    )
    page.fill(f'.panel-prob[data-to="{specialist}"]', "0.3")
    assert page.locator(arrow).input_value() == "0.7"
    panel_route(page, routine, "exit")
    drag_route(page, specialist, "exit")


def test_builder_writes_the_deterministic_queue(tmp_path, engine_page, monkeypatch):
    page = open_builder(tmp_path, engine_page)
    assert "Add a source" in page.locator("#problems").inner_text()
    page.fill("#run-duration", "10")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        fields={"first_arrival": 0, "limit": 3},
        durations={"interarrival": ("constant", {"value": 1})},
    )
    service = add_node(
        page,
        kind="station",
        name="Service",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 2})},
    )
    drag_route(page, customers, service)
    assert "Service: It has no onward route" in page.locator("#problems").inner_text()
    drag_route(page, service, "exit")
    assert "No problems found" in page.locator("#problems").inner_text()
    code = page.locator("#code").text_content()
    assert code == (
        '"""A FlowSim model drawn in the model builder. '
        'Edit it like any FlowSim script."""\n'
        "\n"
        "from flowsim import Model\n"
        "\n"
        'model = Model(time_unit="minutes")\n'
        "customers = model.source(\n"
        '    name="Customers",\n'
        "    interarrival=1,\n"
        "    first_arrival=0,\n"
        "    limit=3,\n"
        ")\n"
        "service = model.station(\n"
        '    name="Service",\n'
        "    capacity=1,\n"
        "    service_time=2,\n"
        ")\n"
        "model.route([customers, service, model.exit])\n"
        "\n"
        "results = model.run(\n"
        "    duration=10,\n"
        "    seed=42,\n"
        ")\n"
        "print(results)\n"
    )
    results = run_script(code, tmp_path, monkeypatch)
    expected = deterministic_queue().run(
        duration=10,
        seed=42,
    )
    assert_same_run(results, expected)
    # The hand-calculated waits: 0, 1, and 2 minutes.
    waits = results.visits.get_column("wait_time").to_list()
    assert waits == [0, 1, 2]


def test_builder_writes_a_branching_network(tmp_path, engine_page, monkeypatch):
    page = open_builder(tmp_path, engine_page)
    build_branching_service(page)
    assert "No problems found" in page.locator("#problems").inner_text()
    code = page.locator("#code").text_content()
    assert "from flowsim import Model, exponential, gamma, uniform\n" in code
    assert "model.route([customers, triage])\n" in code
    assert "model.branch(triage, {routine: 0.7, specialist: 0.3})\n" in code
    with page.expect_download() as download_info:
        page.click("#download-code")
    download = download_info.value
    assert download.suggested_filename == "flowsim_model.py"
    saved = tmp_path / "download.py"
    download.save_as(saved)
    assert saved.read_text(encoding="utf-8") == code
    results = run_script(code, tmp_path, monkeypatch)
    expected = branching_service().run(
        duration=120,
        seed=42,
    )
    assert_same_run(results, expected)


def wait_for_status(page, text):
    """Wait for the file status, which the page sets after reading the file."""
    page.wait_for_function(
        "text => document.getElementById('file-status').textContent.includes(text)",
        arg=text,
    )


def test_builder_saves_and_loads_its_model_file(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    build_branching_service(page)
    code = page.locator("#code").text_content()
    state = page.evaluate("window.flowsimBuilder.state()")
    with page.expect_download() as download_info:
        page.click("#save-json")
    saved = tmp_path / download_info.value.suggested_filename
    download_info.value.save_as(saved)
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert (data["format"], data["version"]) == ("flowsim-builder", 2)
    assert data == state
    triage = next(node for node in data["nodes"] if node["name"] == "Triage")
    assert triage["service_time"] == {"name": "constant", "value": 1}
    page.click("#clear-model")
    assert "Add a source" in page.locator("#problems").inner_text()
    page.set_input_files("#load-json", str(saved))
    wait_for_status(page, "Loaded flowsim_model.json.")
    assert page.locator("#code").text_content() == code
    assert page.evaluate("window.flowsimBuilder.state()") == state
    # A file in another format version is refused, and the model stays.
    later = tmp_path / "later.json"
    later.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")
    page.set_input_files("#load-json", str(later))
    wait_for_status(page, "version 99")
    assert page.locator("#code").text_content() == code


@pytest.mark.parametrize(
    argnames=("name", "identifier"),
    argvalues=[
        ("Check-in", "check_in"),
        ("2nd desk", "station_2nd_desk"),
        ("print", "print_station"),
    ],
)
def test_builder_derives_valid_unique_names(tmp_path, engine_page, name, identifier):
    page = open_builder(tmp_path, engine_page)
    add_node(page, kind="station", name=name)
    add_node(page, kind="station", name=f"{name} ")
    code = page.locator("#code").text_content()
    assert f"{identifier} = model.station(" in code
    assert f"{identifier}_2 = model.station(" in code
    assert "are named" in page.locator("#problems").inner_text()


def two_node_model(page):
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    service = add_node(
        page,
        kind="station",
        name="Service",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 2})},
    )
    drag_route(page, customers, service)
    drag_route(page, service, "exit")
    return customers, service


def refuse_file(page, tmp_path, data, message):
    """Load a file that must be refused and check the model did not change."""
    code = page.locator("#code").text_content()
    state = page.evaluate("window.flowsimBuilder.state()")
    # Each refused file has its own name, so the wait below cannot be met by
    # the status the previous refusal left on the page.
    path = tmp_path / f"bad-{len(list(tmp_path.glob('bad-*.json'))) + 1}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    page.set_input_files("#load-json", str(path))
    wait_for_status(page, f"Could not load {path.name}")
    assert message in page.locator("#file-status").text_content()
    assert page.locator("#code").text_content() == code
    assert page.evaluate("window.flowsimBuilder.state()") == state


def test_builder_refuses_a_loaded_node_id_that_would_reach_the_html(
    tmp_path, engine_page
):
    page = open_builder(tmp_path, engine_page)
    two_node_model(page)
    data = page.evaluate("window.flowsimBuilder.state()")
    hostile = 'n1" onmouseover="window.pwned=1'
    data["nodes"][0]["id"] = hostile
    for edge in data["edges"]:
        if edge["from"] == "n1":
            edge["from"] = hostile
    refuse_file(page, tmp_path, data, "Every node id must be")
    assert page.locator("[onmouseover]").count() == 0
    assert page.evaluate("window.pwned") is None
    # Ids that are not strings, or are repeated, are refused too.
    numbered = json.loads(json.dumps(data))
    numbered["nodes"][0]["id"] = 5
    refuse_file(page, tmp_path, numbered, "Every node id must be")
    repeated = json.loads(json.dumps(data))
    repeated["nodes"][0]["id"] = repeated["nodes"][1]["id"]
    refuse_file(page, tmp_path, repeated, "Two nodes have the id")


def test_builder_refuses_a_loaded_route_the_page_would_not_add(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    customers, service = two_node_model(page)
    data = page.evaluate("window.flowsimBuilder.state()")
    routes = data["edges"]

    def with_edge(edge):
        return {**data, "edges": [*routes, edge]}

    def route(origin, target):
        return {"from": origin, "to": target, "probability": 1}

    refuse_file(
        page,
        tmp_path,
        with_edge(route(customers, service)),
        "Customers already routes to Service.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route(service, service)),
        "A node cannot route to itself.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route(service, customers)),
        "A source cannot receive routed customers.",
    )
    refuse_file(
        page,
        tmp_path,
        with_edge(route("exit", service)),
        "The exit cannot have an outgoing route.",
    )
    # Endpoints must be strings, so 1 and "1" cannot both pass.
    refuse_file(
        page,
        tmp_path,
        with_edge(route(1, service)),
        "A route names a node the file does not have.",
    )


def test_builder_flags_integers_that_a_number_cannot_hold_exactly(
    tmp_path, engine_page
):
    page = open_builder(tmp_path, engine_page)
    two_node_model(page)
    page.fill("#run-duration", "10")
    page.fill("#run-seed", "9007199254740993")
    assert "Seed must be a whole number" in page.locator("#problems").inner_text()
    assert "seed=None" in page.locator("#code").text_content()
    assert "9007199254740992" not in page.locator("#code").text_content()
    page.fill("#run-seed", "1e21")
    assert "Seed must be a whole number" in page.locator("#problems").inner_text()
    assert "seed=None" in page.locator("#code").text_content()
    page.fill("#run-seed", "9007199254740991")
    assert "No problems found" in page.locator("#problems").inner_text()
    assert "seed=9007199254740991" in page.locator("#code").text_content()
    page.fill("#run-seed", "007")
    assert "seed=7," in page.locator("#code").text_content()
    for text in ("2.0", "-3", "1e2"):
        page.fill("#field-capacity", text)
        assert (
            "capacity must be a whole number" in page.locator("#problems").inner_text()
        )


def test_builder_branch_tolerance_comes_from_the_model_check():
    tolerance = schema()["branch_sum_tolerance"]
    assert tolerance == flowsim.model.BRANCH_SUM_TOLERANCE

    def branch(extra):
        model = flowsim.Model()
        model.source(
            name="In",
            interarrival=1,
        )
        stations = [
            model.station(
                name=name,
                capacity=1,
                service_time=1,
            )
            for name in "ABC"
        ]
        model.branch(
            stations[0],
            {stations[1]: 0.5, stations[2]: 0.5 + extra},
        )

    branch(tolerance / 2)
    with pytest.raises(ValueError, match="must sum to one"):
        branch(tolerance * 2)


def test_builder_flags_branch_sums_outside_the_model_tolerance(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    triage = add_node(
        page,
        kind="station",
        name="Triage",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    first = add_node(
        page,
        kind="station",
        name="First",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    drag_route(page, customers, triage)
    panel_route(page, triage, first)
    panel_route(page, triage, "exit")
    arrow = f'.edge-prob[data-from="{triage}"][data-to="{first}"]'
    other = f'.edge-prob[data-from="{triage}"][data-to="exit"]'
    page.fill(arrow, "0.5")
    page.fill(other, "0.5000000001")
    assert "sum to 1.0000000001, not 1" in page.locator("#problems").inner_text()
    page.fill(arrow, "0.7")
    page.fill(other, "0.3")
    assert "sum to" not in page.locator("#problems").inner_text()


def active_id(page):
    return page.evaluate("document.activeElement.id")


def test_builder_builds_and_edits_a_model_from_the_keyboard(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    assert page.locator("#excluded-arguments").text_content() == ""
    page.fill("#run-duration", "10")
    # Adding a node moves focus to its name, and the live region announces it.
    page.focus("#add-source")
    page.keyboard.press("Enter")
    assert active_id(page) == "field-name"
    assert "Added source Source" in page.locator("#announce").text_content()
    page.keyboard.press("Control+a")
    page.keyboard.type("Customers")
    page.select_option("#field-interarrival-kind", "constant")
    page.fill("#field-interarrival-value", "1")
    page.fill("#field-first_arrival", "0")
    page.fill("#field-limit", "3")
    page.focus("#add-station")
    page.keyboard.press("Enter")
    page.keyboard.press("Control+a")
    page.keyboard.type("Service")
    page.select_option("#field-service_time-kind", "constant")
    page.fill("#field-service_time-value", "2")
    station = page.locator("#panel").get_attribute("data-node-id")
    # Tabbing to a node selects it, and Enter moves into its panel.
    page.focus('g.node[data-node-id="n1"]')
    assert page.locator("#panel").get_attribute("data-node-id") == "n1"
    assert (
        page.locator('g.node[data-node-id="n1"]').get_attribute("aria-pressed")
        == "true"
    )
    page.keyboard.press("Enter")
    assert active_id(page) == "field-name"
    # The panel's route controls connect nodes without a pointer.
    page.select_option("#route-target", station)
    page.focus("#add-route")
    page.keyboard.press("Enter")
    assert active_id(page) == "route-target"
    page.focus(f'g.node[data-node-id="{station}"]')
    page.keyboard.press("Enter")
    page.select_option("#route-target", "exit")
    page.focus("#add-route")
    page.keyboard.press("Enter")
    assert "No problems found" in page.locator("#problems").inner_text()
    # Each node and arrow has a name and a role for assistive technology.
    customers = page.locator('g.node[data-node-id="n1"]')
    assert customers.get_attribute("role") == "button"
    assert customers.get_attribute("aria-label") == "source Customers: constant 1"
    arrow = page.locator(f'.edge-hit[data-from="n1"][data-to="{station}"]')
    assert arrow.get_attribute("aria-label") == "Route from Customers to Service"
    # Arrow keys move a focused node by 10, or by 50 with Shift.
    before = node_state(page, "n1")
    page.focus('g.node[data-node-id="n1"]')
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    after = node_state(page, "n1")
    assert (after["x"], after["y"]) == (before["x"] + 10, before["y"] + 50)
    assert page.evaluate("document.activeElement.dataset.focusKey") == "node:n1"
    results = run_script(page.locator("#code").text_content(), tmp_path, monkeypatch)
    assert_same_run(
        results,
        deterministic_queue().run(
            duration=10,
            seed=42,
        ),
    )
    # Escape clears the selection, and Delete removes the focused node.
    page.keyboard.press("Escape")
    assert page.locator("#panel h2").text_content() == "Nothing selected"
    page.focus(f'g.node[data-node-id="{station}"]')
    page.keyboard.press("Delete")
    assert page.locator(f'g.node[data-node-id="{station}"]').count() == 0
    assert active_id(page) == "canvas"
    assert "Deleted station Service" in page.locator("#announce").text_content()


def test_builder_undoes_and_redoes_each_change(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    assert page.locator("#undo").is_disabled() and page.locator("#redo").is_disabled()
    empty = page.evaluate("window.flowsimBuilder.state()")
    source = add_node(page, kind="source", name="Customers")
    # Adding a node and typing its name are two steps; the keystrokes are one.
    named = page.evaluate("window.flowsimBuilder.state()")
    station = add_node(page, kind="station", name="Desk")
    drag_route(page, source, station)
    routed = page.evaluate("window.flowsimBuilder.state()")
    drag(page, center(node_box(page, station)), (700, 600))
    moved = page.evaluate("window.flowsimBuilder.state()")
    assert moved != routed
    page.locator("#canvas rect.background").click(position={"x": 5, "y": 5})
    page.keyboard.press("Control+z")
    assert page.evaluate("window.flowsimBuilder.state()") == routed
    page.click("#undo")
    page.click("#undo")
    page.click("#undo")
    assert page.evaluate("window.flowsimBuilder.state()") == named
    page.keyboard.press("Control+Shift+z")
    page.keyboard.press("Control+y")
    page.keyboard.press("Control+y")
    page.keyboard.press("Control+y")
    assert page.evaluate("window.flowsimBuilder.state()") == moved
    assert page.locator("#redo").is_disabled()
    # Inside a text field, Ctrl+Z is the browser's own undo of that field.
    page.focus("#run-seed")
    page.keyboard.press("Control+z")
    assert page.evaluate("window.flowsimBuilder.state()") == moved
    # New model and file loading are undoable, and a new change clears redo.
    page.click("#clear-model")
    assert page.evaluate("window.flowsimBuilder.state()") == empty
    page.click("#undo")
    assert page.evaluate("window.flowsimBuilder.state()") == moved
    page.click("#undo")
    page.click("#arrange")
    assert page.locator("#redo").is_disabled()
    # The history keeps the last 100 steps.
    page.evaluate(
        "() => { for (let i = 0; i < 105; i += 1) "
        "document.getElementById('arrange').click(); }"
    )
    undone = page.evaluate(
        "() => { let count = 0; const button = document.getElementById('undo'); "
        "while (!button.disabled) { button.click(); count += 1; } return count; }"
    )
    assert undone == 100


def test_builder_arranges_nodes_in_left_to_right_layers(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    build_branching_service(page)
    before = page.evaluate("window.flowsimBuilder.state()")
    page.click("#arrange")

    def position(name):
        nodes = page.evaluate("window.flowsimBuilder.state()")["nodes"]
        node = next(node for node in nodes if node["name"] == name)
        return node["x"], node["y"]

    # Four layers (920 - 60 - 150) / 3 = 236.67 apart, under the 240 cap, so x
    # is 30, 266.67, 503.33, and 740, rounded. A one-node layer starts at (520 - 95) / 2 = 212.5, which rounds to 213,
    # and the two-node layer at (520 - 190) / 2 = 165, then 165 + 95 = 260.
    assert position("Customers") == (30, 213)
    assert position("Triage") == (267, 213)
    assert position("Routine") == (503, 165)
    assert position("Specialist") == (503, 260)
    assert position("Exit") == (740, 213)
    assert "Arranged 5 nodes in 4 columns." in page.locator("#announce").text_content()
    page.click("#undo")
    assert page.evaluate("window.flowsimBuilder.state()") == before


def test_builder_arranges_a_loop_by_steps_from_the_sources(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    source = add_node(page, kind="source", name="S")
    first = add_node(page, kind="station", name="A")
    second = add_node(page, kind="station", name="B")
    panel_route(page, source, first)
    panel_route(page, first, second)
    panel_route(page, second, first)
    panel_route(page, second, "exit")
    assert "form a loop" in page.locator("#problems").inner_text()
    page.click("#arrange")
    nodes = page.evaluate("window.flowsimBuilder.state()")["nodes"]
    # S is 0 steps from the source, A is 1, and B is 2, then the exit.
    assert [node["x"] for node in nodes] == [740, 30, 267, 503]


def history_sizes(page):
    """Count undo and redo steps by clicking each button until it disables."""
    return page.evaluate(
        "() => { const count = (id) => { let n = 0; const b = "
        "document.getElementById(id); while (!b.disabled) { b.click(); n += 1; } "
        "return n; }; const undone = count('undo'); count('redo'); return undone; }"
    )


def test_builder_route_choice_keeps_redo_and_a_route_is_one_step(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    source = add_node(page, kind="source", name="Customers")
    add_node(page, kind="station", name="Desk")
    page.click("#undo")
    page.locator(f'g.node[data-node-id="{source}"] rect.body').click(
        position={"x": 8, "y": 8}
    )
    # Choosing a destination edits nothing, so the undone name can be redone.
    page.select_option("#route-target", "exit")
    assert not page.locator("#redo").is_disabled()
    page.click("#redo")
    steps = history_sizes(page)
    page.click("#add-route")
    assert history_sizes(page) == steps + 1


def test_builder_arranges_a_long_chain_without_overlap(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    ids = [add_node(page, kind="source", name="In")]
    ids += [add_node(page, kind="station", name=f"S{index}") for index in range(4)]
    for origin, target in zip(ids, [*ids[1:], "exit"]):
        panel_route(page, origin, target)
    page.click("#arrange")
    nodes = page.evaluate("window.flowsimBuilder.state()")["nodes"]
    # Six columns would fit 142 apart, under the 150 + 40 minimum, so they sit
    # 190 apart from x = 30, and the canvas widens to 980 + 150 + 30 = 1160.
    by_x = sorted((node["x"], node["y"]) for node in nodes)
    assert by_x == [(x, 213) for x in [30, 220, 410, 600, 790, 980]]
    assert page.locator("#canvas").get_attribute("viewBox") == "0 0 1160 520"


def problems_text(page):
    return page.locator("#problems").inner_text()


def select_edge(page, origin, target):
    """Select an arrow by giving it keyboard focus, which selects it."""
    page.focus(f'.edge-hit[data-from="{origin}"][data-to="{target}"]')


def set_edge_types(page, origin, target, types):
    select_edge(page, origin, target)
    page.check("#edge-types-some")
    for type_id in types:
        page.check(f"#edge-type-{type_id}")


def select_node(page, node_id):
    page.locator(f'g.node[data-node-id="{node_id}"] rect.body').click(
        position={"x": 8, "y": 8}
    )


def test_builder_writes_customer_types_priorities_and_typed_routes(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    page.fill("#run-duration", "120")
    page.click("#add-type")
    page.fill("#type-name-t1", "Walk-in")
    page.click("#add-type")
    page.fill("#type-name-t2", "Appointment")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("exponential", {"mean": 3})},
    )
    # The page fills no type mix; each blank probability is listed.
    assert "Customers: probability of Walk-in needs a value." in problems_text(page)
    page.fill("#field-mix-t1", "0.6")
    page.fill("#field-mix-t2", "0.3")
    assert "type probabilities sum to 0.9, not 1" in problems_text(page)
    page.fill("#field-mix-t2", "0.4")
    desk = add_node(page, kind="station", name="Desk", fields={"capacity": 1})
    page.check("#field-service_by_type")
    page.select_option("#field-service_time-t1-kind", "exponential")
    page.fill("#field-service_time-t1-mean", "4")
    page.select_option("#field-service_time-t2-kind", "constant")
    page.fill("#field-service_time-t2-value", "2")
    page.check("#field-priority_on")
    assert "Desk: rank of Walk-in needs a value." in problems_text(page)
    page.fill("#field-priority-t1", "2")
    page.fill("#field-priority-t2", "1")
    exam = add_node(
        page,
        kind="station",
        name="Exam",
        fields={"capacity": 2},
        durations={"service_time": ("uniform", {"low": 3, "high": 6})},
    )
    panel_route(page, customers, desk)
    panel_route(page, desk, exam)
    panel_route(page, desk, "exit")
    # Desk's second arrow opens its panel on the choice between a split by
    # probability and a split by customer type, and that panel sets the types
    # of both arrows.
    assert page.evaluate("document.activeElement.id") == "edge-types-all"
    assert "How customers leaving Desk choose a route" in (
        page.locator("#panel").inner_text()
    )
    page.check("#edge-types-some")
    assert "Route from Desk to Exam needs at least one customer type." in (
        problems_text(page)
    )
    (to_exam,) = edge_ids(page, desk, exam)
    page.check(f"#edge-type-{to_exam}-t2")
    page.check("#edge-type-t1")
    panel_route(page, exam, "exit")
    assert "No problems found" in problems_text(page)
    # Only a loaded file can mix an arrow for every type with typed arrows.
    typed = page.evaluate("window.flowsimBuilder.state()")
    mixed = json.loads(json.dumps(typed))
    next(edge for edge in mixed["edges"] if (edge["from"], edge["to"]) == (desk, exam))[
        "types"
    ] = None
    for name, data in (("mixed", mixed), ("typed", typed)):
        saved = tmp_path / f"{name}.json"
        saved.write_text(json.dumps(data), encoding="utf-8")
        page.set_input_files("#load-json", str(saved))
        wait_for_status(page, f"Loaded {name}.json.")
        assert (
            "some arrows carry every type and some only named types"
            in problems_text(page)
        ) == (name == "mixed")
    select_edge(page, desk, "exit")
    page.uncheck("#edge-type-t1")
    assert "Desk has no route for type Walk-in, which can reach it from Customers." in (
        problems_text(page)
    )
    page.check("#edge-type-t1")
    code = page.locator("#code").text_content()
    assert (
        "customers = model.source(\n"
        '    name="Customers",\n'
        "    interarrival=exponential(mean=3),\n"
        '    types={"Walk-in": 0.6, "Appointment": 0.4},\n'
        ")\n"
    ) in code
    assert (
        '    service_time={"Walk-in": exponential(mean=4), "Appointment": 2},\n' in code
    )
    assert '    priority={"Walk-in": 2, "Appointment": 1},\n' in code
    assert 'model.route([desk, exam], types=["Appointment"])\n' in code
    assert 'model.route([desk, model.exit], types=["Walk-in"])\n' in code
    results = run_script(code, tmp_path, monkeypatch)
    model = flowsim.Model()
    arrivals = model.source(
        name="Customers",
        interarrival=flowsim.exponential(mean=3),
        types={"Walk-in": 0.6, "Appointment": 0.4},
    )
    front = model.station(
        name="Desk",
        capacity=1,
        service_time={"Walk-in": flowsim.exponential(mean=4), "Appointment": 2},
        priority={"Walk-in": 2, "Appointment": 1},
    )
    room = model.station(
        name="Exam",
        capacity=2,
        service_time=flowsim.uniform(
            low=3,
            high=6,
        ),
    )
    model.route([arrivals, front])
    model.route([room, model.exit])
    model.route([front, room], types=["Appointment"])
    model.route([front, model.exit], types=["Walk-in"])
    assert_same_run(
        results,
        model.run(
            duration=120,
            seed=42,
        ),
    )
    # Removing a type clears its mix entries and its place on routes.
    page.click('.remove-type[data-type="t2"]')
    state = page.evaluate("window.flowsimBuilder.state()")
    source = next(node for node in state["nodes"] if node["name"] == "Customers")
    assert source["mix"] == {"t1": 0.6}
    assert [edge["types"] for edge in state["edges"]] == [None, [], ["t1"], None]


def test_builder_asks_how_a_source_splits_when_its_second_arrow_is_drawn(
    tmp_path, engine_page
):
    page = open_builder(tmp_path, engine_page)
    page.click("#add-type")
    page.fill("#type-name-t1", "New")
    page.click("#add-type")
    page.fill("#type-name-t2", "Existing")
    arrivals = add_node(
        page,
        kind="source",
        name="Arrivals",
        durations={"interarrival": ("constant", {"value": 5})},
    )
    page.fill("#field-mix-t1", "0.4")
    page.fill("#field-mix-t2", "0.6")
    stations = {
        name: add_node(
            page,
            kind="station",
            name=name,
            fields={"capacity": 1},
            durations={"service_time": ("constant", {"value": 2})},
        )
        for name in ("Registration", "Check-in")
    }
    registration, check_in = stations["Registration"], stations["Check-in"]
    panel_route(page, registration, check_in)
    panel_route(page, check_in, "exit")
    # The first arrow carries every customer, so the page asks nothing.
    drag_route(page, arrivals, registration)
    assert page.locator("#panel h2").first.inner_text() != "Route"
    # The second arrow opens its panel on the choice, which starts as a split
    # by probability, and one undo step removes the arrow.
    drag_route(page, arrivals, check_in)
    assert page.locator("#panel h2").first.inner_text() == "Route"
    assert page.evaluate("document.activeElement.id") == "edge-types-all"
    assert "How customers leaving Arrivals choose a route" in (
        page.locator("#panel").inner_text()
    )
    page.keyboard.press("Control+z")
    assert edge_ids(page, arrivals, check_in) == []
    page.keyboard.press("Control+y")
    (to_registration,) = edge_ids(page, arrivals, registration)
    (to_check_in,) = edge_ids(page, arrivals, check_in)
    page.focus(f'.edge-hit[data-edge="{to_check_in}"]')
    # A split by customer type lists both arrows in the one panel.
    page.check("#edge-types-some")
    page.check("#edge-type-t2")
    page.check(f"#edge-type-{to_registration}-t1")
    assert "No problems found" in problems_text(page)
    code = page.locator("#code").text_content()
    assert 'model.route([arrivals, registration], types=["New"])\n' in code
    assert 'model.route([arrivals, check_in], types=["Existing"])\n' in code
    # A split by probability clears the types of every arrow from the source.
    page.check("#edge-types-all")
    edges = page.evaluate("window.flowsimBuilder.state()")["edges"]
    assert [
        (edge["types"], edge["probability"])
        for edge in edges
        if edge["from"] == arrivals
    ] == [(None, 0.5), (None, 0.5)]
    # A third arrow from a node that routes by type starts with no type chosen.
    page.check("#edge-types-some")
    panel_route(page, arrivals, "exit")
    assert page.evaluate("document.activeElement.id") == "edge-types-some"
    assert "Route from Arrivals to Exit needs at least one customer type." in (
        problems_text(page)
    )


def edge_ids(page, origin, target):
    """Return the ids of the arrows from origin to target, in drawing order."""
    return page.locator(
        f'.edge-hit[data-from="{origin}"][data-to="{target}"]'
    ).evaluate_all("items => items.map((item) => item.dataset.edge)")


def set_types_of(page, edge, types):
    """Select one arrow by its id and give it exactly these customer types."""
    page.focus(f'.edge-hit[data-edge="{edge}"]')
    page.check("#edge-types-some")
    for type_id in ["t1", "t2"]:
        if type_id in types:
            page.check(f"#edge-type-{type_id}")
        else:
            page.uncheck(f"#edge-type-{type_id}")


def test_builder_draws_two_routes_between_the_same_nodes_for_different_types(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    customers, service = two_node_model(page)
    # Without customer types, a second route could not differ from the first.
    drag_route(page, customers, service)
    assert "Customers already routes to Service. A second route" in (
        page.locator("#canvas-status").text_content()
    )
    assert len(edge_ids(page, customers, service)) == 1
    page = open_builder(tmp_path, engine_page)
    page.fill("#run-duration", "120")
    page.click("#add-type")
    page.fill("#type-name-t1", "Walk-in")
    page.click("#add-type")
    page.fill("#type-name-t2", "Appointment")
    customers = add_node(
        page,
        kind="source",
        name="Customers",
        durations={"interarrival": ("exponential", {"mean": 3})},
    )
    page.fill("#field-mix-t1", "0.6")
    page.fill("#field-mix-t2", "0.4")
    desk = add_node(
        page,
        kind="station",
        name="Desk",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1})},
    )
    exam = add_node(
        page,
        kind="station",
        name="Exam",
        fields={"capacity": 2},
        durations={"service_time": ("uniform", {"low": 3, "high": 6})},
    )
    panel_route(page, customers, desk)
    panel_route(page, exam, "exit")
    drag_route(page, desk, exam)
    # With types, a second route to Exam is drawn beside the first, with no
    # type chosen, and one undo step removes it.
    drag_route(page, desk, exam)
    first, second = edge_ids(page, desk, exam)
    paths = page.locator(
        f'path.edge[data-from="{desk}"][data-to="{exam}"]'
    ).evaluate_all("items => items.map((item) => item.getAttribute('d'))")
    assert len(set(paths)) == 2
    assert "Route from Desk to Exam needs at least one customer type." in (
        problems_text(page)
    )
    page.keyboard.press("Control+z")
    assert edge_ids(page, desk, exam) == [first]
    page.keyboard.press("Control+y")
    assert edge_ids(page, desk, exam) == [first, second]
    set_types_of(page, first, ["t1"])
    set_types_of(page, second, ["t1"])
    assert "Desk has two routes to Exam for type Walk-in." in problems_text(page)
    set_types_of(page, second, ["t2"])
    # Appointments branch from Desk to Exam or the exit.
    panel_route(page, desk, "exit")
    (leave,) = edge_ids(page, desk, "exit")
    set_types_of(page, leave, ["t2"])
    page.fill(f'.edge-prob[data-edge="{second}"]', "0.3")
    page.fill(f'.edge-prob[data-edge="{leave}"]', "0.7")
    assert "No problems found" in problems_text(page)
    code = page.locator("#code").text_content()
    assert 'model.route([desk, exam], types=["Walk-in"])\n' in code
    assert (
        'model.branch(desk, {exam: 0.3, model.exit: 0.7}, types=["Appointment"])\n'
        in (code)
    )
    results = run_script(code, tmp_path, monkeypatch)
    model = flowsim.Model()
    arrivals = model.source(
        name="Customers",
        interarrival=flowsim.exponential(mean=3),
        types={"Walk-in": 0.6, "Appointment": 0.4},
    )
    front = model.station(
        name="Desk",
        capacity=1,
        service_time=1,
    )
    room = model.station(
        name="Exam",
        capacity=2,
        service_time=flowsim.uniform(
            low=3,
            high=6,
        ),
    )
    model.route([arrivals, front])
    model.route([room, model.exit])
    model.route([front, room], types=["Walk-in"])
    model.branch(front, {room: 0.3, model.exit: 0.7}, types=["Appointment"])
    assert_same_run(
        results,
        model.run(
            duration=120,
            seed=42,
        ),
    )
    # Saving and loading keeps both routes.
    state = page.evaluate("window.flowsimBuilder.state()")
    path = tmp_path / "two-routes.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    page.set_input_files("#load-json", str(path))
    wait_for_status(page, "Loaded two-routes.json")
    assert page.evaluate("window.flowsimBuilder.state()") == state
    assert page.locator("#code").text_content() == code
    # On a diagonal, each parallel arrow starts and ends outside the boxes,
    # which are 150 by 58 pixels and drawn over the arrows, with two arrows
    # and with three.
    for node in state["nodes"]:
        if node["id"] == desk:
            node.update(x=30, y=40)
        if node["id"] == exam:
            node.update(x=205, y=155)
    path.write_text(json.dumps(state), encoding="utf-8")
    page.set_input_files("#load-json", str(path))
    wait_for_status(page, "Loaded two-routes.json")

    def ends_outside(count):
        paths = page.locator(
            f'path.edge[data-from="{desk}"][data-to="{exam}"]'
        ).evaluate_all("items => items.map((item) => item.getAttribute('d'))")
        assert len(paths) == count
        for d in paths:
            numbers = [float(value) for value in re.findall(r"-?[\d.]+", d)]
            (x0, y0), (x1, y1) = numbers[:2], numbers[-2:]
            assert not (30 <= x0 <= 180 and 40 <= y0 <= 98)
            assert not (205 <= x1 <= 355 and 155 <= y1 <= 213)

    ends_outside(2)
    drag_route(page, desk, exam)
    ends_outside(3)
    page.keyboard.press("Control+z")
    ends_outside(2)
    # The last type cannot go while two routes join Desk and Exam.
    page.click('.remove-type[data-type="t2"]')
    page.click('.remove-type[data-type="t1"]')
    assert "Remove a route from Desk to Exam first." in (
        page.locator("#canvas-status").text_content()
    )
    assert [
        item["name"] for item in page.evaluate("window.flowsimBuilder.state()")["types"]
    ] == ["Walk-in"]


def test_builder_writes_schedules_buffers_abandonment_and_failures(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    page.fill("#run-duration", "120")
    arrivals = add_node(page, kind="source", name="Arrivals")
    page.check("#field-arrivals-rates")
    page.fill("#field-rates-0-value", "0.2")
    page.click("#add-row-rates")
    assert active_id(page) == "field-rates-1-start"
    page.fill("#field-rates-1-start", "60")
    page.fill("#field-rates-1-value", "0.5")
    clinic = add_node(
        page,
        kind="station",
        name="Clinic",
        fields={"capacity": 2},
        durations={"service_time": ("exponential", {"mean": 6})},
    )
    page.check("#field-staffing_on")
    page.fill("#field-staffing-0-value", "1")
    page.click("#add-row-staffing")
    page.fill("#field-staffing-1-start", "60")
    page.fill("#field-staffing-1-value", "3")
    assert "Clinic: servers on duty cannot exceed capacity 2." in problems_text(page)
    page.fill("#field-staffing-1-value", "2")
    # The page never picks a behavior: the missing choice is listed, and the
    # script writes None so FlowSim's own error names it.
    assert "Clinic: choose what an off-duty server does with its current job" in (
        problems_text(page)
    )
    assert "    shift_end=None,\n" in page.locator("#code").text_content()
    assert not page.locator("#field-shift_end-finish").is_checked()
    assert not page.locator("#field-shift_end-pause").is_checked()
    page.check("#field-shift_end-pause")
    page.fill("#field-buffer", "3")
    assert active_id(page) == "field-buffer"
    assert "choose what an arrival does when the buffer is full" in problems_text(page)
    page.check("#field-external_overflow-reject")
    page.check("#field-abandon_on")
    assert "Clinic: patience needs a distribution or a constant." in problems_text(page)
    assert page.locator("#field-abandon_from-waiting_and_outside").is_disabled()
    page.check("#field-external_overflow-wait")
    page.check("#field-abandon_from-waiting_and_outside")
    page.select_option("#field-patience-kind", "exponential")
    assert page.locator("#field-patience-mean").input_value() == ""
    page.fill("#field-patience-mean", "5")
    lab = add_node(
        page,
        kind="station",
        name="Lab",
        fields={"capacity": 1},
        durations={"service_time": ("constant", {"value": 1.5})},
    )
    page.check("#field-failures_on")
    assert "Lab: time_to_failure needs a distribution or a constant." in (
        problems_text(page)
    )
    # Choosing a family fills no parameter: the student types each value.
    page.select_option("#field-repair_time-kind", "constant")
    assert page.locator("#field-repair_time-value").input_value() == ""
    assert "Lab: repair_time needs a value." in problems_text(page)
    assert "    repair_time=None,\n" in page.locator("#code").text_content()
    assert "Lab: choose when the time to failure counts down" in problems_text(page)
    page.select_option("#field-time_to_failure-kind", "exponential")
    page.fill("#field-time_to_failure-mean", "20")
    page.select_option("#field-repair_time-kind", "constant")
    page.fill("#field-repair_time-value", "3")
    page.check("#field-failure_clock-busy")
    panel_route(page, arrivals, clinic)
    panel_route(page, clinic, lab)
    panel_route(page, lab, "exit")
    assert "No problems found" in problems_text(page)
    code = page.locator("#code").text_content()
    assert "    rates=[(0, 0.2), (60, 0.5)],\n" in code
    assert "    staffing=[(0, 1), (60, 2)],\n" in code
    results = run_script(code, tmp_path, monkeypatch)
    model = flowsim.Model()
    source = model.source(
        name="Arrivals",
        rates=[(0, 0.2), (60, 0.5)],
    )
    first = model.station(
        name="Clinic",
        capacity=2,
        service_time=flowsim.exponential(mean=6),
        staffing=[(0, 1), (60, 2)],
        shift_end="pause",
        buffer=3,
        external_overflow="wait",
        patience=flowsim.exponential(mean=5),
        abandon_from="waiting_and_outside",
    )
    second = model.station(
        name="Lab",
        capacity=1,
        service_time=1.5,
        time_to_failure=flowsim.exponential(mean=20),
        repair_time=3,
        failure_clock="busy",
    )
    model.route([source, first, second, model.exit])
    assert_same_run(
        results,
        model.run(
            duration=120,
            seed=42,
        ),
    )
    # Clearing the buffer hides the overflow choice and flags the patience rule.
    select_node(page, clinic)
    page.fill("#field-buffer", "")
    assert page.locator("#field-external_overflow-wait").count() == 0
    assert 'abandon_from "waiting_and_outside" needs a buffer' in problems_text(page)


def version_one_file():
    """A model file saved by the 0.3.0 prototype, which had format version 1."""
    return {
        "format": "flowsim-builder",
        "version": 1,
        "flowsim_version": "0.3.0",
        "time_unit": "minutes",
        "run": {"duration": 10, "seed": 42, "drain": False},
        "nodes": [
            {"id": "exit", "kind": "exit", "name": "Exit", "x": 740, "y": 230},
            {
                "id": "n1",
                "kind": "source",
                "name": "Customers",
                "x": 30,
                "y": 40,
                "interarrival": {"name": "constant", "value": 1},
                "first_arrival": 0,
                "limit": 3,
            },
            {
                "id": "n2",
                "kind": "station",
                "name": "Service",
                "x": 205,
                "y": 40,
                "capacity": 1,
                "service_time": {"name": "constant", "value": 2},
            },
        ],
        "edges": [
            {"from": "n1", "to": "n2", "probability": 1},
            {"from": "n2", "to": "exit", "probability": 1},
        ],
    }


def test_builder_loads_a_version_one_file(tmp_path, engine_page, monkeypatch):
    page = open_builder(tmp_path, engine_page)
    path = tmp_path / "old.json"
    path.write_text(json.dumps(version_one_file()), encoding="utf-8")
    page.set_input_files("#load-json", str(path))
    wait_for_status(page, "Loaded old.json.")
    assert "No problems found" in problems_text(page)
    state = page.evaluate("window.flowsimBuilder.state()")
    assert state["version"] == 2 and state["types"] == []
    station = next(node for node in state["nodes"] if node["id"] == "n2")
    # The fields version 1 lacked start off, with every choice unmade.
    assert (station["buffer"], station["shift_end"], station["abandon_on"]) == (
        None,
        "",
        False,
    )
    results = run_script(page.locator("#code").text_content(), tmp_path, monkeypatch)
    assert_same_run(
        results,
        deterministic_queue().run(
            duration=10,
            seed=42,
        ),
    )


def test_builder_refuses_new_fields_the_page_would_not_write(tmp_path, engine_page):
    page = open_builder(tmp_path, engine_page)
    two_node_model(page)
    page.click("#add-type")
    data = page.evaluate("window.flowsimBuilder.state()")
    service = next(node for node in data["nodes"] if node["name"] == "Service")

    def changed(change):
        copy = json.loads(json.dumps(data))
        change(
            copy, next(node for node in copy["nodes"] if node["id"] == service["id"])
        )
        return copy

    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: node.update(shift_end="later")),
        "Service: shift_end has an unknown choice.",
    )
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: node.update(staffing_on="yes")),
        "Service: staffing_on must be true or false.",
    )
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: node.update(priority={"t9": 1})),
        "names a customer type the file does not have",
    )
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: whole["edges"][0].update(types=["t9"])),
        "A route names a customer type the file does not have.",
    )
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: whole["types"][0].update(id='t1" x="')),
        "Every customer type id must be",
    )
    # Type ids are object keys, so a prototype name is refused too.
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: whole["types"][0].update(id="__proto__")),
        "Every customer type id must be t followed by digits",
    )
    # A version 2 file without a feature's switch is refused, not read as off.
    refuse_file(
        page,
        tmp_path,
        changed(lambda whole, node: node.pop("staffing_on")),
        "Service: the file has no staffing_on.",
    )


def test_builder_writes_long_typed_routes_as_ruff_formats_them(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    page.click("#add-type")
    page.fill("#type-name-t1", "Walk-in customers from the north entrance")
    source = add_node(
        page,
        kind="source",
        name="Customers arriving at the north entrance",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    page.fill("#field-mix-t1", "1")
    triage = add_node(page, kind="station", name="Triage station number one")
    routine = add_node(page, kind="station", name="Routine station alpha wing")
    special = add_node(page, kind="station", name="Specialist room b")
    panel_route(page, source, triage)
    panel_route(page, triage, routine)
    panel_route(page, triage, special)
    for target in (routine, special):
        set_edge_types(page, triage, target, ["t1"])
        panel_route(page, target, "exit")
    assert "No problems found" in problems_text(page)
    code = page.locator("#code").text_content()
    # Too long for one line, so ruff puts one argument per line.
    assert (
        "model.branch(\n"
        "    triage_station_number_one,\n"
        "    {routine_station_alpha_wing: 0.5, specialist_room_b: 0.5},\n"
        '    types=["Walk-in customers from the north entrance"],\n'
        ")\n"
    ) in code
    # run_script fails unless ruff format leaves the script unchanged.
    run_script(code, tmp_path, monkeypatch)


def test_builder_puts_a_branch_on_one_indented_line_when_it_fits(
    tmp_path, engine_page, monkeypatch
):
    page = open_builder(tmp_path, engine_page)
    source = add_node(
        page,
        kind="source",
        name="In",
        durations={"interarrival": ("constant", {"value": 1})},
    )
    triage = add_node(page, kind="station", name="Triage station number one")
    routine = add_node(page, kind="station", name="Routine station alpha")
    special = add_node(page, kind="station", name="Specialist room")
    panel_route(page, source, triage)
    panel_route(page, triage, routine)
    panel_route(page, triage, special)
    for target in (routine, special):
        panel_route(page, target, "exit")
    code = page.locator("#code").text_content()
    # The flat call is 91 characters, and its arguments fit in 4 + 78 = 82.
    assert (
        "model.branch(\n"
        "    triage_station_number_one, {routine_station_alpha: 0.5, specialist_room: 0.5}\n"
        ")\n"
    ) in code
    run_script(code, tmp_path, monkeypatch)
