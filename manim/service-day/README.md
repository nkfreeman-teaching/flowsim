# FlowSim: staffing a service day

A five-part teaching video. The continuous video is `output/ServiceDay.mp4`, and the deck is
`output/deck/ServiceDay.html` (both rebuilt by `pixi run render service-day final` from the
`manim/` folder, after `pixi run python manim/service-day/capture.py` from the project root).

| Scene | Part | Starts at slide | Source |
|---|---|---|---|
| `Part1Predict` | Reads the two-stage network's distributions and predicts the bottleneck from offered load per server | 1 | `examples/models.py`, README "Classroom exercise" |
| `Part2Day` | Shows day 1's Service queue with one and with two servers from the saved viewers | 11 | `snippets/exercise.py` |
| `Part3Targets` | States the wait and overtime targets from the exercise's constants | 15 | `examples/service_day.py`, README "Classroom exercise" |
| `Part4Compare` | Compares 1 to 3 servers over 20 days against the wait target and the overtime limit | 20 | `examples/service_day.py` (`staffing_exercise`) |
| `Part5Decide` | Reads the decision table, picks the lowest staffing that meets both targets, and shows a stricter what-if | 29 | `snippets/exercise.py` |

The deck has 32 slides. The slide numbers change if a part gains or loses a break. Every displayed number is
asserted against the sources above when the module is imported.

## Plan

Profile: teaching. The viewer knows basic queueing words but has never seen FlowSim, and
may not have watched the flowsim-core video, so the terms it grounds are grounded again
here in one clause each. The owner set this plan in the session brief and asked that it be
recorded here rather than approved before the build.

### Grounding

| Term on screen | Plain-language definition | Source | First part |
|---|---|---|---|
| station, server, source | A station is a set of parallel servers with one waiting line; a source creates customers | README "A first model" | 1 |
| `lambda rng:` | A function FlowSim calls with the run's random generator to draw each time (arrival gaps average 3 minutes all day) | examples/models.py | 1 |
| `service_capacity` | The argument that sets the Service station's number of servers | examples/models.py | 1 |
| offered load | Arrival rate times mean service time, divided by the number of servers | README "Classroom exercise" | 1 |
| bottleneck | The station with the highest offered load per server, i.e., the busiest one | README "Classroom exercise" ("predict the bottleneck") | 1 |
| viewer | The saved web page FlowSim writes for one run or a comparison | README "Getting started" | 2 |
| simulated day, `staffing_exercise`, `runs[0]` | One replication of 480 operating minutes; the exercise runs 20 per staffing level, and `runs[0]` is day 1 | examples/service_day.py | 2 |
| total wait | A customer's waits at both stations added together | README metric table | 3 |
| overtime | The time after closing needed to finish every customer | README "Measurement rules" | 3 |
| target | An adjustable teaching threshold, not a service standard | README "Classroom exercise" | 3 |
| scenario, `compare`, seed | One staffing level; compare runs each on the same seeds | README "Replications and scenario comparisons" | 4 |
| 95% confidence interval (CI) | The mean across days plus or minus a Student t multiple of its standard error | README "Replications" | 4 |
| decision table | The exercise's table of each level's wait interval, on-time days, and target check | examples/service_day.py | 5 |

### Parts

Numbers come from `captured/numbers.json`, which `capture.py` writes by running
`snippets/exercise.py`; `service_day.py` asserts each one as listed.

| Scene | Shows | Numbers and their check | Breaks |
|---|---|---|---|
| `Part1Predict` | The two-stage network drawn and read from `service_network`, then a bar chart of offered load per server | interarrival mean 3, check-in 1 to 2, service mean 4 (parsed from `examples/models.py`); loads 1/2, 4/3, 2/3, 4/9 (computed, with 4/3 and 2/3 asserted against README "Classroom exercise"); the bottleneck by level (computed) | after the network, each distribution, the load definition, and each staffing level |
| `Part2Day` | Day 1's Service queue with one and two servers, from the saved viewers | maximum queue and overtime for day 1 (captured, asserted equal to the per-run tables and the day's overtime) | after the code and each chart |
| `Part3Targets` | The exercise constants in `examples/service_day.py` and two target cards | 20 days, 480 minutes, 5 minutes, 30 minutes, 90%, 18 of 20 (parsed, and asserted against the README) | after each target |
| `Part4Compare` | `staffing_exercise`'s `compare` call, a drawn interval chart of mean total wait against the 5-minute target, a strip of each day's overtime against the 30-minute limit, and the saved overtime viewer | each level's mean and 95% limits (recomputed from the 20 day values with t = 2.093 and asserted against the decision table); on-time day counts (recounted and asserted) | after the code, each chart step, and the viewer |
| `Part5Decide` | The decision table as Polars displays it, and the chosen level | the choice and its numbers (recomputed from the targets and asserted against `meets_targets`) | after the table, the choice, and the scope note |

