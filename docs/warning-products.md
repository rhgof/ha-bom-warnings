# Warning products: what CAP, text and product XML each hold

BoM publishes each warning as a **product** (for example `IDN20400`) in `/anon/gen/fwo/` as several
files with the same name and different extensions. The integration reads only the `.cap.xml` today.
This page records what the other files add, from real captures, so that work on the warning summary,
the product XML reader and the flood phase (#36) starts from evidence.

Evidence:

- `tests/fixtures/products/2026-11-03T2348Z/`: all 26 current products, 72 files (`.cap.xml`, `.txt`,
  `.xml`), unmodified, with a manifest and the directory listing. Taken by
  `scripts/capture_products.py`; `tests/test_product_captures.py` checks they load.
- Live reads on 4 Nov 2026 (about 11:00 to 11:45 AEDT) of the FTP listing, one file of each kind,
  HTTP HEAD requests, and the NSW RSS feed. Counts below are from that day and will change.

Everything here is **observed, not published**. BoM publishes no code list: the product schema
(`product.xsd` v1.7) does not enumerate hazard types, phases or severities.

## The files beside a CAP file

| File | Present | What it holds |
| --- | --- | --- |
| `.cap.xml` | 26 of 26 | Headline, severity, times, area codes; `description` and `instruction` for most types. **What we use today.** 2.3 to 6.4 KB (median 3.0, average 3.4); all 26 together 89.6 KB |
| `.txt` | 23 of 26 | The warning as written for broadcast. Adds the short title, situation headlines, warning number, tables |
| `.xml` (product XML, schema v1.7) | 23 of 26 | Structured `hazard` elements with type, phase, severity, areas, text sections. Flood 7 to 26 KB, marine wind about 5 KB; thunderstorm XML embeds a base64 map (70 to 297 KB) |
| `.pdf` | 26 of 26 on FTP | Formatted official warning |
| `.wrap.html` | 19 of 26 on FTP | Web version of the warning |
| `.product.xml` | 3 of 26 (heatwave only) | A 500 KB heatwave product. Not examined |
| `.amoc.xml` | 26 of 26 | AMOC product metadata. Not examined |

Served over HTTP (`https://www.bom.gov.au/fwo/<ID>.<ext>`, HEAD requests on 4 Nov 2026), the counts
differ from FTP: `.txt` 200 for 23 of 26, `.pdf` 200 for 23, `.wrap.html` 200 for 21. The three
extreme heat (heatwave) products have no `.txt` and no `.xml`; their `.pdf` is on FTP but returns
404 over HTTP, and only `.wrap.html` is served. Sheep grazier (NSW and Vic) and marine wind (SA, Tas,
Vic) have no `.wrap.html` over HTTP. `.txt` followed by `.wrap.html` covers all 26 products.

## Scope of one CAP file

One CAP file is one **product**: a state or river-system bulletin, replaced in place whenever BoM
re-issues it. It holds one to three `<info>` blocks; each block is a separate warning with its own
headline, severity, times and area codes (2 to 10 codes per file). Matching is per block, so one
file can match a location for some of its areas and not others.

| Type | One file covers | Blocks | Area codes |
| --- | --- | --- | --- |
| Riverine flood | One river system: the basin plus the gauge sites | 1 to 3 | 2 to 8 |
| Marine wind | One state's whole coastal-waters summary, split by strength | 1 or 2 | 4 to 10 |
| Extreme heat | One state | 1 or 2 | 3 to 6 |
| Sheep grazier | One state's forecast districts | 1 or 2 | 3 to 4 |

No file spans states.

## The same fields in each file

### Marine wind, `IDN20400` (NSW Marine Wind Warning Summary)

| | CAP | `.txt` | Product XML |
| --- | --- | --- | --- |
| Title | Headline per block: "Strong Wind Warning for coastal waters between Wooli and Montague Island for 05 November" | "Marine Wind Warning Summary for New South Wales" | The same title (`warning_title`) |
| Strength | Only in the wording | Only in the wording | A code per hazard: `GALE` for Eden, `STR` for the six other coasts |
| Severity | `Moderate` for both blocks, so gale and strong look the same | None | The strength code above, no knots or speed |
| Phase | `msgType` Update | None | `REN` (renewed) at product, hazard and area level |
| Areas | Codes only (`NSW_MW002` to `007`) and a joined name | Names only | Codes plus each coast's extent ("Sydney Coast: Broken Bay to Port Hacking") |
| Times | UTC: effective 2026-11-04T13:00Z, expires 2026-11-05T13:00Z | Issued 10:29 am EDT, valid to midnight Thursday | The same in UTC and local, plus `next-routine-issue-time` |
| Description and instruction | **None** | Postamble, plus "Gale Warning for the following area: Eden Coast" | Postamble, plus a `marine_forecast` summary and, per hazard, `warning_phenomena` ("Strong Wind Warning") and `warning_areas` |
| Link | `<web>` is the generic warnings page | None | None |

BoM re-issued this product at 11:24 AEDT with the same headlines and area split. Its Sydney block
takes effect at midnight AEDT on 5 November.

### Flood, `IDQ20829` (Moderate Flood Warning, Lower Condamine River)

| | CAP | `.txt` | Product XML |
| --- | --- | --- | --- |
| Title | Headline naming three areas | "Moderate Flood Warning for the Lower Condamine River" | The same short title |
| Strength | Only in the wording | In the title and wording | `MOD` per hazard, plus the element `Moderate` |
| Severity | `Moderate` | None | `MOD` (matches CAP here) |
| Phase | `msgType` Update | None | `UPD` at product, hazard and area level |
| Areas | Three codes and the long area name | Names only | The same three, labelled river-basin or river-site, plus the parent basin `QLD_RC168` |
| Times | UTC effective and expires | Issued 12:30 pm AEST; next issue by 1:00 pm Wednesday | The same in UTC and local; next issue is text only |
| Description and instruction | Both, in full: status per gauge and five safety lines | The same plus situation headlines, warning number (8) and a table of 12 gauge heights | The same, split per gauge into `flood_status` and `warning_prediction`, plus the gauges' heights, tendency and coordinates |
| Link | `<web>` is the generic warnings page | Points to the general flood page | Footer text only |

## Which file to use for which field

| Need | Use | Because |
| --- | --- | --- |
| Is it active, when does it expire, which areas | CAP | Already parsed; area codes match the shapefiles |
| A short summary where CAP has a description | CAP `description`, first paragraph | No extra fetch |
| A short summary for marine wind | Product XML | CAP has no description; the XML has one line per strength |
| Gale against strong wind | Product XML (`GALE`, `STR`) | CAP gives both `Moderate`; the headline is the fallback |
| A final flood warning | Product XML phase `FIN` | CAP severity is `Unknown` and the headline has no "Final" |
| Next routine issue time | Marine wind XML (`next-routine-issue-time`) | Flood has it as text only |
| The coast's extent for a marine area | Product XML | CAP has the names only |
| The situation headline of a flood | `.txt` or XML | CAP has none |

## Codes seen

Across the 23 captured product XML files (marine wind 5, flood 16, sheep grazier 2) and 33 hazards:

| Field | Values (count) |
| --- | --- |
| Hazard `type` | `FLW` flood (21), `MWW` marine wind (9), `SHW` sheep grazier (3) |
| Hazard `phase` | `UPD` (13), `FIN` (10), `REN` (8), `CAN` (2) |
| Hazard `severity` | Flood: `BLWMIN` (10), `MIN` (6), `MOD` (5). Marine wind: `STR` (7), `GALE` (1). Sheep grazier: `STD` (2). Cancelled: `CAN` (2) |
| `urgency`, `certainty` | `UNK` only |
| Product `<phase>` | `UPD` (12), `FIN` (8), `REN` (3) |

- **`FIN` is confirmed for floods.** It appears in 8 flood products (`IDQ20770`, `IDQ20790`,
  `IDQ20800`, `IDQ20815`, `IDQ20827`, `IDQ20835`, `IDQ20840`, `IDQ20850`). For those, the CAP severity
  is `Unknown`, the CAP headline does not contain the word "final", and the `.txt` title does
  ("Final Flood Warning for the Boyne and Burnett Rivers").
- **Not seen:** a storm force or hurricane force marine wind code, any thunderstorm code, any
  cyclone, fire weather, frost, road or tsunami code.

## RSS

The RSS feed for a state (for example `IDZ00054.warnings_nsw.xml`, NSW and ACT, TTL 10 minutes) is an
index: one item per current product, with a local-time-prefixed title, a link to a state warnings
web page and a `pubDate`. It has no product ID, area codes, severity, phase or validity times, so
the only join to a CAP file is title text against headline. It is generated with the CAP (`IDN20400`
CAP sent 00:24:50Z, RSS item 00:24:58Z). Its title can carry a phase the CAP headline lacks: "Final
Flood Warning for the Macintyre Brook". RSS stays a fallback only.

## Gaps (checked 4 Nov 2026)

No thunderstorm, severe weather, fire weather, frost, hazardous road, cyclone or tsunami warning was
current anywhere. The 26 products were 16 flood, 5 marine wind, 3 extreme heat and 2 sheep grazier.
Their sibling files, and the thunderstorm cancel and renew phases, are not captured. Re-run the
capture script when one is current.

## The cost of one refresh

- One `LIST *.cap.xml` every 10 minutes. If the server refuses the wildcard it falls back to a plain
  `LIST *`, a listing of about 400 KB; a timeout does not fall back.
- One fetch for each CAP file whose whole listing line changed (the listing has no year, so the line
  is the change signal). The first poll fetches all current files, 26 and about 90 KB on 4 Nov;
  later polls fetch the few that changed.
- The integration never fetches a `.txt` or `.pdf`. It reads two sibling `.xml` files, both by exact
  name and both optional, so neither can fail the warnings refresh:
  - A flood or marine wind product's XML (`<ID>.xml`), listed and fetched once per new issue of a
    product that has a current block of that type (`product_xml.ProductSummaryReader`). Marine wind
    XML is about 5 KB and flood 7 to 26 KB. A file over 400 KB (`MAX_XML_BYTES`) is skipped, which
    keeps out the thunderstorm XML with its embedded map (70 to 297 KB) and the heatwave products.
    It supplies the marine wind description and strength code, and marks a final flood warning.
  - A fire danger product, listed on every poll for each state with a location in a fire weather
    district, and fetched only when its listing line changes (`fire_danger.FireDangerReader`).
- After about 100 requests in a few minutes the server starts timing out data connections, so any
  sibling fetch must stay rare, size-capped and kept out of the warnings path.

## Attribution

Every `.txt` ends with BoM's copyright and disclaimer block and the XML carries the copyright and
disclaimer URLs. Text taken from these files is © Commonwealth of Australia (Bureau of Meteorology),
under the Bureau's own terms (<http://www.bom.gov.au/other/copyright.shtml>).
