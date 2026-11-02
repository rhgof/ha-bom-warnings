"""A warning file is truncated to 0 bytes, which BoM has been seen to do."""

import os
from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    path = root / layout.WARNINGS / "IDQ21035.cap.xml"
    path.write_bytes(b"")
    os.utime(path, (layout.BASE_TIME + 600, layout.BASE_TIME + 600))
