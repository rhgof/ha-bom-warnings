"""The cycle every sibling-file reader shares: read a product's file once per CAP issue.

Tested with a fake reader, so what is asserted is the mechanism and not a file format. The XML and
text readers each have their own tests of what they read.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.bom_warnings.cap import CapWarning, Info, Phase, Severity
from custom_components.bom_warnings.sibling_files import PerIssueReader, Read

from .fake_ftp import FakeFtp

NOW = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)
LATER = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)


class FakeReader(PerIssueReader[str]):
    """Wants a current Frost block, and rewrites its headline with what it 'read'."""

    def __init__(self) -> None:
        super().__init__(FakeFtp({}))
        self.reads: list[str] = []
        self.says: dict[str, Read[str] | None] = {}

    def _wants(self, info: Info, now: datetime) -> bool:
        return info.event == "Frost" and info.is_active(now)

    def _read(self, warning: CapWarning) -> Read[str] | None:
        self.reads.append(f"{warning.product_id}@{warning.identifier}")
        return self.says.get(warning.product_id, Read("read"))

    def _apply(self, warning: CapWarning, value: str, now: datetime) -> CapWarning:
        infos = tuple(
            replace(i, headline=value) if self._wants(i, now) else i for i in warning.infos
        )
        return replace(warning, infos=infos)


def warning(product: str = "IDV1", identifier: str = "a", event: str = "Frost") -> CapWarning:
    block = Info(
        event=event,
        headline="original",
        severity=Severity.MINOR,
        effective=NOW,
        expires=LATER,
        area_desc="",
        area_codes=frozenset({"X"}),
        phase=Phase.NEW,
    )
    return CapWarning(product, identifier, NOW, Phase.NEW, (block,))


def headline(warnings: list[CapWarning]) -> str:
    return warnings[0].infos[0].headline


def test_a_product_is_read_once_per_issue_and_its_value_applied_each_time() -> None:
    reader = FakeReader()

    first = reader.enrich([warning()], NOW)
    second = reader.enrich([warning()], NOW)

    assert reader.reads == ["IDV1@a"]
    assert headline(first) == headline(second) == "read"


def test_a_reissued_product_is_read_again() -> None:
    reader = FakeReader()
    reader.enrich([warning(identifier="a")], NOW)

    reader.enrich([warning(identifier="b")], NOW)

    assert reader.reads == ["IDV1@a", "IDV1@b"]


@pytest.mark.parametrize(
    ("event", "now"),
    [
        pytest.param("Wind", NOW, id="a-block-of-another-type"),
        pytest.param("Frost", datetime(2026, 11, 16, tzinfo=UTC), id="an-ended-block"),
    ],
)
def test_a_block_that_does_not_want_the_file_costs_no_read(event: str, now: datetime) -> None:
    reader = FakeReader()

    result = reader.enrich([warning(event=event)], now)

    assert reader.reads == []
    assert headline(result) == "original"


def test_a_failed_read_leaves_the_warning_alone_and_is_tried_again() -> None:
    reader = FakeReader()
    reader.says["IDV1"] = None

    first = reader.enrich([warning()], NOW)
    reader.says["IDV1"] = Read("read")
    second = reader.enrich([warning()], NOW)

    assert reader.reads == ["IDV1@a", "IDV1@a"]
    assert (headline(first), headline(second)) == ("original", "read")


def test_a_remembered_empty_result_is_not_read_again() -> None:
    reader = FakeReader()
    reader.says["IDV1"] = Read("")

    reader.enrich([warning()], NOW)
    reader.enrich([warning()], NOW)

    assert reader.reads == ["IDV1@a"]


def test_a_product_that_left_the_feed_is_forgotten() -> None:
    reader = FakeReader()
    reader.enrich([warning()], NOW)
    reader.enrich([], NOW)

    reader.enrich([warning()], NOW)

    assert reader.reads == ["IDV1@a", "IDV1@a"]


def test_each_product_is_remembered_separately() -> None:
    reader = FakeReader()
    reader.says["IDV2"] = Read("second")

    result = reader.enrich([warning("IDV1"), warning("IDV2")], NOW)

    assert [w.infos[0].headline for w in result] == ["read", "second"]
