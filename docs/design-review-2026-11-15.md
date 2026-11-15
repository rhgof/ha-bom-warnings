# Design review and handoff, 15 to 16 Nov 2026

A review of both repos (this integration and `ha-bom-warnings-card`) with the deep-module lens
(depth, seams, locality, the deletion test), written so work can resume in a fresh session.
Section 2 says which candidates have landed; section 3 says where the work stands.

## 1. What is already deep (keep)

- `cap.py`: bytes to `CapWarning`, no Home Assistant imports.
- `product_text.parse_text`: bytes to `ProductText`, tested straight through on real files.
- Card `detail-view.ts`: `detailView(state, hass)` to a view, a pure function that the tile tests
  cross without a browser.
- The shared fixture `tests/fixtures/dashboard/states.json` (copied to the card repo). A real seam
  with two adapters: the integration's tests check it against what the code computes, the card's
  tests render from it. The best interface in the project.
- `docs/architecture.json` and `tests/test_architecture.py`: layer rules that run.
- `type_facts.facts_for` (new): one table from event to what a type adds, found by event.

## 2. Deepening candidates

### The root cause, and the decision taken (16 Nov)

The pipeline assumed one CAP `<info>` block is one hazard and its CAP severity is the grade. Flood,
frost, heat and marine wind fit that. Thunderstorm and Severe weather do not (CAP severity is
`Unknown`, the facts are in prose and a sibling `.txt` file) and fire weather has its own grades.
Each fix had been a per-type escape hatch on the CAP-severity pipeline. The decision: the
integration interprets each warning once and sends what a card needs, so the cards hold no level
words, ranks or event names.

### Integration

**1. Type-specific behaviour has leaked into the generic path.** DONE.
`type_facts.py` holds `_READERS`, a table from event to a function `(info, names) -> Facts`
(summary, attributes, badges). `_active` has no event check. Thunderstorm and Weather are the two
entries. It is beside `active_warnings.py` and not on the `warning_types` row, because the
foundation layer cannot import `Info`. Commits `7e893d9`, `4711d96`.

**2. `ProductSummaryReader` and `ProductTextReader` repeat one mechanism.** NOT STARTED.
Both do "fetch once per CAP issue, remember absence, forget a product that left the feed" (the
`_seen` bookkeeping is in both files). They differ in details: the XML reader lists the file, caps
its size and checks it is not older than the CAP; the text reader fetches directly. One per-issue
memo module with per-reader hooks would fix a bug once, and `shared_feed.py` would call one
pipeline instead of two hand-ordered `enrich` calls. Do this before a third sibling file is added.

**3. `Info` is becoming a bag of sibling-file results.** NOT STARTED.
`xml_summary` and `xml_severity` come from the XML; `detailed`, `hazard` and `next_issue` from the
text. Group them into one `SiblingFacts` value. Low risk, lower value than 2.

**4. Level, colour and rank are three small functions over one table.** PARTLY DONE.
`display_fields(warning)` now builds the level, title, colour, icon, rank, ended and badges in one
place (`7ec9617`), but `level_of`, `color_of` and `highest_level` still share `_grades` and the
severity/level split separately. A single `Level` value (word, colour, rank) would make the next
grading change local.

### Card

**5. The card re-derives what the integration already knows.** DONE (`8a06edf`).
`LEVEL_RANK`, `LEVEL_WORDS`, `NO_LEVEL`, `ENDED` and the event check are gone; the card reads
`title`, `rank`, `ended`, `level`, `badges` and `layout`. #93 (colour inconsistency across tiles,
icons and the activity graph) can now be fixed from one source.

**6. `bom-warning-tile.ts` does two jobs.** NOT STARTED. It wraps the built-in tile and, for a
sensor that sends `layout: "detail"`, draws its own, in one class. Split the own-tile rendering
into its own element behind a small dispatcher.

**7. `Hass` and `HassState` are declared in four files** (tile, list card, editor,
`detail-view.ts`). Tidy into one shared module. Cheap, low risk. NOT STARTED.

### Suggested order now

