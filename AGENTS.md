# FlowSim

This is a general Python package for classroom service-network simulations.
Keep SimPy in `flowsim/engine.py` and `flowsim/station.py`, and keep notebook
interfaces in `examples/`.

- Use Pixi for Python commands and dependencies.
- Numeric outputs are classroom tables, CSV files, and interactive plots.
  LaTeX numeric exports are out of scope by the owner's choice.
- Keep one README. Do not add process records unless requested.
- Every run starts with fresh simulation state and owned NumPy generators.
- Every station runs through `_Station` in `flowsim/station.py`. Do not add a
  second customer path for plain stations.
- At equal times, shift changes run first, then completions, transfers,
  failures, and repairs, then arrivals, then drain checks. `flowsim/engine.py`
  sets this order with SimPy event priorities.
- Verify timing and metrics with hand-calculated examples, not only SimPy output.
- Routes remain acyclic, and service remains first-come, first-served.
  Schedules, finite buffers, and failures require explicit behavior arguments.
  Do not choose global defaults for shift ending, overflow, or failure clocks
  without an owner decision.
- Library tests build models from `tests/models.py`, never from `examples/`.
  Only `tests/test_examples.py` and `tests/test_readme.py` use `examples/`,
  to check that the examples and every README Python block still run.
- Run `pixi run check` and `pixi run examples` after behavioral changes.
- The package must import and run without Marimo. Marimo is an example client.
- The version lives only in `flowsim/__init__.py`.

## Adding a station or source behavior

1. Add the argument to `Model.station` or `Model.source` with validation in
   `flowsim/model.py`, including any required companion argument.
2. Implement it in `flowsim/station.py` or `flowsim/engine.py`.
3. Add any new column to the schemas in `flowsim/results.py`, and any new
   replication metric to `METRICS` there.
4. Add a hand-calculated test, and update the README section and tables.
