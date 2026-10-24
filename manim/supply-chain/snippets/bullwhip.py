from examples.supply_chain import amplification, bullwhip_study

comparison = bullwhip_study()
ratios = comparison.intervals(
    metric="bullwhip_ratio",
    stock_point="Factory",
).select(
    "scenario",
    "mean",
    "lower",
    "upper",
)
growth = amplification(comparison)
first = comparison.experiments["Forecast from orders"].runs[0]
first.viewer("output/supply/viewer.html")
