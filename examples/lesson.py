import marimo

__generated_with = "0.25.1"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo
    from extensions import (
        DURATIONS,
        buffered_line,
        combined_line,
        peak_service,
        repairing_machine,
    )
    from models import branching_service, deterministic_queue, service_network
    from service_day import (
        DAYS,
        ON_TIME_SHARE,
        OVERTIME_LIMIT,
        WAIT_TARGET,
        staffing_exercise,
    )

    return (
        DAYS,
        DURATIONS,
        ON_TIME_SHARE,
        OVERTIME_LIMIT,
        WAIT_TARGET,
        branching_service,
        buffered_line,
        combined_line,
        deterministic_queue,
        mo,
        peak_service,
        repairing_machine,
        service_network,
        staffing_exercise,
    )


@app.cell
def _(mo):
    mo.md("""
    # Service networks with FlowSim

    The simulation package works in ordinary Python scripts. This notebook
    connects it to classroom controls and displays its outputs.

    Customers arrive, check in, receive service, and leave. The second
    station is the potential bottleneck. Increase its staffing and compare
    waiting, queue growth, and completed customers.
    """)
    return


@app.cell
def _(mo):
    servers = mo.ui.slider(
        start=1,
        stop=4,
        value=2,
        step=1,
        label="Service station servers",
        show_value=True,
    )
    run_length = mo.ui.slider(
        start=120,
        stop=960,
        value=480,
        step=120,
        label="Run length (minutes)",
        show_value=True,
    )
    seed = mo.ui.number(
        start=0,
        value=42,
        label="Random seed",
    )
    drain = mo.ui.checkbox(
        value=True,
        label="Finish serving customers after closing",
    )
    mo.hstack([servers, run_length, seed, drain])
    return drain, run_length, seed, servers


@app.cell
def _(mo, servers, service_network):
    network = service_network(service_capacity=int(servers.value))
    mo.ui.plotly(network.diagram())
    return (network,)


@app.cell
def _(drain, network, run_length, seed):
    results = network.run(
        duration=run_length.value,
        seed=int(seed.value),
        drain=drain.value,
    )
    return (results,)


@app.cell
def _(mo, results):
    mo.vstack(
        [
            mo.md("## Run totals"),
            mo.ui.table(results.summary),
            mo.md("## Station performance"),
            mo.ui.table(results.stations),
        ]
    )
    return


@app.cell
def _(mo, results):
    mo.md(f"""
    The run contains {results.customers.height} customer records and
    {results.visits.height} station visits. Flow-time averages include
    completed customers. Unfinished customers retain missing exit times.
    Operating-hour queue and utilization metrics stop at closing, even
    when service continues afterward. Closing backlog and overtime are separate.

    The viewer below has station selection, zoomable histories, customer
    timelines, status filters, and CSV downloads. The same viewer is
    available from a script through results.viewer("output/viewer.html").
    """)
    return


@app.cell
def _(mo, results):
    mo.iframe(
        html=results.viewer(),
        height="2300px",
    )
    return


@app.cell
def _(DAYS, ON_TIME_SHARE, OVERTIME_LIMIT, WAIT_TARGET, mo):
    import math as _math

    _required = _math.ceil(ON_TIME_SHARE * DAYS)
    mo.md(f"""
    ## Choose staffing for an eight-hour service day

    Customers arrive about every three minutes, spend one to two minutes
    checking in, and need four minutes of service on average. Check-in has
    one server. Compare one, two, and three service servers.

    Before running the comparison, identify the station that should become
    overloaded with one service server. Predict how staffing will change
    waiting, the closing queue, and time to finish after closing.

    Use {DAYS} simulated days per staffing level. The targets are a mean total
    wait of at most {WAIT_TARGET} minutes and completion within
    {OVERTIME_LIMIT} minutes after closing on at least {_required} of the
    {DAYS} days. Every admitted customer is served. Choose the lowest staffing
    that meets both observed targets. The comparison uses a fixed seed of 42,
    so the seed control above does not change it.
    """)
    return


@app.cell
def _(staffing_exercise):
    day_comparison, staffing_decision = staffing_exercise()
    return day_comparison, staffing_decision


@app.cell
def _(mo, staffing_decision):
    mo.ui.table(
        data=staffing_decision,
        label="Worked staffing comparison",
    )
    return


@app.cell
def _(day_comparison, mo):
    mo.ui.plotly(day_comparison.plot())
    return


