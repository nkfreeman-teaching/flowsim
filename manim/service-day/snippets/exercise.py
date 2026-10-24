from examples.service_day import staffing_exercise

comparison, decision = staffing_exercise()
for name in ["One server", "Two servers"]:
    first_day = comparison.experiments[name].runs[0]
    folder = name.lower().replace(" ", "-")
    first_day.viewer(f"output/service-day/{folder}/viewer.html")
targets = decision.select(
    "scenario",
    "mean_wait_minutes",
    "days_finished_on_time",
    "meets_targets",
)
comparison.viewer(
    path="output/service-day/overtime-comparison.html",
    metric="overtime",
)
