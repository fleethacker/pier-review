# Reviewed Safety Sheet consumer fixture

`reviewed_sheet.json` is an unchanged HTTP response captured from a real local
Intake → Planner → independent Safety review → Safety Sheet chain on base commit
`eaf0a6ae9ebfeba9f5b8ed6f6cda07e457c6c46e` plus the A11 reference/validity fixes
from `15fa143` (locally applied as `a278091`), on 2026-11-05. Both FastAPI services
ran through ASGI HTTP transports; the agents called the modeling service rather
than calculating physics. The fixture was not assembled from contract examples.

The source is `/api/v1/demo/docking-cases` case `ddg-supported-limited`: seeded
DDG-51 Flight IIA, Norfolk Pier 12 North and synthetic saved weather (4 kt wind,
5 kt gusts, 0.1 kt current, 1.8 ft MLLW water level). The Intake report's source is
`scenario`, not a live weather observation or forecast. Language models are off.
The sheet is **AMBER / limited**, because the reference data are estimated rather
than published/qualified and fitting heights are not corrected for loading.
The presence of an independent software review does not qualify those inputs or
establish NSTM compliance. This is demonstration evidence, not an operational
plan, navigational guidance, human approval or engineering certification.
The sheet intentionally has no approvals and remains unlocked.

Captured identities:

| Evidence | ID |
| --- | --- |
| Sheet, version 1 | `sheet_0548edb7c7084428` |
| Planner | `plan_31374482089344c8` |
| Independent Safety review | `review_288c7387cf9d48dc` |
| Mooring analysis | `res_6082fdd5f79b4f11` |

The self-contained SVG in `layout.svg` is the captured graphic. It embeds those
IDs and is bound to the assessed geometry/reference revisions and document data.
Consumers should render these saved bytes, including limited validity and
unavailable states, rather than capture the current editable canvas. This fixture
contains no live map, tokens, external graphics or operational ship information.
Its evidence IDs identify records from the capture process; they are not links to
a persistent remote service.

To regenerate deliberately, from the repository root with dependencies installed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=modeling:agents \
  .venv/bin/python agents/tests/fixtures/generate_reviewed_sheet.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=modeling:agents \
  .venv/bin/python -m pytest agents/tests/test_reviewed_sheet_fixture.py -q -p no:cacheprovider
```

The generator uses local ASGI transports and disables persistence/rate limiting;
it writes only the adjacent JSON fixture. Random record IDs and capture times
change between runs. Update this provenance record whenever replacing it, and
review the resulting HTML/PDF before publishing a new consumer fixture. The
focused tests validate the actual `SafetySheet` schema, saved SVG identity and
immutable rendering, and ensure changed environment data withhold the stale
graphic rather than drawing it as if it were assessed. The Safety Sheet has no
one-page limit; that requirement applies to the separate fielding brief.
