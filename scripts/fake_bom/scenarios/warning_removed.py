"""BoM deletes a warning file once the hazard ends, so a fetch gets a 550."""

from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    (root / layout.WARNINGS / "IDQ21033.cap.xml").unlink()
