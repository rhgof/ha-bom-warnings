# Captured warning products

Each folder is one run of `python -m scripts.capture_products`, named for the UTC time of the run.
It holds, unmodified, every current CAP file in `ftp://ftp.bom.gov.au/anon/gen/fwo/` together with
its two sibling files, the product XML (`<id>.xml`) and the broadcast text (`<id>.txt`). Nothing
is edited, so the folder is a snapshot of what BoM published at that moment.

Each folder also has:

- `manifest.json`: when it was taken, how many files the directory held, the product ids, and for
  every file its listing line and whether it was saved (or why not).
- `listing.txt`: the directory listing lines for the current products only (the directory holds
  thousands of unrelated forecast files). It shows which other siblings exist, such as `.pdf`,
  `.png` and `.wrap.html`, without fetching them.

Heatwave products have no `.xml` or `.txt`. Files over 400,000 bytes are skipped and recorded as
`too_large`: thunderstorm product XML embeds a map image and can be 300 KB.

Nothing under here is used by a test yet. They are evidence for issue #36 (the product XML and
the broadcast text beside the CAP files) and the source for fixtures when that work starts. A
product only exists on the server while its hazard is current, so a later run will hold different
warnings; keep the earlier folders as the record of what was seen.

| Folder | Products | Notes |
| --- | --- | --- |
| `2026-11-03T2348Z` | 26 CAP products, 72 files | Flood (16 products, 8 of them final), marine wind (5, one with a gale hazard), sheep grazier (2), heatwave (3, no siblings). No thunderstorm, cyclone, tsunami, fire weather, frost or road weather warning was current. |
