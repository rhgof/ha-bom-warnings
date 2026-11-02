"""The server is down: the tree is built but nothing listens, so connections are refused."""

from pathlib import Path

LISTENS = False


def apply(root: Path) -> None:
    """Nothing to change in the tree."""
