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
  loads/           M3 wind and current forces               ufc.py, coefficients.py, service.py; entry point compute_loads
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
- M3 environmental loads: UFC Chapter 4 wind/current forces and yaw, with source-checked examples and bounded seed calibration.

Everything else (load sharing, risk, tug sizing, optimizer, simulations) is placeholder logic with the
right shape. Line strengths, berths and tugs are mock data.

## M3 implementation notes

`loads/ufc.py` implements UFC 4-159-03 (12 March 2020), Chapter 4. Constants and
engineering estimates live in `loads/coefficients.py`. The transverse wind fifth
harmonic and angle folding use the earlier UFC edition to resolve 2020 printing
errors; Figure 4-4 confirms the harmonic. UFC flow-toward angles are converted
explicitly from the API's clockwise wind-from and current-toward bearings.

Sustained winds are converted from 60 to 30 seconds using approximate synoptic
curve readings from Figure 3-5 (1.31/1.25). Gust duration is absent from the API;
supplied gusts are assumed to be 30-second winds at 10 m. This assumption must be
checked for real data feeds. Shielding scales wind forces and moments equally.

Missing ship geometry uses documented estimates in response assumptions. Current
uses salt-water viscosity at 15 C with the requested density. Depth below draft
is clamped to T/d=1 with an AMBER finding; ground contact is not modeled. Reynolds
numbers below 10,000 use a numerical floor in the skin-friction expression to
avoid its singularity; this is an engineering regularization, not a UFC rule.
Speeds above 1.5 m/s generate a current-model applicability warning. Yaw assumes
CG at midships and a level keel; LHD uses carrier coefficients by analogy.

The load envelopes and stored results report `backend="real"`. The global HTTP
header and API introduction still say mock: their implementation in
`modeling_api/main.py` is outside this chunk's allowed file scope. Other modules
remain mock even though they now consume UFC loads.

Calibration changes only lateral wind area; hull and frontal areas retain their
original values. All 16 peak force magnitudes pass the NSTM ±10% check and all
areas remain within ±25%. Peak bearings are 76°/284° (DDG, CG, CVN) and 77°/283°
(LHD), outside the requested NSTM bearing tolerance; those 16 tests are explicit
expected failures. The DDG shallow-water current/wind ratio is approximately 3.84.
No UFC coefficient was tuned to address the bearing discrepancy.
