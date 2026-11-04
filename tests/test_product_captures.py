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


@pytest.mark.parametrize(("snapshot", "product"), products(), ids=lambda v: getattr(v, "name", v))
def test_the_product_xml_is_well_formed_where_it_exists(snapshot: Path, product: str) -> None:
    path = snapshot / f"{product}.xml"
    if not path.exists():
        pytest.skip("BoM publishes no product XML for this product (heatwave)")

    root = parse_xml(path.read_bytes())

    assert root is not None
    assert root.tag == PRODUCT_XML_ROOT


@pytest.mark.parametrize(("snapshot", "product"), products(), ids=lambda v: getattr(v, "name", v))
def test_the_text_file_starts_with_the_product_id_where_it_exists(
    snapshot: Path, product: str
) -> None:
    path = snapshot / f"{product}.txt"
    if not path.exists():
        pytest.skip("BoM publishes no text file for this product (heatwave)")

    assert path.read_text().splitlines()[0] == product