2, then 4's remainder, then 6 and 7 alongside a card change. Turning on the detail layout for
Severe weather is one line (`detail=True` on its row) once its tile has something to say. The
card's `HAZARD_WORDS` still turns the integration's hazard keywords into phrases; the integration
could send the phrases instead.

## 3. Where the work stands (16 Nov 2026, morning)

### Shipped and pushed

| Repo | Commit | What |
| --- | --- | --- |
| `ha-bom-warnings` | `7e0c801` | `.txt` reader (`product_text.py`), area-matched summary, `hazards`, `very_dangerous`, `detailed`, `hazard`, `next_issue`, `current` |
| `ha-bom-warnings` | `31025b0` | Thunderstorm and Severe weather sensors say `severe` for CAP `unknown` (orange kept; a real `severe` is red) |
| `ha-bom-warnings` | `7ec9617` | Display fields on every ranked entry and sensor top level: `level` (null when ungraded), `title`, `rank`, `ended`, `badges` |
| `ha-bom-warnings` | `dd9e9f9` | `layout: "detail"` from a type row's `detail` flag; fixture checked against the code |
| `ha-bom-warnings` | `2aa0a56` | Markdown cards read `level` and `ended`; docs |
| `ha-bom-warnings` | `7e893d9` | `type_facts` table, `_active` has no event check |
| `ha-bom-warnings` | `4711d96` | Weather event `hazards` and `hazard` (from two catalogue samples) |
| `ha-bom-warnings-card` | `8a06edf` | Card reads the display fields; `detail-view.ts` replaces `thunderstorm-view.ts` |

Fixtures: `tests/fixtures/products/2026-11-13T0625Z-thunderstorm`, `2026-11-15T0343Z-thunderstorm`,
`2026-11-15T0516Z-thunderstorm` (the last holds the first Cancel product).
Tests at the last full run: integration 1162 passed, card 122 passed. Ruff and mypy clean.

### Open issues (all under epic #36)

- **#77** capture missing warning types: thunderstorm done; severe weather, fire weather, frost,
  hazardous road, cyclone, tsunami still wait on a live warning (`human-gated`).
- **#78** hazard attribute: thunderstorm done; empty-description test done; the Severe weather box
  stays open until a live warning confirms the keyword list.
- **#92** check a live Detailed and a live very dangerous warning, including `next_issue` in
  Queensland, South Australian and Western Australian zones (`human-gated`).
- **#93** warning colours are inconsistent across tiles, icons and the activity graph.

### Known loose ends

- `test_growing_a_zone_over_a_second_district_shows_it_and_shrinking_drops_it` failed
  intermittently in full runs, passed alone and in later full runs. Cause not found.
- The Weather event also carries Coastal Hazard warnings, which say `severe` too and now get
  `hazards` and `hazard` as well (a surf warning says `surf`).
- Whether the more-info activity bars can follow severity is unconfirmed (it is in #93).
- No screenshots of the new tile in the card README.
- Old `unrated` rows remain in the dev recorder history (a true record; purging is optional and
  cannot be undone).
- The browser check of the new card build on the dev server is the user's to confirm.

### Dev instance facts

- The dev server loads the integration from the working tree (symlink), so an integration change
  needs `scripts/ha-dev.sh stop` then `start`. It listens on `127.0.0.1:8124`.
- The card is installed through the dev server's **Marketplace**, not HACS. A download can be a
  stale copy of the previous build; after an update, compare the served file's checksum with the
  repo's `dist/` (`/local/community/ha-bom-warnings-card/bom-warnings-card.js` against
  `ha-bom-warnings-card/dist/bom-warnings-card.js`). Then hard-refresh the browser.
- Tokens stay out of every file and repo (see the workspace `CLAUDE.md`).

## 4. How to resume

1. Pick a candidate from section 2 (or an open issue from section 3).
2. Read `docs/architecture.md` and `docs/warning-products.md` for the data flow and the real-file
   findings, and the repo `CLAUDE.md` for the rules (tests first, real captures only, commit only
   when asked).
3. For a design change, run the design-it-twice step before writing code, then work test first.
