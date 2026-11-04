# modeling

Physics and ML modeling service (FastAPI, port 8000). Modules M1–M7 and M11–M13 from
[docs/PLAN.md](../docs/PLAN.md), organized by mooring phase.

```text
mooring/
  core/            shared types and plumbing
    schemas/         Pydantic models: the source of contract/modeling.openapi.yaml
    geometry.py      ship/berth frames and mooring line geometry (real)
    envelopes.py     result envelopes and the results store (shared with agents)
    jobs.py          async jobs and Server-Sent Events (shared with agents)
    units.py
  refdata/         seed YAML (ships, lines, berths, tugs) and loader (M2)
  rules/           NSTM 582 rule registry and checks (real)
  scenarios.py     saved scenarios (in memory)
  examples.py      example requests: API docs, contract/examples/, tests

  # Capabilities every phase uses
  environment/     M1 wind, current, water level            mock.py
  loads/           M3 wind and current forces               mock.py, helpers.py; entry point compute_loads
  tugs/            M6 tug sizing (shared by moored/berthing) mock.py; entry point size_tugs
  telemetry/       M13 ship sensor ingest                   mock.py

  # Phases
  moored/          Phase 1: ship alongside, lines fast
    mock/            solver.py (M4), risk.py (M5), tugs.py (holding tugs), optimizer.py (M7 line plan)
  berthing/        Phases 1c and 2: about two ship lengths off until all lines are fast
    mock/            tugs.py (assist tugs, berthing windows), sequence.py (M7 line sequence), simulator.py (M11)
  approach/        Phase 3: channel transit to the berth
    mock/            planner.py (route, under-keel clearance), simulator.py (M12)

modeling_api/
  backend.py       swap point: which implementation serves each module
  routers/         env, refdata, loads, telemetry, system (shared); moored, berthing, approach (phases)
  ws.py            WebSocket channels
tests/
```

## Replacing a mock

1. Write the real implementation **beside** the mock in the same package (for example `loads/ufc.py`,
   `moored/solver.py`), with the same function signatures.
2. Switch to it in one place:
    - cross-phase capabilities: the package's `__init__.py` entry point (`compute_loads`, `size_tugs`) and
      `modeling_api/backend.py`;
    - phase modules: `modeling_api/backend.py`.
3. Delete the mock once nothing imports it, set `backend="real"` in the envelopes it returns, and update
   `BACKENDS`.
4. Keep the API shapes unchanged. If you must change them, run `make contract` and tag the UI team on the PR.

Rule of thumb for imports: phase packages may import the shared capabilities and `core`; shared capabilities
never import a phase; phases don't import each other.

## What is real today

- Line geometry: lengths, lead angles, vertical angles, breast/spring/bow/stern classification.
- The NSTM 582 rule checks (`GET /rules` shows which are implemented).
- Seed ship wind areas, back-calculated so the mock drag model matches NSTM Table 582-3-1 at 50 kt.

Everything else (loads, load sharing, risk, tug sizing, optimizer, simulations) is placeholder logic with the
right shape. Line strengths, berths and tugs are mock data.
