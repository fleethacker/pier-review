# Physics/Load agent

The only path from any agent to physics. It computes nothing itself: lateral wind and current forces, line
geometry and bollard strain come from the modeling service (`modeling/`), which is plain Python. This folder
makes those calculations safe for agents to call and auditable afterwards.

**Status:** real gateway and ledger; the physics behind it is still mock in `modeling/` (M3 is being built now).

## What it provides

- `tools.py`: the tool catalog. One `ToolSpec` per modeling endpoint, with name, description, method, path, request
  schema and `async_job`. **The LLM tool definitions for every agent are built from this list.**
- `client.py`: typed async HTTP client for the modeling API (`MODELING_API_URL`).
- `toolkit.py`: `PhysicsToolkit(client, caller, plan_id)`.
    - Typed helpers: `analyze`, `envelope`, `recommend`, `berthing_tugs`, `sequence`, `exceedance`, `windows`,
      `env_now`, `forecast`, `scenario`, `ship`, `berth`.
    - Generic `call(name, input)` for LLM tool use; it fills path params, polls jobs and passes the body through.
    - Every call is appended to the **ledger** with caller, plan id, request hash, `result_id`, status and duration.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/v1/tools` | `ToolSpec[]` |
| POST | `/api/v1/physics/tools/{tool_name}` | `ToolCallResult`: the ledger entry plus the modeling response, unchanged |
| GET | `/api/v1/physics/calls?plan_id=` | `ToolCall[]` |

## Work remaining

1. **LLM tool schemas:** generate JSON Schema tool definitions from `contract/modeling.openapi.yaml` for each
   `ToolSpec` (`request_schema`, plus path and query params for GET tools). Expose them as `tool_definitions()`
   for the Planner, Intake and Safety agents.
2. **Input validation before the call:** validate LLM-produced inputs against the schema and return a structured
   error the LLM can correct. Count it in the ledger as `error`.
3. **Persistence:** the ledger is in memory. Add an optional SQLite store and keep `calls_for()` as the API.
4. **Limits:** per-plan call budget and timeout (configurable), so a looping LLM can't flood modeling.
5. **Result summaries:** a compact, deterministic text summary of each tool result for the LLM context (governing
   element, max % of working load, status), so the LLM doesn't need the full JSON. Pure code, no LLM.

## Guardrails

- No arithmetic on physics quantities in this folder beyond formatting. If a number is needed, it's a modeling
  endpoint.
- Tool names are stable: the ledger, plan rationale and safety checks refer to them.
- Adding a tool means adding a modeling endpoint first.

## Acceptance tests

- Every `ToolSpec` resolves to a real path in `contract/modeling.openapi.yaml` with the right method.
- Generated tool schemas validate the example requests in `contract/examples/modeling/`.
- An invalid LLM input returns a structured error and is logged.
- The budget stops a plan after N calls.
- Ledger entries survive a restart when persistence is on.
