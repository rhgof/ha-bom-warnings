"""Scenarios: each module here defines `apply(root)`, which changes the baseline tree.

To add one, drop fixtures in tests/fixtures/cap/ and a module in this directory. Its file name is
the scenario name. A module may set `LISTENS = False` for a scenario where the server is down.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

from .. import layout


def _modules() -> dict[str, ModuleType]:
    return {
        info.name: importlib.import_module(f"{__name__}.{info.name}")
        for info in pkgutil.iter_modules(__path__)
    }


def names() -> list[str]:
    return sorted(_modules())


def listens(name: str) -> bool:
    return getattr(_modules()[name], "LISTENS", True)


def apply(name: str, root: Path, spatial_from: Path | None = None) -> None:
    """Reset `root` to the baseline, then run the scenario, so the end state is always known."""
    module = _modules().get(name)
    if module is None:
        raise KeyError(f"unknown scenario {name!r}; known: {', '.join(names())}")
    layout.reset(root, spatial_from)
    module.apply(root)
