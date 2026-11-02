"""The strength class of a marine wind warning, from its headline.

No Home Assistant imports. CAP severity has two levels for marine wind (a gale and a strong wind
are both Moderate), and the files carry no speed, so the class is named only in the headline:
"Strong Wind Warning", "Gale Force Wind Warning", "Storm Force Wind Warning". BoM's spatial data
guide lists the classes (strong wind, gale, storm force, hurricane force) and its warning products
guide says marine wind warnings are issued for 26 knots or stronger.
"""

from __future__ import annotations

import re

WIND_EVENT = "Wind"

_CLASSES = {
    "strong": "strong",
    "gale force": "gale",
    "gale": "gale",
    "storm force": "storm",
    "storm": "storm",
    "hurricane force": "hurricane",
    "hurricane": "hurricane",
}
_HEADLINE = re.compile(r"^(?P<class>.+?)\s+wind\s+warning\b", re.IGNORECASE)


def wind_strength(event: str, headline: str) -> str | None:
    """The strength class of a Wind warning, or None.

    Known classes are lowercase and stable (`strong`, `gale`, `storm`, `hurricane`). Wording this
    code does not know keeps its class text as written, so a new class is shown and not lost. A
    cancellation, a headline with no class, and any event other than Wind have no strength.
    """
    if event != WIND_EVENT:
        return None
    match = _HEADLINE.match(headline.strip())
    if match is None:
        return None
    text = match.group("class").strip()
    if text.lower().startswith("cancellation"):
        return None
    return _CLASSES.get(text.lower(), text)
