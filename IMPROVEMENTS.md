# FlowSim improvement tracker

This file tracks the verified and agreed changes from the code review of 2026-10-23, and it is
deleted when every item is done, deferred, or rejected (AGENTS.md keeps one README). The review
covered commit `e9ac3aa`. Three reviewers read the whole repository independently (Claude Opus 5.5,
Claude Sonnet 5.5, and Codex `gpt-6.1-sol` at high effort), and the code-health static suite ran
alongside them. The main session reproduced 11 findings by experiment and checked the rest against
the cited lines. No finding was dropped as wrong, and eight were deferred or rejected with reasons
(see the last table). "Checked" in an item means the main session ran or read it, and a named
reviewer means that reviewer ran it. The owner settled four decisions on
2026-10-23 (items 2.1 to 2.4).

Status values are `open`, `in progress`, `done (<commit>)`, `deferred`, and `rejected`. Update the
status in the same commit as the change.

## How to run a block

Each block is one fresh session, except Block 4, which may need two. Work the blocks in order,
because Block 2 changes seeded outputs and Block 4's refactors are checked against Block 2's
outputs.

1. On the unchanged tree, record the baseline: the test count from `pixi run test`, and the hashes
   of every example CSV.

   ```bash
   pixi run examples
   find output -name '*.csv' -print0 | sort -z | xargs -0 sha256sum > /tmp/flowsim-before.sha
   ```

   The 77 CSVs hashed identically across two runs at `e9ac3aa`, so any difference is real.
2. Make the change, and add the hand-calculated test its item names.
3. Run `pixi run check` and `pixi run examples`, then hash again and `diff` against the baseline.
   The diff must be empty unless the item's "Outputs" field states the expected change. The test
   count must not fall.
4. Commit by path, one item or one tight group per commit, with this file's status updated.

## Block 1: correctness and the lesson display

| # | Change | Where | Found by | Outputs | Status |
|---|---|---|---|---|---|
| 1.1 | Lesson viewers replaced by Marimo size warnings | `pyproject.toml`, `pixi.toml` | Codex | Lesson display only | done (f581522) |
| 1.2 | Decimal times leave a tiny remainder that pauses finished work | `flowsim/station.py:94-108` | Opus | Yes, rare runs | done (aeb84a2) |
| 1.3 | A non-advancing failure and repair cycle hangs the run | `flowsim/station.py:110-151`, `engine.py:105-124` | Codex | Error instead of hang | done (7366e30) |
| 1.4 | Make "shift changes first" an explicit priority and fix the tie-order wording | `scheduler.py`, `engine.py:18-23`, `station.py:173-180`, README, AGENTS.md | Opus, Sonnet | None expected | done (de9689a) |
| 1.5 | Add the missing tie-order and shared-admission tests | `tests/`, README | Sonnet, Opus | None | done (7569926) |
| 1.6 | Give validation tests a `match` | `tests/test_extensions.py:483`, `:503` | Opus | None | done |

**1.1.** Both `mo.iframe(html=results.viewer())` cells (`examples/lesson.py:129-134`, `:348-353`)
exceed Marimo's default output limit of 8,000,000 bytes, so students see a warning in place of
each viewer. Checked: `output/lesson.html` contains "too large for marimo to show" for outputs of
11,777,456 and 11,592,576 bytes. The raw viewer is about 4.9 MB, of which plotly.js is 4,815,765
bytes, and Marimo's iframe encoding roughly doubles it, so trimming the data payload cannot fix
this. Fix: add `[tool.marimo.runtime] output_max_bytes = 30_000_000` to `pyproject.toml`. If
`marimo export` ignores the pyproject setting, set `MARIMO_OUTPUT_MAX_BYTES` in the
`notebook-export` and `notebook` tasks instead. Then make `pixi run examples` fail when
`output/lesson.html` contains "too large for marimo", so this cannot regress silently. Expect the
exported lesson to grow from about 210 KB to roughly 24 MB. Rejected alternative: loading plotly.js
from a CDN, which breaks offline viewing.

