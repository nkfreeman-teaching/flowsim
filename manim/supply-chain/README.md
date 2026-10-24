# FlowSim: the bullwhip effect

A four-part teaching video. The continuous video is `output/SupplyChain.mp4`, and the deck
is `output/deck/SupplyChain.html` (both rebuilt by `pixi run render supply-chain final` from
the `manim/` folder, after `pixi run python manim/supply-chain/capture.py` from the project
root).

| Scene | Part | Starts at slide | Source |
|---|---|---|---|
| `Part1Chain` | Draws the four-stage chain with orders up and shipments down, then reads demand and the stock-point policy from `beer_game` | 1 | `examples/supply_chain.py`, README "Inventory and ordering" |
| `Part2Bullwhip` | Shows the first run's orders, compares the retailer's ratio with the closed form, and draws amplification by stage | 8 | `snippets/bullwhip.py`, README "Supply chain example" |
| `Part3Sharing` | Compares forecasting from orders with sharing consumer demand and a ten-week average, then the fill rates | 15 | `examples/supply_chain.py` (`bullwhip_study`), README "Supply chain example" |
| `Part4Capacity` | Replaces the factory's lead time with a brewhouse and compares fill rate, job time, and bullwhip ratio by capacity and cover | 24 | `snippets/capacity.py`, README "Supply chain example" and "Production at stations" |

The deck has 33 slides. The slide numbers change if a part gains or loses a break. Every displayed number is
asserted against the sources above when the module is imported.

## Plan

Profile: teaching. The viewer knows basic queueing words but has never seen FlowSim, and may
not know inventory terms, so each is grounded in the chain's own picture. The owner set this
plan in the session brief and asked that it be recorded here rather than approved before
the build.

### Grounding

| Term on screen | Plain-language definition | Source | First part |
|---|---|---|---|
| `model.supply` | The call that lists the chain in order, from consumers to the factory, with a one-week review period | examples/supply_chain.py | 1 |
| `lambda rng:` | A function FlowSim calls with the run's random generator to draw each week's demand | examples/supply_chain.py | 1 |
| stock point, stage | A stage that holds inventory, fills orders from stock, and orders from the stage above | README "Inventory and ordering" | 1 |
| beer game | The classroom chain of a retailer, wholesaler, distributor, and factory | README "Supply chain example" | 1 |
| review period | One week; each stage receives, ships, and orders once per week | README "Inventory and ordering" | 1 |
| lead time | Two weeks from a supplier's shipment to the stage's receipt | README "Supply chain example" | 1 |
| order-up-to, inventory position | Order the target minus the position, never below zero; position is stock on hand plus on order minus backorders | README "Inventory and ordering", flowsim/engine.py | 1 |
| moving-average forecast, cover | The mean of the last 5 weeks of incoming orders, and the weeks of demand a target covers | README "Inventory and ordering" | 1 |
| safety stock | Extra stock of one standard deviation of recent demand, scaled by the square root of cover | README "Inventory and ordering" | 1 |
| backorder, `shortage` | An unfilled order that waits and ships first when stock arrives (`shortage="backorder"`); `"lost"` drops it instead | README "Inventory and ordering" | 1 |
| warm-up | The first 20 weeks, left out of the stock-point measures because they hold the startup surge of orders | examples/supply_chain.py | 1 |
| variance | How widely weekly orders swing around their mean | general statistics term, glossed on screen | 2 |
| bullwhip ratio | A stage's order variance divided by the variance of the orders it receives | README "Inventory and ordering" | 2 |
| 95% confidence interval (CI), paired | The mean across 20 runs plus or minus a Student t multiple of its standard error; paired runs share their demand | README "Replications and scenario comparisons" | 2 |
| amplification | A stage's order variance divided by consumer demand variance, compounding the stages below | examples/supply_chain.py `amplification` | 2 |
| demand sharing (`forecast_from="end_demand"`) | Every stage forecasts from consumer demand instead of the orders it receives | README "Inventory and ordering" | 3 |
| fill rate | Cases filled in the week they arrive divided by cases demanded, over the measured weeks | README "Inventory and ordering", flowsim/results.py | 3 |
| brewhouse, batch, job | A production station; each order splits into jobs of up to 25 cases, with `service_time` in weeks per case, not per job | README "Production at stations" | 4 |
| viewer | The saved web page FlowSim writes for one run (`brewing.viewer`) | snippets/capacity.py | 4 |
| mean job time | Mean weeks from a job's release to its finish, waiting included | README "Production at stations" | 4 |

