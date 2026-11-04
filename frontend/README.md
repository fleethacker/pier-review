# frontend

UI team's workspace: the 2D pier canvas, live dashboard and safety sheet views. The framework and tooling are the
UI team's call; nothing outside this folder depends on them.

## Build against the contract, not the Python code

- Specs: [`../contract/modeling.openapi.yaml`](../contract/modeling.openapi.yaml) and
  [`../contract/agents.openapi.yaml`](../contract/agents.openapi.yaml). Conventions and the typical call flow are in
  [`../contract/README.md`](../contract/README.md).
- Example request bodies: [`../contract/examples/modeling/`](../contract/examples/modeling/).
- Mock servers: from the repo root, `make install` once, then `make mock`. Modeling runs at
  `http://localhost:8000/api/v1` (docs at `/docs`) and agents at `http://localhost:8001/api/v1`. CORS is open for
  local development.

Generate TypeScript types from the specs, for example with
[openapi-typescript](https://github.com/openapi-ts/openapi-typescript):

```bash
npx openapi-typescript ../contract/modeling.openapi.yaml -o src/api/modeling.d.ts
npx openapi-typescript ../contract/agents.openapi.yaml -o src/api/agents.d.ts
```

Regenerate them whenever `contract/` changes on `dev`.

## Things to show from the responses

- `status` (GREEN, AMBER, RED) on every envelope, line, fitting and finding.
- `backend: "mock"` and `provenance.confidence` (`mock`, `estimated`, `vision`): show a banner or badge so nobody
  mistakes placeholder numbers for real ones.
- `findings[].reference` (the NSTM 582 paragraph) next to each warning.
- `result_id`s cited in agent rationale, linked to `GET /results/{result_id}` on the modeling service.
