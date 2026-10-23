"""Define, simulate, and explore small service networks."""

# results imports the version while this package loads, so it comes first.
__version__ = "0.1.0"

from flowsim.comparison import Comparison, compare
from flowsim.model import Model, Node
from flowsim.results import Experiment, Results

__all__ = ["Comparison", "Experiment", "Model", "Node", "Results", "compare"]