Decisions taken in the plan: Part 2 (one simulated day) was added after the first preview, so a viewer sees one day's queue before the 20-day summaries. Part 5 adds a what-if with a 2-minute wait target to show that the targets drive the choice. Part 1 adds the three-server case to the README's two loads,
because the computed loads show check-in becoming the bottleneck at three servers, which
explains why three servers still run past closing on some days.

## Review

Codex (gpt-6.1-sol at high effort, from `~/.codex/config.toml`; job `task-mvmj5z0r-l2dxye`)
ran one read-only pass on 2026-10-24 over the first final render, at HEAD 8c05354 plus the
untracked `manim/` tree. It reported opening all 62 final contact sheets. Each finding below
was checked against the scene code, the captured JSON, the README, or `flowsim/` before its
disposition. Finding numbers are Codex's. Findings 1, 2, and 46 span all four videos.

| # | Finding | Disposition |
|---|---|---|
| 1 | A long formula caption gets about 3.5 s in the MP4, since reading-time holds were off. | Accepted. `CodeScene` in `shared/flowsim_video.py` now sets `cps = 17`, so a break holds until a caption has had its length ÷ 17 seconds on screen. This lengthens every video. |
| 2 | Intervals are not explained in every video (machining never says 20 shifts). | Accepted for service-day and machining-line, whose first interval captions now say what the whiskers are and over how many runs. flowsim-core already defines the interval (Part 5), and supply-chain labels its row "Simulated, 20 runs" and gives "95% CI" in the caption. |
| 46 | Grounding-table part numbers disagree with the caption order. | Accepted. The tables were corrected in place. |
| 16 | The Part 2 code panel uses `comparison` before showing where it comes from. | Accepted. `snippets/exercise.py` was reordered so the panel starts at `comparison, decision = staffing_exercise()`. The capture was rerun, since the snippet's hash changed. |
| 17 | "It clears 116 minutes after closing" mixes up the line and the system. | Accepted after checking that overtime is end time minus duration (`flowsim/results.py`). The caption now says everyone is served 116 minutes after closing. |
| 18 | Station and source go undefined, offered load is used before its definition, and the seed is unexplained. | Accepted. The opening caption defines source and station, the offered-load definition now comes before the bottleneck definition, and the compare caption defines a seed. |
| 19 | The "Above 1" caption restates the previous one. | Accepted. It now adds that the line grows until arrivals stop at closing. |
| 20 | The 0 to 100 minute scale squashes the two- and three-server intervals. | Accepted. A zoomed chart of those two levels against the 5-minute target follows the full-scale chart. |
| 21 | The on-time caption reads the count labels. | Accepted. It now says the target counts on-time days, not mean overtime. |
| 22 | The stricter what-if sits beside the original table's `meets_targets`. | Accepted. The table fades out before the what-if box appears. |
| R1 S2 | All of the inputs in the three applied videos and the core extension tour are written as lambda rng: rng.<distribution>(...). | Accepted. One gloss at the first lambda in each video (core Part 5 now shows service_network, service-day Part 1, machining Part 1 new saw-time beat, supply-chain Part 1 demand caption). Shares the core fix with P1. |
| R1 S6 | The student has never seen Polars. | Accepted in part. Core Part 3 gains one caption glossing shape, i64, and f64. Rejected for service-day and machining, whose captions never read the type row; a gloss there costs every viewer time for a row the video does not use. |
| R1 S11 | The code shows comparison, decision = staffing_exercise() and comparison.experiments[name].runs[0] two parts before staffing_exercise and compare are introduced (Part 4, :360). | Accepted. Part 2 caption-01 now says staffing_exercise runs 20 days per level and that the runs[0] viewer marks closing; Part 3 unchanged. |
| R1 S12 | No caption names a first target. | Accepted. 'The second target' became 'The overtime target'. |
| R1 S13 | "Probability bound" is jargon this reader does not have, so the scope point is lost. | Accepted. Reworded to 'a count from these runs, not a probability for future days', which keeps README:115's scope. |
| R1 S14 | "CI" is never expanded in these 3 standalone videos, which breaks the abbreviation obligation. | Accepted. Expanded at first use in service-day, machining, and supply-chain; settled decision on supply-chain interval wording kept (no re-definition). Same as I10, P8, C6. |
| R1 S15 | A student can read "Service, 2" as a second Service station or as stage 2, not as Service with 2 servers. | Accepted. Labels read 'Service, 1 server' to 'Service, 3 servers'. Same as I22. |
| R1 S16 | The target box says "mean total wait" and the table column says mean_wait_minutes. | Accepted. Decision boxes now say 'mean total wait'. |
| R1 I10 | Each video stands alone, and "CI" is never expanded in the service-day, machining, or supply-chain videos, which breaks the acronym obligation. | Accepted. CI expansion as S14; machining Part 3 and Part 4 output means now at one decimal. |
| R1 I21 | The dashed closing line is needed to read "116 minutes after closing" on the first chart, but it is explained only on the second chart. | Accepted. Explained in Part 2 caption-01; the end caption keeps only the axis note. |
| R1 I22 | The bar labels read as names of three stations rather than as server counts. | Accepted. Same fix as S15. |
| R1 P8 | The service-day and machining videos use 'CI' without ever expanding it, although each must stand alone. | Accepted. Core HTML and CSV expanded; CI as S14. |
| R1 P9 | Part 4 caption-09 argues from the intervals ('both intervals sit below the 5-minute target'), but meets_targets compares the point mean with 5 (examples/service_day.py:58-60). | Accepted. Caption names the mean wait and on-time days as the compared statistics. The method question stays with the owner (P1-Q1). |
| R1 P10 | The screenshot appears with no code, although snippets/exercise.py already holds comparison.viewer(path=..., metric="overtime"). | Accepted in part. Caption names the call; the code panel was not added, since the screenshot would have to shrink. |
| R1 P11 | The staffing decision rests on a constant arrival rate all day (exponential scale=3 in service_network). | Accepted. Caption adds 'all day'. |
| R1 P12 | The network has two stations, and neither the chart titles nor the captions say which station's line is plotted. | Accepted. Chart titles name the Service line. |
| R1 C6 | Service-day and machining-line introduce CI without expanding it in their standalone videos. | Accepted. Same fix as S14. |
| R2 S1 | Each of these three standalone videos uses "the viewer" with no gloss. | Accepted in part. Service-day says 'Day 1's saved web page', machining 'A saved viewer page', supply-chain names brewing.viewer (from snippets/capacity.py) in the caption; no code panel added over the screenshot. |
| R2 S13 | The reference line shares its hue with the One-server dots and whiskers. | Accepted. Reference lines drawn in MUTED. Same as P11. |
| R2 S15 | The Polars type row and shape line are glossed only in the core video. | Rejected. NOTE with no repair obligation; R1 S6's decision stands. |
| R2 I4 | The column holds mean total wait (3.239704, the same value as core Part 6 total wait). | Accepted. Caption says mean total wait. Same as P2; caused by the R1 P9 fix. |
| R2 P2 | The target is mean total wait. | Accepted. Same fix as I4. |
| R2 P11 | The reference line reads as part of the One server series. | Accepted. Same fix as S13. |

After these changes, `check` passed for all four videos, every part was re-rendered at final quality, the final sheets were read again, and `check_deck.py` was rerun.

Rows marked R1 and R2 come from rounds 1 and 2 of the review loop in `review-loop/2026-10-24-flowsim-teaching-videos/` (snapshots a6e233f0cd1d and b951369bd929), whose ids are the reviewers' (S student, I instructor, P practitioner, C Codex correctness). The loop's `progress.md` records each verification.
