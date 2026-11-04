"""The served directory tree, laid out exactly like BoM's, and helpers for scenarios."""

from __future__ import annotations

import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAP_FIXTURES = REPO / "tests" / "fixtures" / "cap"
CAP_SAMPLES = REPO / "tests" / "fixtures" / "cap_samples"
FIRE_DANGER_FIXTURES = REPO / "tests" / "fixtures" / "fire_danger"
PRODUCT_CAPTURES = REPO / "tests" / "fixtures" / "products" / "2026-11-03T2348Z"

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


def put_captured_product(
    root: Path, product: str, *, with_xml: bool = True, mtime: float = BASE_TIME
) -> None:
    """Copy a captured product into the warnings directory: its CAP file and its product XML."""
    names = [f"{product}.cap.xml"] + ([f"{product}.xml"] if with_xml else [])
    for name in names:
        target = root / WARNINGS / name
        shutil.copyfile(PRODUCT_CAPTURES / name, target)
        os.utime(target, (mtime, mtime))


def put_fire_danger(root: Path, product: str, *, mtime: float = BASE_TIME) -> Path:
    """Copy a recorded fire danger rating product (IDN10016 and its state equivalents)."""
    target = root / WARNINGS / f"{product}.xml"
    shutil.copyfile(FIRE_DANGER_FIXTURES / f"{product}.xml", target)
    os.utime(target, (mtime, mtime))
    return target


# Any ISO-8601 date-time with seconds, with or without an offset. BoM writes both "+00:00" and
# "-00:00", and the sample identifiers embed the sent time in this form too.
_TIMESTAMP = re.compile(rb"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})((?:[+-]\d{2}:\d{2}|Z)?)")
_SENT = re.compile(rb"<sent>([^<]+)</sent>")


def _parse(value: bytes) -> datetime:
    return datetime.fromisoformat(value.decode()).replace(tzinfo=None)


def shift_timestamps(data: bytes, shift_to: datetime) -> bytes:
    """Move every timestamp by one constant delta so `<sent>` is one hour before `shift_to`.

    A constant delta keeps all durations (effective to expires) as BoM wrote them. The delta is
    computed from naive wall-clock fields and applied to the same fields, so each timestamp keeps
    its own offset text and nothing is reformatted except the date and time digits.
    """
    sent = _SENT.search(data)
    if sent is None:
        raise ValueError("sample has no <sent>")
    sent_wall = _parse(sent.group(1))
    offset = datetime.fromisoformat(sent.group(1).decode()).utcoffset() or timedelta(0)
    target = shift_to.astimezone(UTC).replace(tzinfo=None) - timedelta(hours=1)
    # Compare in the sent time's own offset; a timedelta of a thousand years is fine for datetime.
    delta = target + offset - sent_wall

    def move(match: re.Match[bytes]) -> bytes:
        moved = _parse(match.group(0)) + delta
        return moved.strftime("%Y-%m-%dT%H:%M:%S").encode() + match.group(7)

    return _TIMESTAMP.sub(move, data)


def put_sample(
    root: Path, filename: str, *, shift_to: datetime | None = None, mtime: float = BASE_TIME
) -> Path:
    """Copy a real BoM sample (tests/fixtures/cap_samples) under its BoM name, dates shifted.

    The samples are old and the tsunami one is dated year 3004, so they are never current. This
    shifts every timestamp (sent, effective, expires, onset, and the one inside the identifier)
    by one delta so `<sent>` is `shift_to` minus an hour (default: now, UTC, at call time). It is
    a date shift of real data, done only for dev scenarios and never applied to test fixtures.
    """
    when = shift_to or datetime.now(UTC)
    target = root / WARNINGS / filename
    target.write_bytes(shift_timestamps((CAP_SAMPLES / filename).read_bytes(), when))
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
    for path in sorted(FIRE_DANGER_FIXTURES.glob("ID*.xml")):
        put_fire_danger(root, path.stem)
    if spatial_from:
        for path in spatial_from.glob("IDM*"):
            if path.is_file():
                shutil.copyfile(path, root / SPATIAL / path.name)
