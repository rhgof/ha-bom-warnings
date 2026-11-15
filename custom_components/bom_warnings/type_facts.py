"""What a warning's type adds to it: the summary shown, the extra attributes and the badges.

Most types are the generic case: a paragraph of the CAP description. A type that needs more has an
entry in `_READERS`, a function from the CAP block and the entry's area names to `Facts`. Nothing
outside this module tests for an event by name.

The table is here and not on the `warning_types` row because a reader needs `Info` and the text
helpers, and the foundation layer cannot import them.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from .cap import Info
from .warning_types import THUNDERSTORM_EVENT

# Each warning is repeated on up to 15 entities, and the recorder drops a state whose attributes
# pass 16,384 bytes, so the summary is one short paragraph and never the whole description.
SUMMARY_LIMIT = 300
# A detailed warning is one paragraph about a storm cell and where it is heading, about 420
# characters on 13 Nov 2026, and the part that matters is the end of it, so it is not cut so short.
DETAILED_SUMMARY_LIMIT = 500
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_VERY_DANGEROUS = re.compile(r"very dangerous thunderstorm", re.IGNORECASE)
# In display order. A keyword match, so an automation can test "wind" in `hazards`.
_HAZARD_WORDS = (("wind", "wind"), ("hail", "hail"), ("rain", "rain"), ("flood", "flood"))


@dataclass(frozen=True, slots=True)
class Facts:
    """What a type says about one block, beyond the fields every warning has."""

    summary: str | None
    # Extra attributes for the entities, each left out until there is something to say.
    attributes: Mapping[str, Any] = field(default_factory=dict)
    # Short labels a card shows beside the title, in display order.
    badges: tuple[str, ...] = ()


def _paragraphs(description: str | None) -> list[str]:
    """The paragraphs of a CAP description, each on one line, none empty."""
    parts = (" ".join(part.split()) for part in _PARAGRAPH_BREAK.split((description or "").strip()))
    return [part for part in parts if part]


def _pick(paragraphs: Sequence[str], names: Sequence[str]) -> str:
    """The first paragraph that names one of the entry's areas, else the first paragraph.

    A district's own name is tried first. The second try drops its first word, because BoM's text
    says "Metropolitan" where the district is called "Sydney Metropolitan".
    """
    wanted = [name.lower() for name in names if name]
    for tries in (wanted, [n.split(" ", 1)[1] for n in wanted if " " in n]):
        for paragraph in paragraphs:
            if any(name in paragraph.lower() for name in tries):
                return paragraph
    return paragraphs[0] if paragraphs else ""


def _shorten(text: str, limit: int) -> str | None:
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if text[limit - 1] != " ":
        # The cut fell inside a word, so back up to the end of the previous one.
        cut = cut.rpartition(" ")[0] or cut
    return f"{cut.rstrip()}…"


def summary_of(
    description: str | None, *, areas: Sequence[str] = (), limit: int = SUMMARY_LIMIT
) -> str | None:
    """One paragraph of a CAP description on one line, cut to `limit` characters.

    The paragraph is the first one that names one of `areas`, else the first. A cut falls on a word
    boundary and ends in an ellipsis; a single word longer than the limit is cut hard. None when
    there is nothing to show, so the attribute is left out and never empty.
    """
    return _shorten(_pick(_paragraphs(description), areas), limit)


def _hazards_in(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(hazard for word, hazard in _HAZARD_WORDS if word in lowered)


def _generic(info: Info, names: Sequence[str]) -> Facts:
    return Facts(summary=summary_of(info.description, areas=names))


def _thunderstorm(info: Info, names: Sequence[str]) -> Facts:
    """The paragraph that names the entry's area, its hazards and tier, and the text's facts."""
    paragraph = _pick(_paragraphs(info.description), names)
    hazards = _hazards_in(paragraph) or _hazards_in(info.hazard)
    very_dangerous = bool(_VERY_DANGEROUS.search(paragraph))
    attributes: dict[str, Any] = {}
    if hazards:
        attributes["hazards"] = list(hazards)
    if very_dangerous:
        attributes["very_dangerous"] = True
    if info.detailed:
        attributes["detailed"] = True
    if info.hazard:
        attributes["hazard"] = info.hazard
    if info.next_issue:
        attributes["next_issue"] = info.next_issue.isoformat()
    return Facts(
        summary=_shorten(paragraph, DETAILED_SUMMARY_LIMIT if info.detailed else SUMMARY_LIMIT),
        attributes=attributes,
        badges=(
            *(("Very dangerous",) if very_dangerous else ()),
            *(("Detailed",) if info.detailed else ()),
        ),
    )


_READERS: Mapping[str, Callable[[Info, Sequence[str]], Facts]] = {
    THUNDERSTORM_EVENT: _thunderstorm,
}


def facts_for(info: Info, names: Sequence[str]) -> Facts:
    """The facts for one block, with the product XML's line as the summary when there is no text."""
    facts = _READERS.get(info.event, _generic)(info, names)
    if facts.summary is None and (fallback := summary_of(info.xml_summary)):
        facts = replace(facts, summary=fallback)
    return facts
