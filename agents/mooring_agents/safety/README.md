# Safety/Brief agent

The last line of defense. It independently validates the Planner's plan, warns when gusts approach the plan's
working-load and breaking thresholds, and produces the Mooring Evolution Safety Sheet with rationale and safety
margins for human approval.

**Status:** mock review (`mock.py`) and live warnings, deterministic, no LLM; real sheet assembly and HTML
rendering (`sheet.py`).

## Inputs and outputs

- **Review in:** `SafetyReviewRequest`: `plan_id`, optional `intake_report_id`, `target_margin_pct_wll`.
- **Review out:** `SafetyReview`:
  - `checks[]`: id, pass/fail, severity, detail, cites;
  - `thresholds`: worst wind direction, governing element, limiting gust for the working-load limit, estimated
    breaking gust, forecast max gust;
  - `verdict`: `ready_for_signature`, `revise` or `reject`.
- **Warnings out:** `GustWarning` SSE events, each with the percentage of the working-load and breaking limits for
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
| GET | `/api/v1/safety-sheets/{id}` · `/render?format=html` | sheet · HTML (`pdf` returns 501 for now) |
| POST | `/api/v1/safety-sheets/{id}/approvals` | sheet |

## Checks (deterministic, never decided by an LLM)

| Check | Fails as |
| --- | --- |
| `CITES-RESOLVE`: every cited `result_id` exists in modeling | RED |
| `CITES-IN-LEDGER`: every cite came from a Planner tool call logged for this plan | RED |
| `REANALYSIS-NOT-RED`: independent `analyze_mooring` at the worst intake condition | RED |
| `MARGIN`: highest utilization ≤ target | AMBER |
| `NO-RED-FINDINGS`: no RED NSTM 582 findings | RED |
| `GUST-THRESHOLD`: forecast max gust < 80% of the limiting gust (`limit_envelope`) | AMBER, or RED at ≥ 100% |
| `TUGS-FEASIBLE`: tug plan covers the required force | RED |
| `MST-WITHIN-SHIP`: forecast within the ship's MST | RED and verdict `reject` |

**Breaking threshold:** the mock estimates it as the working-load limiting gust × √(design factor), because line
tension grows with wind speed squared. Replace this with a direct calculation from modeling once the solver is
real: ask for the gust at which the governing line reaches its breaking strength.

## Work remaining

1. **LLM brief:** a short narrative for the bridge (what governs, what to watch, when to act), written only from
   check results and cited numbers. It goes in `SafetyReview.summary` and the sheet.
2. **Direct breaking-load threshold** from modeling (see above), and per-direction thresholds on the sheet.
3. **Watch hardening:**
    - suppress repeats (only warn when severity rises);
    - escalate when wind direction moves into a weaker sector;
    - include forecast-ahead warnings from the intake report ("gusts reach 90% of limit at 16:00Z").
4. **PDF rendering** of the sheet.
5. **Sheet versioning:** re-reviewing a locked sheet creates version n+1.

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
