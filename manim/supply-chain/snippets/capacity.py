from examples.supply_chain import capacity_study

capacity = capacity_study()
fill = capacity.intervals(
    metric="fill_rate",
    stock_point="Factory",
).select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
brewing = capacity.experiments["Brew 150 per week"].runs[0]
brewing.viewer("output/supply/brewing.html")
