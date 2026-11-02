"""The fake BoM FTP server, driven through the real BomFtp client over a local socket."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from custom_components.bom_warnings.ftp import BomFtp, BomFtpError, FileEntry, client_from_env
from scripts.fake_bom import scenarios
from scripts.fake_bom.server import FakeBom


@pytest.fixture
def fake_bom(tmp_path: Path, socket_enabled: None) -> Iterator[FakeBom]:
    with FakeBom(tmp_path / "root") as server:
        yield server


def client_for(server: FakeBom, directory: str = "/anon/gen/fwo/") -> BomFtp:
    return client_from_env({"BOM_WARNINGS_FTP_HOST": server.address}, directory=directory)


def names(server: FakeBom) -> list[str]:
    return [entry.name for entry in client_for(server).list_files("*.cap.xml")]


def test_baseline_serves_warnings_where_bom_does(fake_bom: FakeBom) -> None:
    scenarios.apply("baseline", fake_bom.root)

    assert "IDQ21035.cap.xml" in names(fake_bom)
    assert client_for(fake_bom).fetch("IDQ21035.cap.xml")


def test_baseline_creates_the_spatial_directory(fake_bom: FakeBom) -> None:
    scenarios.apply("baseline", fake_bom.root)

    spatial = client_for(fake_bom, "/anon/home/adfd/spatial/")
    assert spatial.list_files("*") == []


def listing(server: FakeBom) -> dict[str, FileEntry]:
    return {e.name: e for e in client_for(server).list_files("*.cap.xml")}


def test_warning_appears(fake_bom: FakeBom) -> None:
    scenarios.apply("baseline", fake_bom.root)
    before = set(names(fake_bom))

    scenarios.apply("warning_appears", fake_bom.root)

    assert set(names(fake_bom)) - before == {"IDQ21013.cap.xml"}


def test_warning_updated_changes_the_listing_line_not_the_names(fake_bom: FakeBom) -> None:
    scenarios.apply("baseline", fake_bom.root)
    before = listing(fake_bom)

    scenarios.apply("warning_updated", fake_bom.root)

    after = listing(fake_bom)
    assert after.keys() == before.keys()
    assert {n for n in after if after[n].raw != before[n].raw} == {"IDQ21035.cap.xml"}


def test_warning_cancelled_serves_a_cancel_message(fake_bom: FakeBom) -> None:
    scenarios.apply("warning_cancelled", fake_bom.root)

    body = client_for(fake_bom).fetch("IDN20400.cap.xml")
    assert body is not None
    assert b"<msgType>Cancel" in body


def test_warning_removed_is_a_550_on_fetch(fake_bom: FakeBom) -> None:
    scenarios.apply("warning_removed", fake_bom.root)

    assert "IDQ21033.cap.xml" not in names(fake_bom)
    assert client_for(fake_bom).fetch("IDQ21033.cap.xml") is None


def test_empty_file_is_listed_but_has_no_content(fake_bom: FakeBom) -> None:
    scenarios.apply("file_empty", fake_bom.root)

    assert listing(fake_bom)["IDQ21035.cap.xml"].size == 0
    assert client_for(fake_bom).fetch("IDQ21035.cap.xml") is None


def test_unavailable_scenario_says_the_server_must_not_listen() -> None:
    assert not scenarios.listens("unavailable")
    assert scenarios.listens("baseline")


def test_stopped_server_raises_ftp_error(tmp_path: Path, socket_enabled: None) -> None:
    with FakeBom(tmp_path) as server:
        client = client_for(server)
    with pytest.raises(BomFtpError):
        client.list_files("*.cap.xml")


@pytest.mark.parametrize("first", ["warning_appears", "file_empty", "warning_cancelled"])
def test_applying_baseline_after_any_scenario_restores_the_known_state(
    fake_bom: FakeBom, first: str
) -> None:
    scenarios.apply("baseline", fake_bom.root)
    expected = {n: (e.size, e.raw) for n, e in listing(fake_bom).items()}

    scenarios.apply(first, fake_bom.root)
    scenarios.apply("baseline", fake_bom.root)

    assert {n: (e.size, e.raw) for n, e in listing(fake_bom).items()} == expected


def test_unknown_scenario_is_a_clear_error(fake_bom: FakeBom) -> None:
    with pytest.raises(KeyError, match="unknown scenario"):
        scenarios.apply("nope", fake_bom.root)


def test_client_from_env_defaults_to_bom() -> None:
    client = client_from_env({})

    assert (client._host, client._port) == ("ftp.bom.gov.au", 21)


def test_client_from_env_rejects_bad_host() -> None:
    with pytest.raises(BomFtpError):
        client_from_env({"BOM_WARNINGS_FTP_HOST": "localhost:notaport"})