### Parts

Numbers come from `captured/numbers.json`, which `capture.py` writes by running
`snippets/bullwhip.py` and `snippets/capacity.py`; `supply_chain.py` asserts each one as
listed, and every result the README states is checked against the README's own digits.

| Scene | Shows | Numbers and their check | Breaks |
|---|---|---|---|
| `Part1Chain` | The chain drawn with orders up and shipments down, then `beer_game`'s demand and stock-point code | mean 100 and standard deviation 20, lead time 2, window 5, safety factor 1, 104 weeks, 20 weeks of warm-up (parsed from `examples/supply_chain.py`) | after the chain, demand, the stock point, the policy, and warm-up |
| `Part2Bullwhip` | The first run's orders chart from the supply viewer, then the retailer's ratio against the closed form, then amplification bars by stage | retailer ratio and 95% limits (recomputed from 20 runs, asserted against README 2.25, 2.18 to 2.32); closed form 1 + 2L/p + 2L²/p² = 2.12 (computed, asserted against README); amplification 2.2, 6.1, 16.1, 37.6 (recomputed, asserted against `amplification` and README 37.6) | after the chart, the definition, the closed form, and each stage |
| `Part3Sharing` | Amplification bars for the three scenarios, the factory ratio's paired difference, and the fill rates | 9.7 and 8.6 (recomputed, README); factory difference 0.89 (0.77 to 1.00) (paired, recomputed, README); retailer fill 87.0, 84.4, 91.4 and wholesaler fill 83.4, 77.9 (recomputed, README) | after each scenario, the difference, and each fill rate |
| `Part4Capacity` | `capacity_study`'s brewhouse code, the brewhouse queue from the saved viewer, an interval chart of factory fill rate by scenario, and the factory ratio and job time | fill 83.8 (82.4 to 85.3), 76.5, 88.3, 94.2, 97.1; ratio 2.32 in four scenarios and 2.76 (2.61 to 2.91) with cover 3; job time 2.29, 1.49, 0.92, 1.71 (each recomputed and asserted against README); identical factory orders across the four two-week-cover scenarios (asserted run by run) | after the code, the queue, each chart step, the ratio, and the closing finding |

