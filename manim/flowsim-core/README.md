# FlowSim: the core workflow

A seven-part teaching video. The continuous video is `output/FlowsimCore.mp4`, and the deck
is `output/deck/FlowsimCore.html` (both rebuilt by `pixi run render flowsim-core final` from
the `manim/` folder, after `pixi run python manim/flowsim-core/capture.py` from the project
root).

| Scene | Part | Starts at slide | Source |
|---|---|---|---|
| `Part1Model` | Builds the deterministic queue (title "A model in five calls") from `Model()`, a source, a station, and a route, then runs it | 1 | `examples/models.py` (`deterministic_queue`), `snippets/queue.py` |
| `Part2Hand` | Times the three customers by hand on a Gantt chart, then draws the waiting line and the busy server | 10 | README "For maintainers" |
| `Part3Tables` | Shows the customers, visits, stations, and summary tables as Polars displays them, and matches them to the hand values | 16 | `snippets/queue.py`, README "Results" |
| `Part4Viewer` | Shows the saved offline viewer (station table, queue chart, customer 3's timeline) and the exported files | 23 | `snippets/queue.py`, README "Results" |
| `Part5Replications` | Runs 20 days of the two-stage network and builds a 95% confidence interval for the Service mean wait | 30 | `snippets/replications.py`, README "Replications and scenario comparisons" |
| `Part6Compare` | Compares one, two, and three Service servers on common seeds, with paired differences against two servers and the comparison viewer | 38 | `snippets/compare.py`, README same section |
| `Part7Extensions` | Tours branches, types, schedules, buffers, priorities and patience, failures, and stock points through README blocks | 48 | README "Model features" |

The deck has 62 slides. The slide numbers change if a part gains or loses a break. Every displayed number is
asserted against the sources above when the module is imported.

## Plan

Profile: teaching. The viewer is a student or instructor who knows basic queueing words
(arrival, server, waiting line) but has never seen FlowSim. The owner set this plan in the
session brief and asked that it be recorded here rather than approved before the build.

### Grounding

| Term on screen | Plain-language definition | Source | First part |
|---|---|---|---|
| model, `Model()` | The container for one simulated system's sources, stations, and routes | README "A first model" | 1 |
| source | Where customers enter; it creates one customer per interarrival time | README "A first model" | 1 |
| interarrival time | The time between one arrival and the next | README "A first model" | 1 |
| station | A set of identical parallel servers with one waiting line | README intro | 1 |
| capacity | The number of servers at a station | README "Demand and staffing schedules" | 1 |
| route, `model.exit` | The order of stations a customer visits, ending at the exit | README "A first model" | 1 |
| duration | The minutes the run admits arrivals and serves customers | README "Measurement rules" | 1 |
| seed | The number that fixes every random draw, so a rerun repeats the run | README "Replications" | 1 |
| first come, first served | Customers start service in the order they joined the line | AGENTS.md, README "Scope and limits" | 2 |
| wait | Time from joining a station's line to starting service | README "Measurement rules" | 2 |
| mean queue | The time-average number of customers waiting (queue area over time) | README "Measurement rules" | 2 |
| utilization | The share of installed server time that is occupied | README "Measurement rules" | 2 |
| flow time | Time from arrival to exit | README "Replications" metric table | 3 |
| customers, visits, stations, summary tables | One row per customer, per station visit, per station, and per run | README "Results" export table | 3 |
| `shape`, `i64`, `f64` | The Polars display's row and column count, and its whole-number and decimal column types | Polars display | 3 |
| throughput | Exits per minute during operating hours | README metric table | 3 |
| offline viewer | One hypertext markup language (HTML) page that carries its data and plotting library, so it opens without internet | README "Getting started" | 4 |
| export, CSV, `metadata.json` | The tables written as comma-separated values (CSV) files, plus the run settings | README "Results" | 4 |
| 95th percentile wait | The 0.95 quantile of the sorted waits, interpolated linearly between neighbors, so waits 0, 1, and 2 give 1.9 (a column in the viewer's station table) | README metric table, flowsim/results.py | 4 |
| `lambda rng:`, `scale` | A function FlowSim calls with the run's random generator to draw each time; NumPy's exponential `scale` is a mean | README "A first model", examples/models.py | 5 |
| replication | One independent run with its own random draws, i.e., one simulated day here | README "Replications" | 5 |
| `drain=True` | Keep serving after closing until every admitted customer finishes | README "Measurement rules" | 5 |
| 95% confidence interval | The mean across runs plus or minus a Student t multiple of its standard error | README "Replications" | 5 |
| warm-up | An opening stretch left out of the averages; zero in this video | README "Measurement rules" | 4 |
| scenario, `compare` | One named version of the model; compare runs each with the same seeds | README "Replications and scenario comparisons" | 6 |
| paired difference | A scenario's value minus the baseline's within the same replication | README same section | 6 |
| branch | Sends each customer to one destination with fixed probabilities | README "Branches and shared stations" | 7 |
| customer type | A label each arrival draws, which service times and routes may depend on | README "Customer types" | 7 |
| schedule, `staffing`, `shift_end` | A list of (time, value) pairs for arrival rates per minute or staffed servers, and what an off-duty server does | README "Demand and staffing schedules" | 7 |
| buffer, blocking | A cap on the waiting line, and a finished job holding its server because the next line is full | README "Finite buffers and blocking" | 7 |
| priority, patience, abandonment | A rank among types in the line that never interrupts service, and how long a customer waits before leaving unserved; abandoned and rejected customers are left out of the mean wait | README "Priorities and abandonment" | 7 |
| failure clock, repair | When `time_to_failure` runs down (`"available"`: up time on shift, idle or busy, plus finishing a customer after the shift), and the downtime before it works again | README "Failures and repair" | 7 |
| stock point, lead time, backorder | A stage that holds inventory, fills orders from stock, and reorders each period; the delay from the supplier's shipment to receipt; an unfilled order that waits for new stock | README "Inventory and ordering" | 7 |

### Parts

Numbers come from `captured/numbers.json`, which `capture.py` writes by running the snippet
files and README blocks; `flowsim_core.py` asserts each one as listed.

| Scene | Shows | Numbers and their check | Breaks |
|---|---|---|---|
| `Part1Model` | The deterministic queue built call by call from `examples/models.py`, beside a drawn network, then `model.run` from `snippets/queue.py` | arrivals 0, 1, 2 and service 2 (parsed from `deterministic_queue`); duration 7 (parsed from the snippet) | after the network, the source, the station, the route, and the run |
| `Part2Hand` | A hand Gantt chart of three customers, the waiting-line step chart, and the busy server bar | waits 0, 1, 2; queue area 3 over 7 minutes; busy 6 of 7 (recomputed, then asserted against README "For maintainers" and the captured run) | after arrivals, service, waits, the queue, and utilization |
| `Part3Tables` | The four tables as Polars displays them, each with its `select` code | waits, flow times, mean queue 3/7, utilization 6/7, throughput 3/7 (captured, asserted equal to the hand values) | one per table, and at the match |
| `Part4Viewer` | `viewer` and `export` code, then viewer screenshots (station table, queue chart, customer 3's timeline) and the exported file list | customer 3's flow time 4 (captured, asserted against the hand chart) | one per screenshot |
| `Part5Replications` | `experiment` code, a dot plot of the 20 days' Service mean waits, and the interval table | 20 runs, the mean and 95% limits for Service and for Check-in, which the interval table also shows (recomputed from the 20 run values with t = 2.093 and asserted against the library) | after the code, the dots, the interval, and the scope note |
| `Part6Compare` | `compare` code, the scenario means, the paired differences against Two servers, and the saved comparison viewer | scenario means and paired differences with limits (recomputed from per-day values and asserted); baseline parsed from the snippet and asserted against the capture; same seeds in every scenario (asserted); unpaired half-width 0.74 (two-sample t with 38 degrees of freedom, t = 2.024) against paired 0.63 (asserted narrower) | after the code, the means, the differences, the shared days, the two widths, and the viewer |
| `Part7Extensions` | One README excerpt per extension (branches, types, schedules, buffers, priorities and abandonment, failures, stock points), each from a block that `capture.py` runs | none | one per extension, and the closing rule |

Decisions taken in the plan: the hand-timing part comes before the tables so the tables
confirm a calculation the viewer already did; the extension tour quotes the README's own
blocks rather than new code, so every excerpt is code that the README test also runs.

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
| 3 | `failure_clock="available"` gloss says "whenever the server is up", but the clock also needs the server on shift or finishing its last job. | Accepted after checking `_Server.available` in `flowsim/station.py`. The caption now says the server must be up and on shift or finishing its last job. |
| 4 | The tour names behavior arguments without explaining the shown values, and stock-point terms go undefined. | Accepted. Captions now explain `shift_end="finish"`, `"reject"`, and `abandon_from="waiting"`, and a second stock-point beat defines lead time and backorders. |
| 5 | "Steady state" is undefined for this audience. | Accepted. The caption now says the interval covers 480-minute days that start empty, not long-run behavior. |
| 6 | The viewer's station table shows a 95th percentile wait before percentiles are explained. | Accepted. A new Part 4 beat defines the 95th percentile wait. |
| 7 | "Up to 3" can read as minute 3. | Accepted. The caption now says the source stops after 3 customers. |
| 8 | The server caption repeats the table. | Accepted after checking `_Station` in `flowsim/station.py`, which numbers servers 1 to capacity per station. The caption now says server numbers are within each station. |
| 9 | The queue-chart caption restates the legend. | Accepted. The caption now points to the range slider under the chart. |
| 10 | The timeline caption restates the bars. | Rejected. The screenshot is the chart alone, without the viewer's flow-time text, so the caption ties the bars to the hand-calculated 4 minutes from Part 2. |
| 11 | "Each dot is one day's mean wait" repeats the axis labels. | Accepted. The caption now adds that the interval weights every day equally. |
| 12 | "The same limits for each station" suggests identical limits. | Accepted. The caption now says one row per station. |
| 13 | The means-read caption only reads the table. | Rejected. It points the viewer to the two rows the comparison turns on, and the equal-weighting fact Codex proposed is now in Part 5 (finding 11). |
| 14 | The pairing caption repeats the same-seeds caption. | Accepted. It now says a negative difference means less waiting than with one server. |
| 15 | The closing caption restates the one before it. | Accepted. The beat was removed, and the part ends on the behavior-argument caption. |
| R1 S1 | The viewer table under this caption shows a 95th percentile wait of 1.9 for the hand-timed waits 0, 1, and 2. | Accepted. Caption now states the interpolation and the 1.9; P95_WAIT recomputed and asserted in the module. Same root cause as I2, P3, C2. |
| R1 S2 | All of the inputs in the three applied videos and the core extension tour are written as lambda rng: rng.<distribution>(...). | Accepted. One gloss at the first lambda in each video (core Part 5 now shows service_network, service-day Part 1, machining Part 1 new saw-time beat, supply-chain Part 1 demand caption). Shares the core fix with P1. |
| R1 S5 | "The interval" is used while only dots are on screen. | Accepted. Merged with I1 and I7 wording. |
| R1 S6 | The student has never seen Polars. | Accepted in part. Core Part 3 gains one caption glossing shape, i64, and f64. Rejected for service-day and machining, whose captions never read the type row; a gloss there costs every viewer time for a row the video does not use. |
| R1 S7 | The excerpt starts inside deterministic_queue, and the def line is never shown. | Rejected. Adding the def line to the first panel would not place the value beside capacity=capacity in the second panel, so it adds a line without fixing the gap. |
| R1 S8 | The file list shows activities.csv, failures.csv, and states.csv, 3 tables the video never introduced. | Accepted. Caption says all 7 tables (count computed from the captured file list). Merged with P8's CSV expansion. |
| R1 S9 | "Lifetime" is never defined. | Accepted. Caption now names time_to_failure and keeps the finishing-job case from first-pass finding 3; merged with I5. |
| R1 S10 | The code shows rates=[(0, 0.2), (90, 0.6), (300, 0.2)] and staffing=[(0, 1), (90, 3), ...]. | Accepted. Caption lists (time, value) pairs with the per-minute rate unit; merged with P7. |
| R1 I1 | The band runs the full width of a plot of the 20 single days. | Accepted. Caption says the band is not a range for single days; drops 'It widens as days vary more'. |
| R1 I2 | The station table on screen shows a 95th percentile wait of 1.9 for the hand-timed waits 0, 1, and 2. | Accepted. Same fix as S1. |
| R1 I4 | The caption appears while the stock-point code is still on screen, and the bottom strip then lights all seven extension names. | Accepted. Strip now inks only the four extensions; caption reads 'Four of these extensions require ...'. |
| R1 I5 | At 114 characters and 6.7 s this is the longest caption in the core video. | Accepted. S9 wording used, which keeps the README's finishing-job case that I5 would drop. |
| R1 I6 | The caption never says whether priority preempts service. | Accepted. Caption adds 'without preempting service' (asserted against README). |
| R1 I7 | "The interval" is used before any interval has been drawn or named. | Accepted. Caption: 'Each dot is one day's mean wait, and every day counts equally.' |
| R1 I8 | The model on screen is the deterministic queue, which has no random draws. | Accepted. Caption reads seed=42 (parsed from the snippet) and 'any random draws'. |
| R1 I9 | Captions are set in serif text, so captions that open on a lowercase table name (customers, visits, stations, summary) read as grammar slips rather than identifiers. | Accepted. Four captions now open on results.customers, results.visits, results.stations, results.summary. |
| R1 I23 | Labels are centered by bounding box, so words with descenders ride about 4 px high. | Accepted. Strip and Gantt legend arrange with aligned_edge=UP. |
| R1 P1 | The core workflow video never opens service_network, the model behind its interval and comparison results. | Accepted. Part 5 swaps in the service_network excerpt at the random beat, highlights the exponential(scale=4) line, and states scale as a mean (asserted), then restores the snippet panel. |
| R1 P3 | The station table directly below shows a 95th percentile wait of 1.9 for waits 0, 1, and 2, so one customer in three exceeds it. | Accepted. Same fix as S1. |
| R1 P4 | Neither caption says that comparison.intervals() defaults to mean_total_wait or that differences() defaults to the first listed scenario (flowsim/comparison.py:123, :37). | Accepted. Both captions now name the default metric and baseline, asserted by parsing comparison.py. |
| R1 P5 | The closing card names each argument but not its choices, so a practitioner sees one value per argument and never learns its alternative. | Accepted in part. Each box now lists its allowed values (parsed from flowsim/model.py and asserted). The fifth stock-point box is deferred with S1-Q2, since it broadens what the closing card claims. |
| R1 P6 | The tour never says that rejected and abandoned customers are excluded from wait and flow averages. | Accepted. New Part 7 beat: 'Abandoned and rejected customers are left out of the mean wait.' |
| R1 P7 | The excerpt shows rates=[(0, 0.2), (90, 0.6), (300, 0.2)] and a six-pair staffing list, but no caption says how to read a pair or what unit a rate has. | Accepted. Same fix as S10. |
| R1 P8 | The service-day and machining videos use 'CI' without ever expanding it, although each must stand alone. | Accepted. Core HTML and CSV expanded; CI as S14. |
| R1 C2 | The displayed percentile is 1.9, but only two of the three waits, 0, 1, and 2, do not exceed it. | Accepted. Same fix as S1. |
| R1 C4 | This wording can be read as time from ordering to receipt. | Accepted. Caption: 'lead_time runs from the supplier's shipment to receipt.' Grounding row updated. |
| R2 S2 | The video's last held frame adds four values ("pause", "wait", "waiting_and_outside", "busy") that no caption ever explains. | Accepted. Boxes now show the value the tour explained (asserted against the README excerpts and flowsim/model.py) and are titled Staffing, Buffers, Patience, Failures. Merged with I8. Practitioner R1 P5 asked for the alternatives; student and instructor now find them unexplained. Treated at the higher concern, i.e., no unexplained values on the held frame. |
| R2 S3 | "Preempting" is scheduling jargon outside the named undergraduate vocabulary, and the clause that was added to state the rule depends on it. | Accepted. 'Lower ranks go first but never interrupt service.' Same as C4. |
| R2 S4 | "Counts equally" has nothing to count toward. | Accepted. Student's paste-ready wording used. |
| R2 S11 | The core video calls everyone a customer for six parts, and then "job" appears undefined. | Accepted. Captions say customer instead of job (shift_end, blocking, failure clock). |
| R2 S12 | Both excerpts cut off the def line, so the parameter's value is invisible. | Accepted in part. Part 5's service_network excerpt now starts with its def line (service_capacity: int = 2). Part 1 rejected again for R1 S7's reason. |
| R2 I2 | The final frame shows Two servers and Three servers, each as a difference from One server, and the two intervals overlap almost completely (-87.8 to -63.0 and -90.2 to -64.8). | Accepted. Caption adds 'Both rows compare with One server, not with each other.' The re-pairing question stays with the owner. |
| R2 I5 | 'It' follows a caption about experiment.intervals, so its referent is unclear. | Accepted. 'The interval covers days that start empty, not long-run behavior.' Must-survive scope kept. |
| R2 I6 | The grounding table defines the 95% CI as the mean plus or minus a Student t multiple of its standard error, but no frame in the core video says how the interval is built. | Accepted. 'experiment.intervals reports these Student t limits by station.' |
| R2 I7 | README:492-494 says the clock 'advances while a server is up and scheduled'. | Accepted. Merged with C1: 'counts up time on shift, idle or busy. It also counts finishing a customer after the shift.' |
| R2 I8 | The box says schedules need shift_end, but README:313 says 'The shift rule is required with staffing', and arrival-rate schedules do not need it. | Accepted. Merged with S2. |
| R2 I14 | '3 over 7 minutes, i.e., 3/7' is a fact followed by its restatement, and the 3 has no unit. | Accepted. 'Mean queue is the time-average line length, here 3/7.' The chart keeps the area label. |
| R2 I15 | The next caption ('server_id says which server took a visit...') restates 'names its server'. | Accepted. 'results.visits has one row per station visit.' |
| R2 I16 | Customer 2 waits from minute 1 to 2 and customer 3 from minute 2 to 4. | Accepted. 'The waiting line holds one customer at a time, minutes 1 to 4.' |
| R2 I19 | The part shows five calls: Model(), model.source, model.station, model.route, and model.run. | Accepted. Title 'A model in five calls'. |
| R2 P1 | A practitioner's real staffing question is two servers against three (3.2 vs 1.1 minutes), but the video only pairs against the overloaded one-server case. | Accepted. Caption adds 'baseline= names another.' |
| R2 P9 | The highlighted "reject" on the downstream station suggests that Finishing rejects Assembly's jobs. | Accepted. Band now covers buffer=0 only. |
| R2 C1 | The definition includes ordinary off-shift idle time. | Accepted. Same fix as I7. |
| R2 C3 | HTML remains unexpanded, and the CSV expansion omits "values". | Accepted. 'hypertext markup language (HTML)' and 'comma-separated values (CSV)'. |
| R2 C4 | The new qualification correctly states the behavior but introduces "preempting" without a gloss for the undergraduate audience. | Accepted. Same fix as S3. |

| Owner | Pair against Two servers rather than One server, where pairing barely narrowed the interval (I1-Q1, P1-Q4, I2-Q1). | Done. `snippets/compare.py` sets `baseline="Two servers"` for `differences` and the viewer; Part 6 reads the third server's −2.1 minutes (95% CI −2.8 to −1.5) and states the unpaired and paired half-widths, 0.74 and 0.63. |
| Owner | Record the Check-in interval that the waits table shows (C1-Q1). | Done. `capture.py` records Check-in's runs and interval, and the module asserts them. |
| Owner | The timeline's rotated "Station" title touched its tick label (I1-Q3). | Done in `flowsim/viewer.html` (`automargin` and a 12-pixel standoff), then recaptured. |

After the round 2 changes, `check` passed for all four videos, every part was re-rendered at final quality, the final sheets were read again, and `check_deck.py` was rerun. The owner rows were answered after the loop; their check renders passed, and the closing checkpoint read them.

Rows marked R1 and R2 come from rounds 1 and 2 of the review loop in `review-loop/2026-10-24-flowsim-teaching-videos/` (snapshots a6e233f0cd1d and b951369bd929), whose ids are the reviewers' (S student, I instructor, P practitioner, C Codex correctness). The loop's `progress.md` records each verification.