**1.2.** `count_down` computes the remainder as `remaining - (now - started)`. Checked: an arrival
at 0.1 with service 0.2 and `staffing=[(0, 1), (0.3, 0), (5, 1)]`, `shift_end="pause"`, gives
`service_end` 5.0 with a paused span from 0.3 to 5.0, because 0.1 + 0.2 is 0.30000000000000004. By
hand the service ends at 0.3. The whole-number version (1, 2, shift at 3) is correct. Fix: keep
`deadline = started + remaining` and set `remaining = deadline - now` after each wake. Treat the
work as finished when the deadline is at most `math.nextafter(now, math.inf)`, i.e., when it is
now or the next representable time. (The first proposal, `now + remaining == now`, fails this
test, because the deadline 0.30000000000000004 is one representable time after the shift change
at 0.3.) This test needs no tolerance constant, and it also covers failure lifetimes. Keep creating one new
timeout per wake as now (see deferred item D1), so event sequence numbers do not change. Test: the
decimal model above, expecting `service_end == 0.3` and no paused activity. Outputs (owner accepted
2026-10-23): the finishing rule changes no example, but the deadline arithmetic moves the
repairing-machine example by one rounding step, in a service resumed after a failure (customer 31,
2.8e-14 earlier) and the next service on that server.

**1.3.** Checked: `time_to_failure=1e-100`, `repair_time=0`, `failure_clock="available"` hangs
`run()` (stopped by a 10-second alarm), with or without a staffing schedule. Each failure and
repair lands on the same timestamp forever. Fix: in `_Server.failures`, raise a `ValueError` naming
the station and server when a whole failure and repair cycle leaves the clock unchanged. This
follows the existing interarrival guard at `engine.py:284-288`. A single tiny random lifetime
followed by a positive repair stays valid. Test: the model above raises with a clear message.
Extended (owner decision 2026-10-23): without a schedule the machine starts at 0, where each cycle
moves the clock by 1e-100 and the same-timestamp check never fires (120,423 cycles in 3 seconds
reached 1.2e-95). The interarrival guard had the same gap for `interarrival=1e-100` from time 0.
Both guards now also raise when the cycle or the interarrival cannot advance the clock from the
run's duration, i.e., `duration + gap == duration`.
Pain: Codex rated it 4, and the main session rates it 2, because it needs a lifetime below clock
resolution and a zero repair together. Treated as 4 until resolved, since a hang in class gives no
feedback at all.

**1.4.** Shift changes share NORMAL priority with completions, and they run first at equal times
only because every shift timeout is queued when the station is built (`station.py:174-175`).
Checked: `engine.py:18-21` says these events "use the scheduler's NORMAL priority", while AGENTS.md
says priorities set the order. Fix (adjudicated, see Disagreements): renumber so that `URGENT=0`,
`SHIFT_PRIORITY=1`, `NORMAL=2`, `ARRIVAL_PRIORITY=3`, `SETTLED_PRIORITY=4`, and pass
`priority=SHIFT_PRIORITY` at `station.py:177`. Reword README lines 338-342, the AGENTS.md bullet,
and the engine comment as "shift changes first; then completions, transfers, failures, and
repairs in the order they were scheduled; then arrivals; then drain checks". Outputs: none
expected, because priorities do not change sequence numbers and shifts already win these ties. The
CSV hash diff must be empty.

**1.5.** Add hand-calculated tests built from `tests/models.py` or inline: (a) a shift start
versus an arrival at the same instant (`staffing=[(0, 0), (5, 1)]`, `buffer=0`, reject, arrival at
5, expect completed); (b) a repair end versus an arrival (`time_to_failure=1`, `repair_time=2`,
arrival at 3, `buffer=0`, expect completed); (c) outside arrivals and blocked upstream transfers
competing for one `buffer=0, external_overflow="wait"` station. Both kinds share one `pending`
deque in request order (`station.py:226`, `:281`), so also add one README sentence saying so.

**1.6.** The two parametrized validation tests call `pytest.raises(ValueError)` without `match`,
so 12 cases pass on the wrong error. Add the expected message fragment to each case.

## Block 2: approved output changes, then a seeded-output tripwire

| # | Change | Where | Found by | Outputs | Status |
|---|---|---|---|---|---|
| 2.1 | Key random streams by node name | `flowsim/engine.py:50-61`, README | Opus, Sonnet | Every seeded run, once | open |
| 2.2 | List stations in model definition order | `flowsim/engine.py:62-72` | Sonnet | Row order | open |
| 2.3 | Rename `in_service_*` to `occupied_*` and relabel plots | `results.py:299-301`, `plots.py:132`, `viewer.html`, README | Opus, Sonnet | Column names | open |
| 2.4 | Add `measurement_rejected` and `measurement_admitted` | `results.py:356-424`, `METRICS`, README | Opus | New columns | open |
| 2.5 | Add two station columns missing from `METRICS` | `results.py:89-119`, README | Opus | Accepts two metrics | open |
| 2.6 | Remove the unused paused-area accumulator | `results.py:253-276` | Codex | None | open |
| 2.7 | Give empty interval tables their columns | `results.py:149-158` | Sonnet | Empty frame gains columns | open |
| 2.8 | Store staffing levels as integers | `schedules.py:45`, `station.py:159`, `:177` | Opus | `metadata.json` levels | open |
| 2.9 | Pin seeded outputs with a tripwire test | `tests/` | Opus, Sonnet | None | open |

