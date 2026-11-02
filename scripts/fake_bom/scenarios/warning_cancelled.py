"""A coastal wind warning is cancelled: its file now holds a recorded `Cancel` message."""

from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    layout.put_cap(root, "IDN20400")
