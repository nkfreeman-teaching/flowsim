# FlowSim: modeling a machining line

A four-part teaching video. The continuous video is `output/MachiningLine.mp4`, and the
deck is `output/deck/MachiningLine.html` (both rebuilt by `pixi run render machining-line
final` from the `manim/` folder, after `pixi run python manim/machining-line/capture.py`
from the project root).

| Scene | Part | Starts at slide | Source |
|---|---|---|---|
| `Part1Line` | Draws the five-station line (plus a source) and reads the blank release and the saw's zero buffer from the code | 1 | `examples/operations.py` (`machining_line`), README "Machining line" |
| `Part2Capacity` | Computes rough capacity per station, then adds the lunch staffing and the CNC failures, with the saved viewer's resource charts | 11 | `examples/operations.py`, `snippets/line.py` |
| `Part3Buffers` | Compares the buffer plans by parts per shift and by CNC blocking, with the relocation and paired gains tables | 22 | `examples/operations.py` (`BUFFER_PLANS`, `line_study`), `snippets/line.py` |
| `Part4Failures` | Adds the no-failure scenario, the CNC down share, and the saved comparison viewer | 30 | `snippets/line.py`, README "Machining line" |

The deck has 34 slides. The slide numbers change if a part gains or loses a break. Every displayed number is
asserted against the sources above when the module is imported.

## Plan

Profile: teaching. The viewer knows basic queueing words but has never seen FlowSim. The
owner set this plan in the session brief and asked that it be recorded here rather than
approved before the build.

### Grounding

| Term on screen | Plain-language definition | Source | First part |
|---|---|---|---|
| station, server, CNC | A set of identical machines or workers with one waiting line; CNC (computer numerical control) is automated cutting | README "A first model", examples/operations.py | 1 |
| blank, release, customer | A raw part, and the time it enters the system; FlowSim calls each blank a customer | examples/operations.py docstring | 1 |
| `lambda rng:` | A function FlowSim calls with the run's random generator to draw each time (the saw takes 2.5 to 3.5 minutes) | examples/operations.py | 1 |
| buffer | The waiting spaces in front of a station, apart from its servers | README "Finite buffers and blocking" | 1 |
| `external_overflow="wait"`, raw stock | Released blanks that find the saw busy wait outside the line | README "Machining line" | 1 |
| saturated | The line never runs out of blanks, so its output measures one shift's output from an empty line | README "Machining line" | 1 |
| `completed_at_close` | Parts finished by the end of the 480-minute shift, starting from an empty line | README metric table | 1 |
| rough capacity | Shift minutes times average servers divided by mean minutes per part, ignoring variability and blocking | computed here, not stated in the README | 2 |
| bottleneck | The station with the lowest rough capacity | README "Machining line" | 2 |
| viewer | The saved web page FlowSim writes for one run or a comparison | README "Getting started" | 2 |
| staffing, lunch | The scheduled fitters, which drop from two to one from minute 240 to 300 | examples/operations.py | 2 |
| failure, repair, `failure_clock="busy"` | A machine breaks after a sampled amount of cutting time (90 minutes on average) and is down for a sampled repair (10 to 30 minutes, 20 on average), with no shared repair crew | README "Failures and repair" | 2 |
| blocking | A finished part holds its machine because the next buffer is full | README "Finite buffers and blocking" | 1 |
| blocked share, machine time | The fraction of machine time (2 CNC machines × 480 minutes) spent blocked | README "Measurement rules" | 3 |
| scenario, paired difference, 95% confidence interval (CI) | One buffer plan; a plan's output minus another plan's on the same shift (the no-buffer plan, or two each for the relocation); the interval across 20 such shifts | README "Replications and scenario comparisons" | 3 |
| down share | The fraction of machine time spent broken down, under the two-each plan | README "Measurement rules" | 4 |

### Parts

Numbers come from `captured/numbers.json`, which `capture.py` writes by running
`snippets/line.py` (which calls `line_study`); `machining_line.py` asserts each one as listed.

