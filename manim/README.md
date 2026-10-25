# Manim videos

Silent animated videos for flowsim, one folder per video. Each video is built from one
source as two products: a continuous MP4 and an offline HTML deck that stops at each break
until the presenter advances it. The setup was copied from
`~/.claude/skills/manim-video/template` on 2026-10-24.

| Folder | Video | Unlisted YouTube copy |
|---|---|---|
| `flowsim-core/` | FlowSim: the core workflow (model, tables, viewer, replications, comparisons, extensions) | https://youtu.be/lRh8qnjg4lo |
| `service-day/` | FlowSim: staffing a service day (the classroom exercise) | https://youtu.be/z-lPhexe7ZY |
| `machining-line/` | FlowSim: modeling a machining line (bottleneck, buffer plans, CNC failures, lunch staffing) | https://youtu.be/kY1KzMO9g-I |
| `supply-chain/` | FlowSim: the bullwhip effect (four stages, demand sharing, brewing capacity) | https://youtu.be/SbkiDw28vhI |

The four uploads are also in one unlisted
[playlist](https://www.youtube.com/playlist?list=PLGOCHatbz0gA). A re-rendered video
needs a new upload, since YouTube does not replace a video's file in place.

## Layout

- `shared/explainer.py` holds what every video uses: the font check, base colors, text and
  caption builders, the house style for boxes, cards, bars, arrows, and title and section
  cards, and the scene classes. `ExplainerScene` (captions, checkpoints, slide breaks, and
  part title cards) is the teaching and research profile, and `PitchScene` is the short cut
  for an outside audience (faster, larger captions).
- `shared/review_frames.py` cuts checkpoint stills into contact sheets for review.
- `shared/exported.py` reads the project's exported numbers file, so a video displays the
  values the paper displays, and asserts facts that have no macro against manuscript lines.
- `shared/clip_timer.js` is the deck's animation timer, and `shared/add_clip_timer.py` adds
  it to a deck (`render.sh` runs it after every deck build).
- `render.sh` renders one video folder. Each video folder has its scene module, a
  `video.conf` naming the module, the output name, and the parts in order, and a README
  naming its sources.
- `pixi.toml` is a separate environment (manim 0.22, manim-slides 5.7.0 with PyQt6), so the
  project's own environment does not depend on it.

Renders stay out of git (`*/build/`, `*/output/`). To bring this folder's shared files up to
the current skill, run `scaffold.py --upgrade` from the project root (see the manim-video
skill).

## Capture

The FlowSim videos show real code and real output. Each video's `capture.py` runs in the
project's own environment, since this folder's environment does not install FlowSim:

```bash
pixi run python manim/<video>/capture.py   # from the project root
```

It executes the snippet files under `<video>/snippets/` (and, for flowsim-core, the README
blocks it quotes), screenshots tables and saved viewers with Playwright and Chrome, and
writes `<video>/captured/numbers.json`. The scene module checks that every snippet, example
file, and README block still matches the copy that ran, so a stale capture stops the render.
`shared/capture_tools.py` and `shared/flowsim_video.py` hold the helpers both sides share.

## Render

From this folder:

```bash
pixi run render <video> check     # run every scene without rendering; lists caption defects
pixi run render <video> preview   # 480p15 draft plus contact sheets in <video>/build/preview/
pixi run render <video> review    # 720p15 plus contact sheets in <video>/build/review/stills/
pixi run render <video> final     # 1080p30, video and deck in <video>/output/
PARTS="Part1Question" pixi run render <video> review
```

The last form renders selected parts only and skips the joined video and the deck. Each
video module asserts every displayed number against its source before drawing, so a changed
source fails the render instead of shipping a wrong number.

## Presenting

Copy `<video>/output/deck/` (the page and its `_assets/` folder) to the presenting machine
and open the HTML file in a browser. The right arrow plays the next segment, and the left
arrow returns to the previous one. Typing `G`, a slide number, and Enter jumps to that
slide. The deck needs no internet, because the render copies reveal.js into the assets
folder.

A small ring in the bottom-right corner fills while the current slide's animation plays and
becomes a check when it has finished, so the next click is safe. Space pauses and resumes
the animation (the ring dims while paused), and T hides or shows the ring.
