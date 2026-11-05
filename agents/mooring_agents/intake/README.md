# Environment/Intake agent

Turns raw and forecast environment data into what the Planner and Safety agents need: windows of concern,
a Mooring Service Type (MST) assessment and the conditions to design for.

**Status:** real (`agent.py`), with the original deterministic assessment in `core.py` and optional guarded LLM narration. Endpoints are unchanged; reports add optional narration provenance fields.

## Inputs and outputs

- **In:** `IntakeRequest`: a `scenario_id` (or `berth_id`, `ship_class_id`, `side_to`), `horizon_hours`, and an
  optional `env_scenario_id` for synthetic storms.
- **Out:** `IntakeReport` (`schemas.py`):
  - `current`: the latest environment snapshot.
  - `windows`: gust, sustained wind, current, wind shift and data gap windows, each with a severity and reason.
  - `mst`: the MST required by the horizon and whether it exceeds the ship's own MST.
  - `planning_conditions`: the worst case first. The Planner designs for `planning_conditions[0]`.
  - `berthing_windows`: low-current, low-gust times, from modeling `/windows/berthing`.
  - `data_quality`: stale, missing, flagged and mock data.
  - `summary`: a short narrative.
  - `tool_call_ids`: the ledger entries behind the report.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/v1/intake/reports` | `202` job → `IntakeReport` |
| GET | `/api/v1/intake/reports/{report_id}` | `IntakeReport` |

## How it works

1. **Get data through the Physics toolkit only** (`get_scenario`, `get_berth`, `get_ship`, `get_environment`,
   `get_forecast`, `berthing_windows`). Never call NOAA directly: normalization is modeling M1's job.
2. **Deterministic core (stays code, never LLM):**
    - Window detection with named thresholds. Current values: gust AMBER 25 kt, RED 34 kt; sustained wind
      AMBER 34 kt (MST I limit), RED 64 kt (MST II); broadside current AMBER 1 kt, RED 2 kt; wind shift
      ≥ 45°/h.
    - Broadside current is computed from the ship's heading at the berth.
    - The MST assessment uses `mooring.rules.nstm582.MST_LIMITS` (NSTM Table 582-1-1).
    - Planning conditions: worst gust, strongest current, and now.
3. **LLM layer:**
    - Write `summary` for a bridge audience.
    - Rank windows by operational impact (for example, a gust window during the planned berthing time).
    - Explain data-quality issues.
    - Optionally propose an extra planning condition, with a reason. The LLM may rank windows and append a forecast condition, but cannot delete or change any deterministic finding; the worst-gust planning condition stays first.

## Guardrails

- Every number in `summary` must appear in the report's structured fields. Test this.
- Thresholds live in one place with their NSTM reference; changing one needs a test.
- With no LLM configured, the agent still returns a complete report (deterministic summary).

## Acceptance tests

- A synthetic 64 kt / 2 kt MST II scenario produces RED gust windows and `mst_required = "II"`.
- A calm forecast produces no AMBER or RED windows.
- `planning_conditions[0]` is the worst gust in the horizon.
- Mock or stale data is reported in `data_quality`.
- Every tool call is in the ledger under the report id.
- The LLM summary contains no numbers absent from the report.

## Implementation and configuration

`thresholds.py` names the existing thresholds. MST wind/current limits reference
NSTM Table 582-1-1 through the canonical `MST_LIMITS` table. The gust alert policy,
wind-shift trigger, freshness cutoff and low-current berthing cutoff are local
policies retained from the mock, **not claimed NSTM numeric requirements**.
The core retains its original synthetic-series handling, summary, chronological
order, MST decisions and data-quality behavior. Golden reports captured before
extraction cover forecast, calm and synthetic-storm cases.

Narration uses `shared.llm.get_llm()` and `intake/prompts/summary.txt`. Configure
`AGENTS_LLM_PROVIDER=openai`, `AGENTS_LLM_MODEL` with your chosen model ID, and
`OPENAI_API_KEY` through the environment. The shared text-only adapter uses the
[OpenAI Responses API](https://developers.openai.com/api/docs/guides/text), with
storage disabled. It does not execute model tool calls. No model is selected
implicitly and no new dependency is required. Missing configuration returns the
core assessment without calling a provider, with the code-owned risk headline prepended. Incomplete replies, provider errors,
invalid proposals and a 30-second narration deadline also fall back to the core;
failures are logged without response payloads or credentials.

The first summary sentence is always written by code: highest window severity (or
no windows of concern), required MST, and whether that exceeds the ship's MST.
Unknown ship MST is stated explicitly. The model returns a private JSON proposal,
not an IntakeReport, with two to four further sentence templates, window impact
scores, quality explanations, and at most one forecast index with a reason.

Only weather wind/gust/current speeds, directions and water level; window start,
end, peak, severity and kind; typed MST fields (not reason prose); and planning
condition times may be referenced. Densities, observation age, data-quality
internals, IDs, tool calls and other metadata are excluded. The same environmental
allowlist applies to an extra planning snapshot. Code adds units (kt, °, ft, or
the window's own peak unit) and formats UTC times as HH:MMZ DD Mon. The model may
not write unit tokens, literal numbers, or common spelled-out quantities. It may
not write severity/reassurance terms (RED, AMBER, GREEN, safe, calm, low risk,
benign) or MST followed by Roman numerals outside fact references. These checks
apply to summary sentences, quality explanations and extra-condition reasons.
They constrain numerical provenance and risk language; they do not prove all
possible semantic claims in generated prose.

Every returned report sets `summary_source` to `llm` or `deterministic`.
`narration_note` is null on success, or a sanitized fallback reason such as
`provider timeout`, `guardrail: unit token` or `guardrail: fact reference`.
Both fields are optional for backward compatibility with older report payloads.
The successful LLM source refers to the additional sentences; the first sentence
is still owned by code. Fallback retains the deterministic summary after the
same headline.

Ranking sorts the original window objects stably by impact score; missing entries
get zero impact and are never dropped. Quality explanations are appended to the
original details; issue types, severities and station IDs stay intact. An optional
condition copies the indexed snapshot from the same forecast fetched by the core,
never from model-provided environment data. Existing conditions keep their order;
duplicates are ignored. The whole proposal is validated before applying any part.

`mock.py` remains only as a compatibility re-export because Planner and Safety
currently import its report store. Core, agent and compatibility imports share
that store. Agent responses report `backend="real"` even when narration falls back;
that describes the intake implementation, not whether modeling data is live.
Underlying mock/stale quality findings remain visible. The generated contract includes
the two optional provenance fields; all existing fields and endpoints remain.

Declared per-component quality and validity intervals are checked across current and forecast samples, independently of aggregate quality. Poor/out-of-interval inputs produce RED data-quality findings, suspect AMBER; unknown quality, unknown prediction issue time and source limitations remain INFO. Retrieval time is not an issue time or proof of freshness. Safety review consumes these findings and Safety watch rechecks when component quality changes.

The code-owned headline qualifies blocking input-quality findings even if no physical threshold windows are detected. This qualification is retained with or without model narration. Missing coverage continues to state that future exceedance is unknown.
