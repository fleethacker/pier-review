# Environment/Intake agent

Turns raw and forecast environment data into what the Planner and Safety agents need: windows of concern,
a Mooring Service Type (MST) assessment and the conditions to design for.

**Status:** mock (`mock.py`), deterministic, no LLM. Endpoints and schemas are live.

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
3. **LLM layer (to build):**
    - Write `summary` for a bridge audience.
    - Rank windows by operational impact (for example, a gust window during the planned berthing time).
    - Explain data-quality issues.
    - Optionally propose an extra planning condition, with a reason. The LLM may add or reorder, but it can't
      delete a deterministic window or soften a severity.

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
