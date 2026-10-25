from examples.operations import line_study

comparison = line_study()
gains = comparison.differences(
    metric="completed_at_close",
    baseline="No buffers",
).select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
moved = comparison.differences(
    metric="completed_at_close",
    baseline="Two each",
).select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
output = comparison.intervals(metric="completed_at_close").select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
day = comparison.experiments["Two each"].runs[0]
day.viewer("output/machining/viewer.html")
comparison.viewer(
    path="output/machining/comparison.html",
    metric="completed_at_close",
    baseline="No buffers",
)