@app.cell
def _(day_comparison, mo):
    mo.vstack(
        [
            mo.md(
                """
            Paired differences subtract the one-server result within each
            matched simulated day. Negative differences indicate shorter waits.
            These intervals estimate uncertainty in the finite-day statistic.
            The observed overtime count does not establish a 90% population probability.
            """
            ),
            mo.ui.plotly(day_comparison.plot(differences=True)),
        ]
    )
    return


@app.cell
def _(deterministic_queue, mo):
    _exact = deterministic_queue().run(duration=7)
    mo.vstack(
        [
            mo.md(
                """
            ## Check the arithmetic

            Three customers arrive at minutes 0, 1, and 2. One server takes
            two minutes per customer. Service starts at 0, 2, and 4, and
            finishes at 2, 4, and 6. Waits are 0, 1, and 2 minutes.
            Mean waiting time is 1 minute. The queue area is 3 customer-minutes,
            so its time average over seven minutes is 3/7. Utilization is 6/7.
            """
            ),
            mo.ui.table(_exact.visits),
            mo.ui.table(_exact.stations),
        ]
    )
    return


@app.cell
def _(branching_service, mo):
    _branch = branching_service()
    mo.vstack(
        [
            mo.md(
                """
            ## Route customers to different services

            Triage sends each customer to exactly one service. Routine service
            has a 70% routing probability, and specialist service has 30%.
            These probabilities do not guarantee exact proportions in a finite run.
            """
            ),
            mo.ui.plotly(_branch.diagram()),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Demand peaks, shifts, blocking, and repairs

    Compare the examples below. The service example has a demand peak and a
    lunch break. The production line holds upstream machines when downstream
    space is full. The machine example pauses work during independent repairs.
    The combined line includes changing demand, staffing, finite buffers, and failures.

    The extra resource chart separates processing, paused work, and blocked
    jobs. Occupied capacity alone does not measure productive work.
    Inspect rejected arrivals as well as wait averages. A short observed wait
    can accompany substantial rejection when waiting space is limited.
    """)
    return


@app.cell
def _(DURATIONS, mo):
    extension_choice = mo.ui.dropdown(
        options=list(DURATIONS),
        value="Combined line",
        label="Example system",
    )
    extension_seed = mo.ui.number(
        start=0,
        value=42,
        label="Random seed",
    )
    mo.hstack([extension_choice, extension_seed])
    return extension_choice, extension_seed


@app.cell
def _(extension_choice, mo):
    shift_choice = mo.ui.dropdown(
        options=["Finish current job", "Pause current job"],
        value="Finish current job",
        label="Work at the end of a shift",
        disabled=extension_choice.value not in {"Peak service", "Combined line"},
    )
    failure_choice = mo.ui.dropdown(
        options=["Elapsed available time", "Processing time only"],
        value="Elapsed available time",
        label="Failure clock",
        disabled=extension_choice.value not in {"Repairing machine", "Combined line"},
    )
    mo.hstack([shift_choice, failure_choice])
    return failure_choice, shift_choice


@app.cell
def _(
    DURATIONS,
    buffered_line,
    combined_line,
    extension_choice,
    failure_choice,
    peak_service,
    repairing_machine,
    shift_choice,
):
    _shift_policy = "finish" if shift_choice.value == "Finish current job" else "pause"
    _failure_clock = (
        "available" if failure_choice.value == "Elapsed available time" else "busy"
    )
    _models = {
        "Peak service": lambda: peak_service(shift_end=_shift_policy),
        "Buffered line": buffered_line,
        "Repairing machine": lambda: repairing_machine(failure_clock=_failure_clock),
        "Combined line": lambda: combined_line(
            shift_end=_shift_policy,
            failure_clock=_failure_clock,
        ),
    }
    extension_model = _models[extension_choice.value]()
    extension_duration = DURATIONS[extension_choice.value]
    return extension_duration, extension_model


@app.cell
def _(extension_duration, extension_model, extension_seed):
    extension_results = extension_model.run(
        duration=extension_duration,
        seed=int(extension_seed.value),
        drain=True,
    )
    return (extension_results,)


@app.cell
def _(extension_model, mo):
    mo.ui.plotly(extension_model.diagram())
    return


@app.cell
def _(extension_results, mo):
    mo.iframe(
        html=extension_results.viewer(),
        height="3000px",
    )
    return


if __name__ == "__main__":
    app.run()
