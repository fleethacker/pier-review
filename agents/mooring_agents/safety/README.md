# Safety/Brief agent

The last line of defense. It independently validates the Planner's plan, warns when gusts approach the plan's
working-load gust thresholds, and produces the Mooring Evolution Safety Sheet with rationale and safety
margins for human approval.

**Status:** real deterministic review and warning stream (`agent.py`) with optional guarded LLM narration; real sheet
assembly with HTML and PDF rendering (`sheet.py`).

## Inputs and outputs

- **Review in:** `SafetyReviewRequest`: `plan_id`, optional `intake_report_id`, `target_margin_pct_wll`.
- **Review out:** `SafetyReview`:
  - `checks[]`: id, pass/fail, severity, detail, cites;
  - `thresholds`: worst wind direction, governing element, limiting gust for the working-load limit, unavailable
    breaking gust, forecast max gust;
  - `verdict`: `ready_for_signature`, `revise` or `reject`.
- **Warnings out:** `GustWarning` SSE events, each with the percentage of the working-load gust limit for
  the current wind direction.
- **Sheet:** `SafetySheet` plus HTML render and approvals (pilot, First Lieutenant, CO). It locks on the first
  approval.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/v1/safety/reviews` | `202` job → `SafetyReview` |
| GET | `/api/v1/safety/reviews/{review_id}` | `SafetyReview` |
| GET | `/api/v1/safety/watch/{plan_id}?interval_s=&limit=` | SSE `warning` events |
| POST | `/api/v1/safety-sheets` | `201`; runs a review if `review_id` is omitted |
| GET | `/api/v1/safety-sheets/{id}` · `/render?format=html|pdf` | sheet · printable HTML or PDF (PDF returns 501 with setup instructions if Pango is missing) |
| POST | `/api/v1/safety-sheets/{id}/approvals` | sheet |

## Checks (deterministic, never decided by an LLM)

| Check | Fails as |
| --- | --- |
| `CITES-RESOLVE`: every cited `result_id` exists in modeling | RED |
| `CITES-IN-LEDGER`: every cite came from a Planner tool call logged for this plan | RED |
| `REANALYSIS-NOT-RED`: independent `analyze_mooring` at every original and supplemental intake condition | RED |
| `MARGIN`: highest utilization ≤ target | AMBER |
| `NO-RED-FINDINGS`: no RED NSTM 582 findings | RED |
| `GUST-THRESHOLD`: forecast max gust < 80% of the limiting gust (`limit_envelope`) | AMBER, or RED at ≥ 100% |
| `TUGS-FEASIBLE`: tug plan covers the required force | RED |
| `MST-WITHIN-SHIP`: forecast within the ship's MST | RED and verdict `reject` |

**Breaking threshold:** unavailable. A wind-speed square-root estimate cannot establish line or fender breaking
behavior. Only a future independently qualified modeling result can supply that threshold.

A supplemental intake adds to the original plan's conditions. Each check aggregates failures from every condition;
`PLAN-NOT-RED` prevents an independent review from clearing unresolved planner failures. Gust limits use the lowest
established solver limit in each direction across all assessed conditions; an unknown limit remains unknown. This is
a conservative selection of modeling results, not a new load calculation. Forecast coverage/MST checks consider both
reports. The sheet cites the supplemental report when supplied, and never invents a line-doubling procedure from a
high-utilization line number. Line-handling sequences remain draft/unreviewed until reviewed by a deck officer or pilot.

## Work remaining

Operationally qualified data, verified human approval authority, fresh-condition revalidation, and a validated breaking
model remain outside this demonstration. Archived approvals do not authorize a later operation. HTML is always available;
PDF needs the documented native rendering libraries.

## Guardrails

- Pass/fail and verdict are code. The LLM writes words only, and every number in them must come from a check or a
  cited result. Test this.
- The review re-runs physics itself; it never trusts the Planner's numbers without re-checking.
- The disclaimer stays on every sheet: decision aid only; the CO and pilot keep authority.

## Acceptance tests

- A plan with a fabricated `result_id` fails `CITES-RESOLVE`.
- A plan citing a result that isn't in its ledger fails `CITES-IN-LEDGER`.
- Forecast gusts above the plan limit make `GUST-THRESHOLD` RED and the verdict `revise`.
- A forecast beyond the ship's MST makes the verdict `reject`.
- The watch stream emits AMBER at ≥ 80% and RED at ≥ 100% of the limit for the current wind direction.
- The sheet contains go/no-go lines for 80% of limit, the limit, and the breaking threshold.

## PDF rendering setup

PDFs are rendered from the HTML sheet with WeasyPrint, which needs the Pango/GObject system libraries:
`brew install pango` on macOS, or `apt-get install libpango-1.0-0 libpangoft2-1.0-0` on Debian/Ubuntu
(including container images). Without them, `format=pdf` returns `501` with these instructions and HTML still
works; the tests accept either outcome.

Watch limits apply only to the assessed current/water-level/density and wind-basis conditions. Changed inputs emit `requires_recheck` with reasons and no threshold percentage; missing/poor inputs are RED. This compares facts and requests a new modeling assessment; it does not extrapolate limits in the agent. A provider/transport failure emits terminal `source_unavailable` (`SafetyWatchUnavailable`) with no invented measurements. Clients should show unavailable, then reconnect with backoff only when `retryable`. Negative watch parameters and unbounded zero-interval polling are rejected.

Sheets retain the analysis_result_id beside the line-load table, threshold_result_ids beside gust limits, all review-check citations, and prescribed holding_tugs separately from the berthing tug plan. Legacy sheets without holding_tugs report unknown assistance; an explicit empty list means none was prescribed. HTML/PDF escape citation text and label the evaluated snapshot time/source so it is not mistaken for live conditions.

New plans and sheets preserve `installed_at_water_level_mllw_ft` across original and supplemental review conditions. The printable sheet states that common tide and the no-implicit-tending assumption. Legacy sheets display unknown installation rather than inventing a value; archived plans should be regenerated before multi-tide comparison.

The printable sheet includes current flow-toward bearing, assessed MLLW water level, the intake forecast assessment and recorded wind averaging/gust/reference-height basis. When component provenance exists it prints source, quality, validity interval, actual issue and retrieval separately; unknown values stay unknown. All free text is escaped. Table headers repeat across printed pages. A printed timestamp describes assessed inputs, not a live freshness guarantee.