**2.1 (owner approved).** Checked by both Claude reviewers: inserting a station named "Aaa" changes
the first arrivals of an unrelated source (seed 7 gave `[3.59, 3.80, 10.27, 19.10]` before and
`[1.84, 4.47, 4.98, 9.03]` after). Fix: derive each node's seeds from
`np.random.SeedSequence(entropy=seed, spawn_key=(zlib.crc32(name.encode()), purpose))`, with one
purpose each for durations, routing, and servers, and per-server children spawned from the server
key. Raise if two names in one model share a CRC. Update README lines 410-412 and 458-461, retire
the "same records as SimPy 4.1.2" sentences (`scheduler.py:7-8`, README 552-553) in favor of "was
checked against SimPy 4.1.2 at commit `32e96d3`", and regenerate `output/`. Rejected: Python's
`hash(name)`, which changes per process.

**2.2 (owner approved).** Checked: `branching_service()` defines Triage, Routine, Specialist, but
the station table lists Routine, Specialist, Triage, because `sorted(model._nodes)` also orders
`self.stations` and `self.histories`. Fix: iterate `model._nodes` in definition order when building
stations (after 2.1, sorting is no longer needed for seeds). Re-check tests that index row 0 of a
multi-station frame.

**2.3 (owner approved).** Checked: an upstream server holding a blocked customer reports
`in_service_at_close` 1 with `blocked_at_close` 1, because the column copies `busy`. Rename the
columns to `occupied_at_close` and `occupied_at_end`, the queue plot trace and the viewer heading to
"Occupied servers", and update README 350-353 and `tests/test_simulation.py:54`.

**2.4 (owner approved).** Checked: `single_station(buffer=0, external_overflow="reject")` run with
`duration=4, warmup=2.5, drain=True` reports `rejected` 2 and `admitted` 1, with
`measurement_arrivals` 0. Keep the whole-run columns (the README identity
`arrivals = completed + remaining + rejected` depends on them), add the two post-warm-up counts to
`_system_metrics` and `METRICS`, and state each window in the README table. Test: that model by
hand.

**2.5.** `mean_scheduled_servers` and `mean_outside_queue` are station columns but not `METRICS`
entries, so `intervals()` rejects them. Add them with kinds "servers" and "customers", plus README
rows.

**2.6.** `areas["paused"]` is accumulated for every state interval and never read. Remove it from
the accumulator. Item 4.10 rewrites this code later, so keep the change small.

**2.7.** Checked: a model with no stations returns a `(0, 0)` frame from `intervals()`. Give
`interval_frame` the full schema (`station`, `metric`, `runs`, `observed_runs`, `mean`, `lower`,
`upper`, `confidence`, and `scenario` and `baseline` where used).

**2.8.** `validate_schedule` stores count levels as `float(value)`, and the station converts them
back with `int(...)`. Store `int` when `counts=True` and drop the conversions.

**2.9.** Nothing pins seeded output today. After 2.1 to 2.8, add one test that pins hand-copied
literals for `service_network().run(duration=480, seed=42)`: customer count, the first three
arrival times, and two summary metrics, documented as an intentional tripwire. Block 4 relies on
it. Adjudicated: hand-copied literals (Sonnet's proposal) over a saved CSV snapshot (Opus's), since
literals survive polars formatting changes.

## Block 3: experiments and comparisons

| # | Change | Where | Found by | Outputs | Status |
|---|---|---|---|---|---|
| 3.1 | `Experiment` accepts runs from different models | `results.py:505-531`, `engine.py` | Codex, Sonnet | Mixed runs now raise | open |
| 3.2 | Build `Experiment` tables from its runs on access | `results.py:532-564`, tests | Sonnet | None | open |
| 3.3 | Share the settings check and metadata writer | `results.py`, `comparison.py` | Opus | Error text only | open |

**3.1.** Checked: `Experiment([...])` pooled a service-time-1 model and a service-time-9 model as
two replications and reported a mean wait of 4.0. The settings tuple compares only duration,
warm-up, drain, time unit, and capacities. Fix: have `_Run` give `Results` a private definition key
built from every node's settings and routes, with callables compared by identity, and require equal
keys in `Experiment`. Runs of one `Model` object always match. Two separately built models with
different lambdas are refused, which is the safe direction. Test: the two-model case raises.

