"""When the weekly shapefile layer check is due, and the record that survives a restart.

No Home Assistant imports. The schedule is a value: every step returns the next one, so the
shared feed holds the current schedule and never mutates timing state of its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# Shapefile layers change rarely, so they are checked weekly, in the background.
LAYER_CHECK_INTERVAL = timedelta(days=7)
# When the last check reached the server, so a restart does not start a fresh one.
LAYER_CHECK_RECORD = ".last_layer_check"


@dataclass(frozen=True, slots=True)
class LayerSchedule:
    next_check: datetime

    @classmethod
    def loaded(cls, last_record: datetime | None, now: datetime) -> LayerSchedule:
        """Due at once, unless a recent record says otherwise."""
        # A record from the future (clock change) would postpone the check for too long.
        if last_record is not None and last_record <= now:
            return cls(last_record + LAYER_CHECK_INTERVAL)
        return cls(now)

    def due(self, now: datetime) -> bool:
        return now >= self.next_check

    def started(self, now: datetime) -> LayerSchedule:
        """Next due a week after the start, not the finish, so a slow check is not repeated."""
        return LayerSchedule(now + LAYER_CHECK_INTERVAL)

    def unreached(self, now: datetime) -> LayerSchedule:
        """The server was never reached, so try again on the next poll rather than in a week."""
        return LayerSchedule(now)


def read_record(cache_dir: Path) -> datetime | None:
    """Blocking. When the last check reached the server; None if missing or unreadable."""
    try:
        last = datetime.fromisoformat((cache_dir / LAYER_CHECK_RECORD).read_text())
    except OSError, ValueError:
        return None
    return last if last.tzinfo else None


def write_record(cache_dir: Path, now: datetime) -> None:
    """Blocking. Failing to write only means the next start checks again."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / LAYER_CHECK_RECORD).write_text(now.isoformat())
    except OSError as err:
        _LOGGER.debug("Could not record the layer check time: %s", err)
