"""The served directory tree, laid out exactly like BoM's, and helpers for scenarios."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAP_FIXTURES = REPO / "tests" / "fixtures" / "cap"

WARNINGS = Path("anon/gen/fwo")
SPATIAL = Path("anon/home/adfd/spatial")

# A fixed time so listings are identical from run to run.
BASE_TIME = datetime(2026, 11, 2, 10, 0, tzinfo=UTC).timestamp()

# Warnings that are current in the baseline state; the other fixtures are used by scenarios.
BASELINE_WARNINGS = ("IDQ21035", "IDQ21033", "IDW21013", "IDN36631")


def put_cap(root: Path, product: str, *, mtime: float = BASE_TIME) -> Path:
    """Copy a recorded CAP fixture into the warnings directory."""
    target = root / WARNINGS / f"{product}.cap.xml"
    shutil.copyfile(CAP_FIXTURES / f"{product}.cap.xml", target)
    os.utime(target, (mtime, mtime))
    return target


def reset(root: Path, spatial_from: Path | None = None) -> None:
    """Rebuild the tree from scratch with the baseline warnings.

    `spatial_from` is a directory of shapefile zips (IDM000NN.zip) to serve. The repo has none,
    so by default the spatial directory is empty.
    """
    shutil.rmtree(root / "anon", ignore_errors=True)
    (root / WARNINGS).mkdir(parents=True)
    (root / SPATIAL).mkdir(parents=True)
    for product in BASELINE_WARNINGS:
        put_cap(root, product)
    if spatial_from:
        for path in spatial_from.glob("IDM*"):
            if path.is_file():
                shutil.copyfile(path, root / SPATIAL / path.name)