**3.2.** `Experiment.stations` and `.summary` are copies made in `__init__`, and tests mutate them
(`tests/test_service_day.py:257`, `:285-291`, `:448`) to reach the missing-replication guard in
`_values`. Make both properties over `self.runs`, move those tests to patch `run.summary`, and
remove the guard if it becomes unreachable.

**3.3.** `results.py:518-531` and `comparison.py:37-47` each define a `settings()` tuple, both
check station existence, and both write `metadata.json` with their own version stamp. Add one
`_run_settings(run)` and one `_write_metadata(path, data)` helper in `results.py`, and drop the
duplicate station check from `Comparison._values`.

## Block 4: typed records and module structure

Every item here must leave the CSV hash diff empty, except 4.10, which is compared with a relative
tolerance of 1e-12.

| # | Change | Where | Found by | Status |
|---|---|---|---|---|
| 4.1 | Replace dict records with slotted dataclasses, and test record fields against schemas | `engine.py`, `station.py`, `results.py` | Opus, Sonnet | open |
| 4.2 | Replace status and phase strings with `StrEnum` | `engine.py`, `station.py`, `results.py` | Sonnet | open |
| 4.3 | Split `Node.duration` into interarrival and service time, and name the stream pair | `model.py`, `engine.py`, `station.py` | Opus, Sonnet | open |
| 4.4 | Add read-only `Model` accessors and precompute routing once per run | `model.py`, `engine.py`, `plots.py`, tests | Opus, Sonnet | open |
| 4.5 | Move `number`, `integer`, `sample` to a leaf module and hoist local imports | new `flowsim/validation.py`, all modules | Sonnet | open |
| 4.6 | Document `_Station` and `_Server`, and share one future-staffing helper | `station.py:154-348` | Sonnet, suite | open |
| 4.7 | Remove the unreachable "arriving" status | `engine.py:155` | Opus, Sonnet | open |
| 4.8 | Drop the redundant limit clause in the source loop | `engine.py:129-139` | Sonnet | open |
| 4.9 | Compute station state in one pass, and count outside tickets with a counter | `station.py:193-204` | Opus, Codex | open |
| 4.10 | Compute time-weighted station areas in polars and split the count metrics out | `results.py:246-354` | Opus, Sonnet | open |
| 4.11 | Expand calls to the keyword layout rule in touched files | all touched files | Codex | open |

Notes. For 4.1, a polars frame silently nulls a misspelled key (Opus checked: a row with `exit_tme`
gave `exit_time == [None]` with no error), so the dataclasses and a field-equals-schema test close
the gap. `Results.__init__` (16 parameters, suite CX1) may take one run-record object if that falls
out naturally. For 4.4, normalize probabilities once so the same draws are consumed. For 4.5,
plotly is loaded on `import flowsim` already (checked: `comparison.py` imports `flowsim.plots` at
the top), so the lazy plot imports save nothing. For 4.6, `settled_drain_check` has cyclomatic
complexity 18, and its two searches for future staffing differ only in the level they need. For
4.9, Opus measured `observe` at 1.96 s of a 5.83 s run (10,000 customers, 5 stations), and the main
session measured the outside-queue count at 0.26 s for 4,000 customers waiting outside. Neither
matters for a classroom day, so this item is for clarity first. For 4.11, the rule is the owner's
global one: a call with three or more arguments, or two or more keywords, goes one keyword argument
per line with a trailing comma (e.g., `Metric("system", "Mean total waiting time", "time")`).

## Block 5: plots, viewer, docs, and examples

| # | Change | Where | Found by | Status |
|---|---|---|---|---|
| 5.1 | Select viewer traces by station metadata instead of fixed counts | `plots.py:126-303`, `viewer.html:214-221` | All three | open |
| 5.2 | Build each customer timeline once, in Python | `plots.py:306-375`, `viewer.html:223-275` | Opus, Sonnet | open |
| 5.3 | Move the comparison page to a template file | `comparison.py:276-335` | Sonnet | open |
| 5.4 | Fix README and message drift | README, `model.py:24`, `:259`, `:301` | Opus, Sonnet | open |
| 5.5 | Derive example labels and constants from one place | `examples/`, `tests/test_examples.py:40` | Opus, Sonnet | open |
| 5.6 | Round-trip every exported CSV in the export test | `tests/test_simulation.py:361-377` | Sonnet | open |
| 5.7 | Reword the AGENTS.md test-model rule | `AGENTS.md` | Sonnet | open (owner approved) |

**5.1.** The viewer JS hard-codes `Math.floor(i / 2)` and `Math.floor(i / 6)` (`viewer.html:217`,
`:220`), which repeat the trace counts in `plots.py`. Set `meta=station` on each trace and select by
it in Python's `updatemenus` and in the JS, with one shared button helper.