Decision taken in the plan: Part 2 draws amplification bars rather than ratio bars, because
amplification shows the compounding the README reports (37.6 at the factory), while each
stage's own ratio stays between about 2 and 3.

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
| 31 | The stock-point, policy, and scenario excerpts are open fragments. | Accepted. Part 1 shows the whole 11-line `stock_point` call after clearing the chain, and Part 3 shows the whole `return compare(...)` statement. |
| 32 | The inventory position omits backorders. | Accepted after checking `flowsim/engine.py`, which computes on hand plus on order minus backorders. The caption now says so. |
| 33 | The shipments label also covers the consumer arrow. | Accepted. The label now reads "shipments between stages" and sits under the stage-to-stage arrows. |
| 34 | Backorder, moving average, and safety stock are not grounded. | Accepted. Captions now define backorders and say the forecast is the 5-week average of incoming orders and the safety stock is in their standard deviations. |
| 35 | "Every measure" and "nothing before it is measured" overstate the warm-up. | Accepted after checking that only stock-point measures use the window. Captions now say stock-point measures skip the warm-up and use weeks 20 to 103. |
| 36 | "Order over incoming variance" is ambiguous. | Accepted. The caption now says placed over received variance. |
| 37 | The 2.12 closed form is shown without its no-safety-stock condition. | Accepted in part. The captions now say the theory has no safety stock and the simulation does. The negative-order qualification is left to the README's own statement of it ("Inventory and ordering"), so the caption carries one condition. Whether the zero floor binds in this study was not checked. |
| 38 | The 0.89 own-ratio drop is captioned over the amplification chart. | Accepted. A separate chart of the factory's own bullwhip ratio for the two scenarios now carries that caption. |
| 39 | The fill-rate definition does not say it counts cases. | Accepted after checking `flowsim/results.py`, which divides cases filled by cases demanded. The caption now says incoming cases. |
| 40 | "Jobs of 25 cases" is false for the last job, and the per-case time is unexplained. | Accepted. The caption now says up to 25 cases and that a job takes 1/rate weeks per case. |
| 41 | "Job weeks" does not say release to finish. | Accepted. The column now reads "Job lead time", and the caption says from release to finish. |
| 42 | The 37.6 caption repeats the bar label. | Rejected. The caption states the README's headline finding in words, with its consumer-demand reference, which the bar alone does not give. |
| 43 | The shared-bars caption reads the labels. | Accepted. It now says sharing leaves the retailer unchanged because the retailer already sees consumer demand, which the computation layer asserts. |
| 44 | The retailer fill caption repeats labels. | Accepted. It now gives the reason, i.e., the supplier now plans from consumer demand. |
| R1 S2 | All of the inputs in the three applied videos and the core extension tour are written as lambda rng: rng.<distribution>(...). | Accepted. One gloss at the first lambda in each video (core Part 5 now shows service_network, service-day Part 1, machining Part 1 new saw-time beat, supply-chain Part 1 demand caption). Shares the core fix with P1. |
| R1 S4 | This reads as the ratio "is placed over" something. | Accepted. Caption now divides the variance of orders placed by that of orders received (README:596, asserted). Same as I3, P22, C1. |
| R1 S14 | "CI" is never expanded in these 3 standalone videos, which breaks the abbreviation obligation. | Accepted. Expanded at first use in service-day, machining, and supply-chain; settled decision on supply-chain interval wording kept (no re-definition). Same as I10, P8, C6. |
| R1 S21 | L and p are never named. | Accepted. Caption names lead time L and window p. Same as I11, C8. |
| R1 S22 | The source of √2 (the square root of the 2-week cover) is not given, and "their" has no clear referent. | Accepted. Caption adds that √2 comes from the 2-week cover. |
| R1 S23 | The caption defines position but does not say the policy orders the gap between the target and position. | Accepted. Merged with I14 wording. |
| R1 S24 | "Paired" is never defined in this standalone video. | Accepted. Caption says the pairing is on the same demand. Same as C10. |
| R1 S25 | The values 2.29, 1.49, 0.92, and 1.71 have no unit. | Accepted. Header is 'Mean job time (weeks)' on two lines. Same as C11. |
| R1 I3 | This caption defines the video's main metric, which is a must-survive grounding term, and it does not parse. | Accepted. Same fix as S4. |
| R1 I10 | Each video stands alone, and "CI" is never expanded in the service-day, machining, or supply-chain videos, which breaks the acronym obligation. | Accepted. CI expansion as S14; machining Part 3 and Part 4 output means now at one decimal. |
| R1 I11 | L and p are never named. | Accepted. Same fix as S21. |
| R1 I12 | The chart shows the startup spike near week 4, but nothing says why the warm-up is cut, which is the point an instructor makes about warm-up. | Accepted. Caption: 'The dashed line ends the warm-up, which holds the startup surge.' Part 1 still gives the 20-week warm-up. |
| R1 I13 | 8.6 has no unit. | Accepted. Caption says 8.6 times consumer demand variance. |
| R1 I14 | The caption defines "position" but never says how it enters the order (target minus position), and it does not use the grounding term "inventory position". | Accepted. Caption states the order quantity and names inventory position. |
| R1 I15 | "rate" is used before the next caption gives the brew rates (120, 150, 200 cases a week). | Accepted. Caption: 'brewed at a set rate per week'. |
| R1 I16 | The caption states the surprise without the mechanism the README gives (inventory position counts units on order, so receipts never change it). | Accepted. Caption: 'Position counts units on order, so factory orders do not change.' Covers P20. |
| R1 I17 | The deck stops on bare axes with six row labels and no data, which wastes a click. | Accepted. pause('fill') removed; the intervals build under the definition caption. |
| R1 I18 | "Buys" is a figurative verb, which the voice reference bans. | Accepted. Caption: 'raises the fill rate but makes orders more variable' (README sentence still asserted). Same as C13 second half. |
| R1 P2 | The video shows model.demand and model.stock_point, but never shows model.supply([consumers, *stages, factory], period=1), the one call that orders the stages into a chain and sets the weekly review. | Accepted. model.supply excerpt shown under the chain at the flows beat (lines parsed from beer_game); caption names it. |
| R1 P20 | Orders stay the same only because the factory's cover is fixed at two weeks and FlowSim does not adapt cover to the brewhouse's actual lead time (README 'Production at stations'). | Accepted. Covered by I16's caption; the rates caption already says targets cover two weeks. |
| R1 P21 | The ten-week average beats both alternatives on bullwhip and on both fill rates. | Accepted. New final beat in Part 3 states the result and the no-trend condition. |
| R1 P22 | 'Placed over received' reads as the ratio being placed somewhere. | Accepted. Same fix as S4. |
| R1 C1 | The definition omits the numerator and grammatically puts the ratio itself over a variance. | Accepted. Same fix as S4. |
| R1 C3 | The statement covers the retailer generally, although its fill rate later falls from 87.0% to 84.4%. | Accepted. Caption narrows to retailer orders. |
| R1 C8 | The values are supplied without identifying what the symbols measure. | Accepted. Same fix as S21. |
| R1 C10 | Both videos use paired inference before explaining what is paired. | Accepted. Fixed by S3 and S24. |
| R1 C11 | The column omits both its unit and its averaging operation. | Accepted. Header as S25; caption says 'Jobs average 2.29 weeks'. |
| R1 C12 | These labels violate the brief's minimum 0.45-frame-unit edge margin, approximately 61 pixels at 1080p. | Accepted. Chart right edge moved to 5.3 and each label passes inside_frame. |
| R1 C13 | The title uses a rhetorical question, and the closing caption uses figurative wording. | Accepted. Title 'The bottleneck'; closing as I18. |
| R2 S1 | Each of these three standalone videos uses "the viewer" with no gloss. | Accepted in part. Service-day says 'Day 1's saved web page', machining 'A saved viewer page', supply-chain names brewing.viewer (from snippets/capacity.py) in the caption; no code panel added over the screenshot. |
| R2 S8 | The mechanism is compressed into "so". | Accepted. Merged with I13: 'so brew speed cannot change orders. The factory's ratio is 2.32 in all four.' |
| R2 S9 | The same retailer quantity appears as 2.25 and then 2.2. | Accepted. Amplification labels at three significant figures. Same as I18. |
| R2 S14 | "Beer game" is a grounding-table term, but it appears only as a function name and is never connected to the chain. | Accepted. Caption: 'model.supply lists the beer game's chain in order.' |
| R2 I12 | The next caption restates the same fact, which the caption voice rules forbid, and it costs 2.6 s. | Accepted. Retailer caption keeps only the fill-rate drop. |
| R2 I13 | Part 2 gave the retailer's ratio (2.25) and a cumulative factory amplification (37.6). | Accepted. Header 'Factory bullwhip ratio' on two lines; caption says the factory's ratio. |
| R2 I18 | Two different values for the same quantity on consecutive beats. | Accepted. Same fix as S9. |
| R2 P6 | README:681-683 says a production station's service_time is the time per unit, so a job takes its quantity times one draw. | Accepted. 'service_time is weeks per case, not per job.' replaces 'brewed at a set rate'; brew_rate stays highlighted. |
| R2 P7 | shortage="backorder" is a required behavioral choice (README:552-556). | Accepted. Caption names both shortage values. |
| R2 P10 | Ragged baselines on axis labels look careless, which is the same defect I1-I23 fixed in the core video only. | Accepted. Tick labels and the amplification legend top-aligned; the job and ratio columns bottom-aligned. |
| R2 P13 | The label is meant to key the arrows by color, but its color does not match them, while 'shipments' does match its blue arrows. | Accepted. Up arrows drawn in ORDER_RED. |
| R2 C2 | The unconditional subtraction permits a negative order when inventory position exceeds the target. | Accepted. 'order_up_to orders target minus inventory position, never below zero.' |

After these changes, `check` passed for all four videos, every part was re-rendered at final quality, the final sheets were read again, and `check_deck.py` was rerun.

Rows marked R1 and R2 come from rounds 1 and 2 of the review loop in `review-loop/2026-10-24-flowsim-teaching-videos/` (snapshots a6e233f0cd1d and b951369bd929), whose ids are the reviewers' (S student, I instructor, P practitioner, C Codex correctness). The loop's `progress.md` records each verification.