| Scene | Shows | Numbers and their check | Breaks |
|---|---|---|---|
| `Part1Line` | The five-station line (plus a source) drawn, and the blanks source and saw read from `machining_line` | release every 2 minutes, saw buffer 0 (parsed from `examples/operations.py`); 240 blanks per shift (computed); saw occupied all shift (captured utilization, asserted at least 0.999); one routing with no rework (README "every blank follows the same routing" and "rework loops are not implemented", and one `route` call with no `branch` in `machining_line`) | after the line, the station, the routing, the release, the buffer, raw stock, and the output measure |
| `Part2Capacity` | A bar chart of rough capacity per station, then the lunch staffing and the CNC failures read from the code, with the saved viewer's resource charts | each station's mean time (parsed); 1.875 average fitters (computed from the staffing list and asserted against the captured `mean_scheduled_servers`); CNC 6 × (1 + 20/90) minutes per part and about 131 parts (computed); the CNC chart's minutes 250 to 400 (set in `capture.py` and read from the capture) | after the chart, lunch, the fitters chart, each failure step, the CNC chart, the lunch-adjusted chart, and the CNC cost |
| `Part3Buffers` | `BUFFER_PLANS`, an interval chart of parts per shift by plan, the CNC blocked share by plan, and the paired gains table | plan means and 95% limits (recomputed from 20 runs and asserted); the gain over no buffers (paired, recomputed, asserted, and checked against README "more than ten"); the move to assembly (paired, recomputed, asserted against FlowSim's `differences(baseline="Two each")` table, and checked against README "less than one part"); CNC blocked share (mean of captured run values) | after the plans, blocking, each chart step, the relocation table, and the gains table |
| `Part4Failures` | The no-failure scenario added to the chart, the CNC down share, and the saved comparison viewer | the no-failure gain over two each (paired, recomputed, and checked against README "about as many parts again"); CNC down share (mean of captured run values) | after the added row, the comparison, the down share, and the viewer |

Decision taken in the plan: the rough capacity chart is this video's own hand calculation
from the model's mean times, labeled as rough on screen, since the README states the
bottleneck but not a capacity per station.

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
| 16 | The Part 3 code panel uses `comparison` before showing where it comes from. | Accepted. `snippets/line.py` was reordered so the panel starts at `comparison = line_study()`, and the capture was rerun. |
| 23 | "Real output falls below it" treats a mean-time estimate as a bound. | Accepted. The caption now says simulated output here falls below it, which the captured means confirm (the highest is 130.45 against 131). |
| 24 | Blank, CNC, station, blocking, and bottleneck are used before they are defined. | Accepted. Part 1 now defines blank, station, and CNC, and blocking moves from Part 3 to Part 1. The bottleneck caption names it as the station with the least capacity. |
| 25 | 1.875 should be called scheduled fitters, and `shift_end="finish"` goes unexplained. | Accepted in part. The caption now says scheduled fitters. The finish rule is left out, since the flowsim-core video explains it and the line has no room for another beat here. |
| 26 | The caption quotes a paired interval while the whiskers show separate intervals. | Accepted. The caption now gives only the mean gain, and the paired intervals appear with the `differences` table at the end of the part. |
| 27 | The 0.15-part relocation result has no uncertainty. | Accepted. The caption adds its paired 95% CI (−0.36 to 0.66), recomputed in the computation layer. |
| 28 | "Share of capacity" has no stated denominator, and 17% does not name its plan. | Accepted. Captions now say machine time is 2 machines × 480 minutes and that 17% is for the two-each plan. |
| 29 | "Buffers keep the CNC from blocking" contradicts the 4% blocked share. | Accepted. The caption now says buffers cut CNC blocking. |
| 30 | The plans caption repeats the source comment. | Accepted. A caption now states that both relocation plans hold 8 spaces (asserted from `BUFFER_PLANS`). |
| 45 | The plan calls it a six-station line. | Accepted. The README now says five stations plus a source. |
| R1 S2 | All of the inputs in the three applied videos and the core extension tour are written as lambda rng: rng.<distribution>(...). | Accepted. One gloss at the first lambda in each video (core Part 5 now shows service_network, service-day Part 1, machining Part 1 new saw-time beat, supply-chain Part 1 demand caption). Shares the core fix with P1. |
| R1 S3 | "Paired" is a grounding-table term (paired difference, Part 3). | Accepted. Applied in a shorter form: caption-07 now says the plans are paired on the same shifts, and caption-09 names the two-each baseline and that the interval spans zero (asserted). No new beat. Same root cause as P16, C10. |
| R1 S6 | The student has never seen Polars. | Accepted in part. Core Part 3 gains one caption glossing shape, i64, and f64. Rejected for service-day and machining, whose captions never read the type row; a gloss there costs every viewer time for a row the video does not use. |
| R1 S14 | "CI" is never expanded in these 3 standalone videos, which breaks the abbreviation obligation. | Accepted. Expanded at first use in service-day, machining, and supply-chain; settled decision on supply-chain interval wording kept (no re-definition). Same as I10, P8, C6. |
| R1 S17 | "Outside the line" does not say where the blanks wait or until when. | Accepted. Caption says blanks wait outside the line until the saw is free. |
| R1 S18 | The formula is given (shift minutes × servers ÷ mean minutes per part), but no station's mean minutes appear on screen except via assembly's uniform(5, 8). | Rejected. Fixed tick labels would contradict the bars that later change (lunch at 138, failures at 131). The operand the bottleneck verdict turns on (CNC's 6 minutes) is now in the caption (S19). |
| R1 S19 | The 6 (CNC mean minutes) is never stated. | Accepted. Caption names repairs per busy minute and the 6-minute CNC part; repair caption now gives the 20-minute mean. Merged with I20, P13, C9. |
| R1 S20 | The video says blanks and parts throughout, but the viewer axis says customers. | Rejected. Duplicate of P15, whose Part 1 caption now says each blank is one FlowSim customer; the axis label is library output (S1-Q1). |
| R1 I10 | Each video stands alone, and "CI" is never expanded in the service-day, machining, or supply-chain videos, which breaks the acronym obligation. | Accepted. CI expansion as S14; machining Part 3 and Part 4 output means now at one decimal. |
| R1 I19 | For three captions the yellow band points at a line of code the caption is not about. | Accepted. Band fades after the blocking caption appears. Covers P19. |
| R1 I20 | No caption or code panel ever states the CNC's 6-minute mean time, and 20 is the unstated mean of the 10-to-30-minute repair. | Accepted. Same fix as S19. |
| R1 I24 | "CNC failures cost about what the buffers add" rests on two paired point estimates whose intervals are not shown together. | Rejected. NOTE with no repair obligation; the 14.2 and 13.6 are paired means whose intervals the viewer shows. |
| R1 P8 | The service-day and machining videos use 'CI' without ever expanding it, although each must stand alone. | Accepted. Core HTML and CSV expanded; CI as S14. |
| R1 P13 | The 6 is CNC's mean cutting time (gamma(shape=4, scale=1.5)), but the CNC station is never shown and 6 never appears before this caption. | Accepted in part. Caption fix as S19; chart labels rejected for S18's reason. |
| R1 P14 | Each shift starts from an empty line (fresh state, no warm-up in line_study), so parts per shift include the time to fill a line whose first part needs about 21 minutes to reach pack. | Accepted. Caption adds 'from an empty line' and keeps the README's 'It measures capacity'. Answers the part of I1-Q2 inside the brief. |
| R1 P15 | FlowSim's own viewer labels parts as 'customers', and the video never says that FlowSim treats each part or job as a customer. | Accepted. Part 1 caption-01 says each blank is one FlowSim customer. |
| R1 P16 | 'Paired' is used two captions before caption-13 defines the pairing, which breaks order of exposition. | Accepted. Same fix as S3. |
| R1 P17 | These two shares answer a plant's main questions, but the video never names the stations-table columns that hold them (blocking_fraction and downtime_fraction, results.py:779 and machining_line.py:212). | Rejected. Identifier names would cost the student reader clarity in two captions that state the quantity in words; the stations table is in the README. |
| R1 P18 | The no-failure scenario removes every CNC failure. | Accepted. Caption: 'Ending every CNC failure adds about as much as the buffers.' |
| R1 P19 | The highlight points at a line that none of these three captions describes, so the visual cue tells the viewer the wrong thing. | Accepted. Fixed by clearing the band (I19) rather than moving it. |
| R1 C5 | The caption does not identify the downstream buffer. | Accepted. Codex's paste-ready wording used. |
| R1 C6 | Service-day and machining-line introduce CI without expanding it in their standalone videos. | Accepted. Same fix as S14. |
| R1 C7 | The phrase describes the operation but does not expand the acronym, despite the explicit first-use requirement. | Accepted. Caption expands computer numerical control. |
| R1 C9 | The 6-minute mean CNC cutting time has not been stated on screen, so the first operand in the capacity calculation is unexplained. | Accepted. Same fix as S19. |
| R1 C10 | Both videos use paired inference before explaining what is paired. | Accepted. Fixed by S3 and S24. |
| R1 C13 | The title uses a rhetorical question, and the closing caption uses figurative wording. | Accepted. Title 'The bottleneck'; closing as I18. |
| R2 S1 | Each of these three standalone videos uses "the viewer" with no gloss. | Accepted in part. Service-day says 'Day 1's saved web page', machining 'A saved viewer page', supply-chain names brewing.viewer (from snippets/capacity.py) in the caption; no code panel added over the screenshot. |
| R2 S5 | The video shows only the saw (2.5 to 3.5) and assembly (5 to 8) times before the bars. | Accepted. Each station's mean minutes now sit under its tick label (parsed STATIONS means, which do not change with lunch or failures), so R1 S18's objection to labels that the later bars contradict no longer applies. |
| R2 S6 | Part 3's closing table shows a scenario and a gain of 27.8 that Part 4 introduces only later. | Accepted in part. Fixed with P3's caption rather than moving the beat, which keeps the parts unchanged. |
| R2 S7 | "Spanning zero" states a fact about the interval without its reading. | Accepted. 'Against two each, the 95% CI is -0.36 to 0.66, so no clear difference.' |
| R2 S10 | No simulated output is on screen, so "here" points at nothing. | Accepted. Merged with I3. |
| R2 S15 | The Polars type row and shape line are glossed only in the core video. | Rejected. NOTE with no repair obligation; R1 S6's decision stands. |
| R2 I1 | This caption repeats caption-07 ('Both plans run the same shifts, so the gain is paired.'). | Accepted. Caption states the paired interval, merged with P3's last-row note; width inequality asserted at import. |
| R2 I3 | Each shift starts from an empty line, and the first part needs about 21 minutes to reach pack (README R1 P14). | Accepted. 'It ignores variability, blocking, and filling an empty line. Simulated output falls below it.' |
| R2 I9 | MOVE comes from the scene's own t_interval. | Rejected. A second differences call needs a snippet change and recapture after the last scored round, so its numbers would go unreviewed. Listed in the handback as a recommendation. |
| R2 I10 | At projection size you cannot see the black and green marks the caption points to. | Rejected. Cropping to minutes 250 to 400 needs a capture-side zoom or a pixel crop whose minute mapping is not known here. Listed in the handback. |
| R2 I11 | For three beats the panel illustrates none of these captions. | Accepted. The code panel and band clear when the blocking caption appears. |
| R2 I17 | The viewer under this caption plots 'Two each, no CNC failures' at 27.8 against No buffers, which is both gains combined. | Accepted. 'Ending all CNC failures too adds about as much again, 27.8 in all.' |
| R2 P3 | The gains table on screen has a third row, 'Two each, no CNC failures' at 27.8, which Part 4 only introduces later. | Accepted. Caption names the last row; merged with I1. |
| R2 P4 | README:494-495 says repairs run independently 'since there is no shared repair crew'. | Accepted. Caption adds 'There is no shared repair crew.' |
| R2 P5 | The screenshot is day 1 of the 'Two each' buffer plan (asserted at machining_line.py:216, from snippets/line.py). | Accepted. Caption says day 1 uses two buffer spaces each. |
| R2 P8 | This pair carries the video's main decision: buffers or maintenance. | Accepted. Interval added from NO_FAILURES, which is asserted against the README's 'about as many parts again'. |
| R2 P10 | Ragged baselines on axis labels look careless, which is the same defect I1-I23 fixed in the core video only. | Accepted. Tick labels and the amplification legend top-aligned; the job and ratio columns bottom-aligned. |
| R2 P12 | The ≈ glyph renders with a visibly double space on each side, unlike the source text. | Accepted. 'A 6-minute part costs 6 × (1 + 20/90), about 7.3 machine-minutes.' |

| Owner | completed_at_close "measures capacity" overstated it, since each shift starts empty (I1-Q2, I2-Q2). | Done. The caption says "It measures one shift's output from an empty line", and the project README now says the same. |
| Owner | State that every blank follows one routing with no scrap or rework (P2-Q2). | Done. A Part 1 caption, asserted against the README and the model code. |
| Owner | The relocation interval came from the scene's own t interval (R2 I9). | Done. `snippets/line.py` adds `differences(baseline="Two each")`; Part 3 shows its table, and the scene asserts its intervals against it. |
| Owner | The CNC resource chart was too dense to read (R2 I10). | Done. `capture.py` zooms it to minutes 250 to 400, and the caption names the window. |
| Owner | The comparison viewer called parts "customers" twice, in the label and in the unit (S1-Q1, P1-Q2, I1-Q3). | Done in part. `flowsim/results.py` now gives counts the unit "count"; the label keeps FlowSim's word "customers", which Part 1 defines as one blank. |

After the round 2 changes, `check` passed for all four videos, every part was re-rendered at final quality, the final sheets were read again, and `check_deck.py` was rerun. The owner rows were answered after the loop; their check renders passed, and the closing checkpoint read them.

Rows marked R1 and R2 come from rounds 1 and 2 of the review loop in `review-loop/2026-10-24-flowsim-teaching-videos/` (snapshots a6e233f0cd1d and b951369bd929), whose ids are the reviewers' (S student, I instructor, P practitioner, C Codex correctness). The loop's `progress.md` records each verification.
