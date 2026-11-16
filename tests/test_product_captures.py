"""The captured BoM warning products load offline, and the manifest tells the truth about them.

`tests/fixtures/products/<stamp>/` holds every current product as BoM served it: the CAP file and
its `.txt` and `.xml` siblings, taken by `scripts/capture_products.py`. Later work (the warning
summary, the product XML reader) builds its tests on these files, so this checks they are intact.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.bom_warnings.cap import parse_cap, parse_xml

PRODUCTS_DIR = Path(__file__).parent / "fixtures" / "products"
SNAPSHOTS = sorted(path for path in PRODUCTS_DIR.iterdir() if path.is_dir())
PRODUCT_XML_ROOT = "product"


def manifest(snapshot: Path) -> dict[str, Any]:
    return json.loads((snapshot / "manifest.json").read_text())


def products() -> list[tuple[Path, str]]:
    return [
        (snapshot, product) for snapshot in SNAPSHOTS for product in manifest(snapshot)["products"]
    ]


def products_with(suffix: str) -> list[tuple[Path, str]]:
    """The products that have a sibling file with this suffix."""
    return [(s, p) for s, p in products() if (s / f"{p}{suffix}").exists()]


def saved_files(snapshot: Path) -> list[dict[str, Any]]:
    return [f for f in manifest(snapshot)["files"] if f["status"] == "saved"]


def test_there_is_a_snapshot() -> None:
    assert SNAPSHOTS


@pytest.mark.parametrize("snapshot", SNAPSHOTS, ids=lambda p: p.name)
def test_every_saved_file_is_on_disk_at_its_listed_size(snapshot: Path) -> None:
    files = saved_files(snapshot)
    assert files
    assert {f["name"]: (snapshot / str(f["name"])).stat().st_size for f in files} == {
        f["name"]: f["size"] for f in files
    }


@pytest.mark.parametrize(("snapshot", "product"), products(), ids=lambda v: getattr(v, "name", v))
def test_the_cap_file_parses_to_its_own_product(snapshot: Path, product: str) -> None:
    warning = parse_cap((snapshot / f"{product}.cap.xml").read_bytes())

    assert warning is not None
    assert warning.product_id == product
    assert warning.infos


@pytest.mark.parametrize(
    ("snapshot", "product"), products_with(".xml"), ids=lambda v: getattr(v, "name", v)
)
def test_the_product_xml_is_well_formed(snapshot: Path, product: str) -> None:
    root = parse_xml((snapshot / f"{product}.xml").read_bytes())

    assert root is not None
    assert root.tag == PRODUCT_XML_ROOT


@pytest.mark.parametrize(
    ("snapshot", "product"), products_with(".txt"), ids=lambda v: getattr(v, "name", v)
)
def test_the_text_file_starts_with_the_product_id(snapshot: Path, product: str) -> None:
    assert (snapshot / f"{product}.txt").read_text().splitlines()[0] == product


@pytest.mark.parametrize("suffix", [".xml", ".txt"])
def test_only_heatwave_products_lack_a_sibling_file(suffix: str) -> None:
    # The filter above leaves these out, so this is what keeps "BoM publishes none for a heatwave
    # warning" (whose CAP event is Extreme Heat) a checked fact and not a silent hole.
    lacking = [(s, p) for s, p in products() if (s, p) not in products_with(suffix)]
    events = {
        info.event.lower()
        for snapshot, product in lacking
        for info in parse_cap((snapshot / f"{product}.cap.xml").read_bytes()).infos  # type: ignore[union-attr]
    }
    assert events <= {"extreme heat"}
