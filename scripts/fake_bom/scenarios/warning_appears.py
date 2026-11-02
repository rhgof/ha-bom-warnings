"""A new Severe heatwave warning for Queensland appears."""

from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    layout.put_cap(root, "IDQ21013")
