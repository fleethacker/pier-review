# Physics/Load agent

The only path from any agent to physics. It computes nothing itself: lateral wind and current forces, line
geometry and bollard strain come from the modeling service (`modeling/`), which is plain Python. This folder
makes those calculations safe for agents to call and auditable afterwards.

**Status:** validated gateway, tool schemas, budgets, summaries and optional persistent ledger are implemented.
Modeling responses report their backend and qualification separately; real implementations can remain limited or invalid.

## What it provides

- `tools.py`: the tool catalog. One `ToolSpec` per modeling endpoint, with name, description, method, path, request
  schema and `async_job`. **The LLM tool definitions for every agent are built from this list.**
- `client.py`: typed async HTTP client for the modeling API (`MODELING_API_URL`).
- `toolkit.py`: `PhysicsToolkit(client, caller, plan_id)`.
    - Typed helpers: `analyze`, `envelope`, `recommend`, `berthing_tugs`, `sequence`, `exceedance`, `windows`,
      `hold_tugs`, `env_now`, `forecast`, `resolve_forecast`, `scenario`, `ship`, `berth`,
      `predict_trajectory`, `prediction` (read an immutable result).
    - Generic `call(name, input)` validates input, enforces limits, fills path params and polls jobs.
    - Every attempt is recorded with caller, plan id, request hash, `result_id`, status, duration and any error.
- `ledger.py`: in-memory or SQLite audit storage, accessed through `calls_for(plan_id=None)`.
- `summary.py`: `summarize(tool_name, output)` for deterministic LLM context.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/v1/tools` | `ToolSpec[]` |
| POST | `/api/v1/physics/tools/{tool_name}` | `ToolCallResult`: the ledger entry plus unchanged modeling output or a local error |
| GET | `/api/v1/physics/calls?plan_id=` | `ToolCall[]` |

## Agent integration

```python
from mooring_agents.physics import PhysicsToolkit, calls_for, summarize, tool_definitions

definitions = tool_definitions()
physics = PhysicsToolkit(client, caller="planner", plan_id=plan_id)
output = await physics.call("analyze_mooring", request)
context = summarize("analyze_mooring", output)
audit = calls_for(plan_id)
```

`tool_definitions()` returns one `{name, description, input_schema}` dictionary per `ToolSpec`. Schemas come
from `contract/modeling.openapi.yaml`, with references resolved: POST tools use their `request_schema`
component, and GET tools use path and query parameters. Provider-specific wrapping belongs in `shared/llm.py`.
Source and wheel distributions bundle the same contract so schema generation also works outside the checkout.

Invalid input never reaches modeling. Generic `call()` returns a correctable error, for example:

```json
{"error": {"code": "invalid_input", "message": "Invalid input for 'get_ship'; correct the listed fields.", "fields": [{"path": "$.class_id", "message": "'class_id' is a required property"}]}}
```

Local limit errors use the same `error.code` and `error.message` shape with codes `budget_exceeded` or
`timeout`. These errors are stored as JSON in the ledger entry's `error` string. Typed helpers enforce the
same checks and raise `ModelingError` with status 422, 429 or 504 respectively; modeling HTTP errors retain
their existing `ModelingError` behavior.

`summarize()` accepts JSON output or a typed response. It copies modeling's result ID, status and relevant
values, including the supplied governing element and utilization. It does no arithmetic, ranking or finding
counts; probabilities and numeric precision are preserved. Lists without a designated best item are
summarized using their explicitly labeled first item.

## Configuration and persistence

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `AGENTS_MAX_TOOL_CALLS` | `40` | Nonnegative maximum attempts per server-created agent operation (legacy gateway: per plan/caller). Zero rejects every attempt. |
| `AGENTS_TOOL_TIMEOUT_S` | `30` | Finite positive seconds for the HTTP operation, including job polling. |
| `AGENTS_LEDGER_DB` | unset | Optional SQLite file path; its parent directory must exist. `:memory:` is not supported. |

Direct gateway budgets without an operation id remain per `plan_id` and per caller: shared by all toolkit instances of the same caller for that plan, but the Planner's spending never consumes the Safety review's allowance (the budget exists to stop a runaway LLM loop, not the deterministic independent check). The Planner caps its iterations so its finishing calls fit, and over-budget requests surface as HTTP 429 (timeouts as 504). Invalid inputs and failed
calls consume the budget, and over-budget attempts are also logged. A call reserves its ledger entry before
HTTP, so concurrent calls cannot bypass the limit. With `plan_id=None`, the budget belongs to that toolkit
instance. A local timeout/cancellation stops polling and attempts to cancel an acknowledged modeling job; submission without an acknowledged job id cannot be cancelled remotely.
Limits are read at toolkit construction. Keep the ledger path fixed while the service is running.

Without `AGENTS_LEDGER_DB`, the ledger is held in memory for the process. With SQLite enabled, audit entries
and per-plan budget usage survive new toolkit instances and process restarts, and are shared across processes
using the same file. `calls_for(plan_id)` filters the active store; `calls_for()` returns all entries.

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
- Timeouts cover the full call, including job polling.
- Summaries contain only numbers present in the tool output.
- Ledger entries survive a restart when persistence is on.

API agent operations receive a server-created `operation_id`, retained on tool-call audit entries. Repeated safety
reviews and follow-up requests each get a fresh bounded allowance, while concurrent calls within one operation
share it atomically. The LLM and HTTP tool caller cannot choose/reset this scope. All entries remain linked to the
same plan for citations and ownership. Queue/rate limits still apply to incoming operations. With AGENTS_PERSIST=1,
the ledger defaults to MOORING_DB unless AGENTS_LEDGER_DB overrides it.
