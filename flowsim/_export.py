"""Safe CSV and metadata export helpers shared by runs, experiments, and comparisons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from flowsim import __version__

if TYPE_CHECKING:
    from flowsim.results import Experiment


def write_text(path: str | Path, text: str) -> None:
    destination = Path(path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination.write_text(
        data=text,
        encoding="utf-8",
    )


# Every file name a FlowSim export can write. An export removes the ones it did
# not write, so a folder never mixes files from two different exports.
EXPORT_FILE_NAMES = frozenset(
    {
        "customers.csv",
        "visits.csv",
        "states.csv",
        "stations.csv",
        "summary.csv",
        "activities.csv",
        "failures.csv",
        "inventory.csv",
        "shipments.csv",
        "stock_points.csv",
        "metadata.json",
        "runs.csv",
        "intervals.csv",
        "differences.csv",
    }
)


def require_flowsim_folder(destination: Path) -> None:
    """Refuse a folder that holds export-named files FlowSim did not write.

    A folder counts as FlowSim's when its metadata.json parses as a JSON object
    with a "flowsim_version" key. A missing folder or one without export-named
    files is fine.
    """
    if not destination.is_dir():
        return
    clashing = sorted(
        name for name in EXPORT_FILE_NAMES if (destination / name).is_file()
    )
    if not clashing:
        return
    try:
        metadata = json.loads((destination / "metadata.json").read_text())
    except (OSError, ValueError):
        metadata = None
    if isinstance(metadata, dict) and "flowsim_version" in metadata:
        return
    raise ValueError(
        f"{destination} holds {', '.join(clashing)}, but no FlowSim "
        "metadata.json, so FlowSim cannot tell whether it wrote them and will "
        "not replace or delete them. Export into an empty folder or one an "
        "earlier FlowSim export wrote."
    )


def remove_stale_exports(destination: Path, written: set[str]) -> None:
    """Delete FlowSim export files in destination that this export did not write."""
    for name in EXPORT_FILE_NAMES - written:
        stale = destination / name
        if stale.is_file():
            stale.unlink()


def _write_metadata(path: str | Path, data: dict[str, Any]) -> None:
    """Write export metadata as JSON, stamped with the FlowSim version.

    The file is written beside its destination and then renamed over it, so an
    interrupted write keeps the earlier metadata, which marks the folder as
    FlowSim's for require_flowsim_folder.
    """
    destination = Path(path)
    partial = destination.with_name(destination.name + ".partial")
    write_text(partial, json.dumps({"flowsim_version": __version__, **data}, indent=2))
    partial.replace(destination)


def export_tables(
    directory: str | Path,
    *,
    summary: pl.DataFrame,
    stations: pl.DataFrame,
    stock_points: pl.DataFrame | None,
    intervals: pl.DataFrame,
    differences: pl.DataFrame | None,
    metadata: dict[str, Any],
) -> Path:
    """Write pooled run tables, intervals, and metadata, removing stale files."""
    tables = {
        "runs.csv": summary,
        "stations.csv": stations,
        "stock_points.csv": stock_points,
        "intervals.csv": intervals,
        "differences.csv": differences,
    }
    return write_export(
        directory=directory,
        tables={name: table for name, table in tables.items() if table is not None},
        metadata=metadata,
    )


def write_export(
    directory: str | Path,
    tables: dict[str, pl.DataFrame],
    metadata: dict[str, Any],
) -> Path:
    """Write metadata.json and each table to its file name, removing stale files."""
    destination = Path(directory)
    require_flowsim_folder(destination)
    destination.mkdir(
        parents=True,
        exist_ok=True,
    )
    # Metadata goes first, so a request that cannot be written replaces no
    # tables from an earlier export, and an export interrupted while writing
    # tables leaves a folder that a retry still recognizes as FlowSim's.
    _write_metadata(destination / "metadata.json", metadata)
    for name, table in tables.items():
        table.write_csv(destination / name)
    remove_stale_exports(destination, set(tables) | {"metadata.json"})
    return destination


def request_metadata(
    experiment: Experiment,
    metric: str,
    station: str | None,
    stock_point: str | None,
    confidence: float,
    *,
    level: float,
) -> dict[str, Any]:
    """Describe an export's request, settings, and replication seeds."""
    settings = experiment.settings
    return {
        "metric": metric,
        "station": station,
        "stock_point": stock_point,
        # The validated level is a Python float, as JSON needs, for any real input.
        "confidence": level,
        "time_unit": settings.time_unit,
        "duration": settings.duration,
        "warmup": settings.warmup,
        "drain": settings.drain,
        "replication_seeds": [run.settings.seed for run in experiment.runs],
    }
