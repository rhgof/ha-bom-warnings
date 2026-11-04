"""Capture BoM's current warning products, unmodified, for study and for test fixtures.

Usage: python -m scripts.capture_products [--out DIR] [--max-bytes N] [--delay SECONDS]

For every current CAP file in /anon/gen/fwo/ this saves the CAP file and its `.xml` and `.txt`
siblings (the product XML and the broadcast text) under `tests/fixtures/products/<UTC stamp>/`,
with a `manifest.json` that says what was seen, what was saved and why anything was not. It also
saves the raw directory listing. Nothing is edited, so the files are real BoM output.

It talks to the real BoM server and ignores BOM_WARNINGS_FTP_HOST. The server starts timing out
after a hundred or so requests in a few minutes, so it shares one login, pauses between fetches,
skips files over `--max-bytes` (thunderstorm XML embeds a map image and heatwave products are huge)
and stops after three failures in a row.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from custom_components.bom_warnings.ftp import BomFtpError, FileEntry, client_from_env

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "products"
SIBLING_SUFFIXES = (".xml", ".txt")
CAP_SUFFIX = ".cap.xml"
MAX_FAILURES_IN_A_ROW = 3


@dataclass
class Capture:
    name: str
    size: int
    listing: str
    status: str


def product_ids(listing: list[FileEntry]) -> list[str]:
    return sorted(
        entry.name.removesuffix(CAP_SUFFIX) for entry in listing if entry.name.endswith(CAP_SUFFIX)
    )


def product_listing(listing: list[FileEntry], products: list[str]) -> list[FileEntry]:
    """Every file beside a current CAP file, whatever its extension.

    The directory holds thousands of unrelated forecast files, so only these lines are kept. They
    show which siblings exist (PDF, map image, product XML) without saying anything about the rest.
    """
    return [entry for entry in listing if entry.name.split(".")[0] in products]


def wanted(product: str, listing: list[FileEntry]) -> list[FileEntry]:
    """The CAP file and the siblings worth reading, as listed.

    A `.cap.xml` ends in `.xml` too, so match the product's own name exactly.
    """
    names = {f"{product}{CAP_SUFFIX}", *(f"{product}{suffix}" for suffix in SIBLING_SUFFIXES)}
    return [entry for entry in listing if entry.name in names]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-bytes", type=int, default=400_000)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%MZ")
    target = args.out / stamp
    target.mkdir(parents=True)

    # An empty environment on purpose: this is always the real server.
    client = client_from_env({})
    captures: list[Capture] = []
    failures = 0
    with client.session():
        listing = client.list_files("*")
        products = product_ids(listing)
        beside = product_listing(listing, products)
        (target / "listing.txt").write_text("\n".join(entry.raw for entry in beside) + "\n")
        print(f"{len(listing)} files listed, {len(products)} current CAP products")
        for product in products:
            for entry in wanted(product, listing):
                if entry.size > args.max_bytes:
                    captures.append(Capture(entry.name, entry.size, entry.raw, "too_large"))
                    print(f"  skip  {entry.name} ({entry.size} bytes)")
                    continue
                if failures >= MAX_FAILURES_IN_A_ROW:
                    captures.append(Capture(entry.name, entry.size, entry.raw, "not_tried"))
                    continue
                time.sleep(args.delay)
                try:
                    data = client.fetch(entry.name)
                except BomFtpError as err:
                    failures += 1
                    captures.append(Capture(entry.name, entry.size, entry.raw, f"error: {err}"))
                    print(f"  FAIL  {entry.name}: {err}")
                    continue
                failures = 0
                if data is None:
                    captures.append(Capture(entry.name, entry.size, entry.raw, "empty_or_gone"))
                    continue
                (target / entry.name).write_bytes(data)
                captures.append(Capture(entry.name, entry.size, entry.raw, "saved"))
                print(f"  saved {entry.name} ({len(data)} bytes)")

    manifest = {
        "captured_at": datetime.now(UTC).isoformat(),
        "source": "ftp://ftp.bom.gov.au/anon/gen/fwo/",
        "max_bytes": args.max_bytes,
        "directory_files": len(listing),
        "products": products,
        "files": [asdict(c) for c in captures],
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    saved = sum(c.status == "saved" for c in captures)
    print(f"saved {saved} of {len(captures)} files to {target}")
    if failures >= MAX_FAILURES_IN_A_ROW:
        print("stopped early after repeated failures; run again later for the rest")


if __name__ == "__main__":
    main()
