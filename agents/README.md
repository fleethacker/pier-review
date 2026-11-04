# agents

LLM agent service (FastAPI, port 8001): M8 berth map analysis, M9 planning agent and M10 safety sheet from
[docs/PLAN.md](../docs/PLAN.md).

Agents **never compute physics**. They call the modeling service over HTTP through `clients.py`
(`MODELING_API_URL`, default `http://localhost:8000/api/v1`) and cite every number by its `result_id`.

```text
mooring_agents/
  schemas/      Pydantic models: the source of contract/agents.openapi.yaml
  clients.py    typed HTTP client for the modeling service
  tools.py      the agent's tool catalog (each tool = one modeling endpoint); served at GET /tools
  mock/         deterministic mock agents (no LLM yet)
    planner.py  plan -> evaluate -> adjust loop over modeling tools, SSE events, follow-up answers
    vision.py   berth image -> draft berth + detections + confirmation questions
    sheet.py    safety sheet assembly, approvals, HTML rendering
  backend.py    swap point: which implementation serves each agent
  api/main.py   endpoints
tests/          run the modeling app in-process behind an HTTP transport
```

## Replacing a mock with an LLM agent

1. Keep the function signatures in `mock/planner.py` and `mock/vision.py`, and the SSE event types.
2. Turn `tools.py` into LLM tool definitions. Input schemas come from `contract/modeling.openapi.yaml`.
3. Keep the guardrails from the plan: every number in rationale cites a `result_id`, the agent cannot override a
   RED finding, and humans approve the sheet.
4. Swap the import in `backend.py`. Model choice and API access (direct or through an AI gateway) are open
   decisions in the plan.