**5.2.** Checked by reading: the JS draws "In service" from visit times when a customer has no
activity rows (`viewer.html:250-255`), but `customer_plot` draws nothing, so the two disagree for
zero-length service. Add one Python function that returns timeline spans, use it in
`customer_plot`, and embed the spans in the viewer payload so the JS only draws them. Also rename
the loop variable `label` at `plots.py:323`, which hides the module's `label()` function.
Adjudicated: Opus's single-source design over Sonnet's keep-both-plus-parity-test.

**5.3.** `Comparison.viewer` builds a 30-line f-string page with its own CSS, while `Results.viewer`
uses `flowsim/viewer.html`. Move it to `flowsim/comparison.html` using the same placeholder scheme,
and add it to package data.

**5.4.** Add `resource_plot()` to the README's figure list (as a note, since `test_readme` runs the
first-model block). Change "The prototype supports acyclic routes only." to "FlowSim supports
acyclic routes only." Change the `number()` docstring to "Require a finite nonnegative scalar".
Add one README line on the different defaults of `Experiment.intervals` (`mean_wait`, every
station) and `Comparison.intervals` (`mean_total_wait`, one station).

**5.5.** `examples/service_day.py:44` takes the server count from `enumerate`, so reordering the
scenarios would mislabel them. Build the scenarios from `{n: ...}` and carry `n` with each row.
Import `WAIT_TARGET` and `ON_TIME_SHARE` in `tests/test_examples.py` in place of the literals 5 and
3, and put example durations in one table used by `extensions.main()` and the lesson.

**5.6.** Extend the export round trip to `failures.csv` (a run with an unfinished repair, so
`repair_end` is null), `activities.csv`, and `states.csv`, using the schema constants.

**5.7 (owner approved 2026-10-23).** AGENTS.md says library tests build models from `tests/models.py`, but
about 20 tests build small one-off models inline, and that reads better for a hand calculation.
Reword to "Library tests never import from `examples/`. Shared models live in
`tests/models.py`, and one-off hand-calculation models may be built inline."

## Deferred and rejected

| # | Finding | Found by | Disposition and reason |
|---|---|---|---|
| D1 | `count_down` leaves stale timeouts in the heap, and shift changes pulse every server | Sonnet | Deferred. Pain 1: the heap held 6,239 entries for 4,767 customers. Reusing timeouts changes sequence numbers and therefore tie order, so revisit only with a measured need. |
| D2 | Send the viewer payload column-wise | Sonnet | Deferred. plotly.js is 4.8 MB of a 4.9 MB classroom viewer, so this does not fix 1.1 and helps only for days near 10,000 customers. |
| R1 | Keep running per-station counters for large capacities | Sonnet | Rejected. The reviewer recommended no fix (0.44 s at 2 servers, 2.11 s at 200). |
| R2 | Validate once per experiment instead of per replication | Sonnet | Rejected. The cost is negligible, and a private no-validation run path would be a second entry point. |
| R3 | `branching_service` duplicated in `tests/models.py` and `examples/models.py` (suite DUP1) | Suite | Rejected. AGENTS.md requires test models separate from examples. |
| R4 | Exact float equality in six tests (suite DC6) | Suite | Rejected. The expected values (0.5, 0.75, 1.5, 12.5) are exact binary results of integer arithmetic, so exact equality is the stricter, correct check. |
| R5 | `Model.station` has 11 parameters (suite CX1) | Suite | Rejected. They are keyword-only student-facing options, and grouping them would change the public call. |
| R6 | Two long tests exceed cyclomatic 15 (suite CX1) | Suite | Rejected. Each walks one hand calculation, which splitting would scatter. |

## Disagreements

- **Shift-change priority (1.4).** Opus proposed an explicit shift priority, and Sonnet proposed
  rewording the docs only, out of concern that new tiers change sequence numbers. Adjudicated for
  Opus plus Sonnet's wording, because priorities leave sequence numbers unchanged, and the CSV hash
  check enforces "no output change".
- **Failure-cycle hang (1.3).** Codex rated pain 4, and the main session rates 2. Treated as 4.
- **Customer timeline (5.2).** Opus proposed one Python source, and Sonnet proposed keeping both
  versions with a parity test. Adjudicated for Opus.
- **Tripwire form (2.9).** Opus proposed a saved CSV reference, and Sonnet proposed hand-copied
  literals. Adjudicated for Sonnet.
- **Seeding (2.1).** Sonnet recommended the change outright, and Opus recommended it only if the
  owner accepts a one-time change in every seeded result. The owner approved it.
