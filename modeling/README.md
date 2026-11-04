# modeling

Physics and ML modeling service (FastAPI, port 8000). Modules M1–M7 and M11–M13 from [docs/PLAN.md](../docs/PLAN.md).

```text
mooring/
  core/
    schemas/      Pydantic models: the source of contract/modeling.openapi.yaml
    geometry.py   ship/berth frames and mooring line geometry (real)
    envelopes.py  result envelopes and the results store (shared with agents)
    jobs.py       async jobs and Server-Sent Events (shared with agents)
    units.py
  rules/nstm582.py  NSTM 582 rule registry and checks (real)
  refdata/          seed YAML: ships, lines, berths, tugs (estimated or mock values; see provenance)
  mock/             mock implementation of every module
modeling_api/
  backend.py      swap point: which implementation serves each module
  routers/        one file per module group
  ws.py           WebSocket channels
tests/
```

## Replacing a mock

1. Build the real module beside the mock (for example `mooring/loads/ufc.py`) with the same function signatures
   as `mooring/mock/forces.py`.
2. Point the module at it in `modeling_api/backend.py` and update `BACKENDS`.
3. Set `backend="real"` in the envelopes it returns.
4. Keep the API shapes unchanged. If you must change them, run `make contract` and tag the UI team on the PR.

## What is real today

- Line geometry: lengths, lead angles, vertical angles, breast/spring/bow/stern classification.
- The NSTM 582 rule checks (`GET /rules` shows which are implemented).
- Seed ship wind areas, back-calculated so the mock drag model matches NSTM Table 582-3-1 at 50 kt.

Everything else (load sharing, risk, tug sizing, optimizer, simulations) is placeholder logic with the right
shape. Line strengths, berths and tugs are mock data.
