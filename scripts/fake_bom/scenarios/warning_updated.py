"""A warning is reissued: same file name, newer modified time and a changed size.

The integration's change signal is the listing line, so a later time and one extra byte is
enough. The content stays a real recorded CAP file.
"""

import os
from pathlib import Path

from .. import layout


def apply(root: Path) -> None:
    path = layout.put_cap(root, "IDQ21035", mtime=layout.BASE_TIME + 600)
    with path.open("ab") as handle:
        handle.write(b"\n")
    os.utime(path, (layout.BASE_TIME + 600, layout.BASE_TIME + 600))
