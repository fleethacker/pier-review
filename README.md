# Pier Review

Two applications, each self-contained. They share a repository and nothing else: neither builds, tests or runs the other.

| | What it is | Start here |
|---|---|---|
| [`mooring/`](mooring/) | **Pier Review**, the mooring assistant: a backup camera for ships — predicted path, mooring and docking planning with a safety sheet, berthing and port-transit simulation, and mission storyboarding. A modeling service, an agent service, a shared contract and a web app. | [mooring/README.md](mooring/README.md) |
| [`exercise/`](exercise/) | **Exercise simulator**: replay a naval exercise in 3D on a Mapbox map — ships, aircraft, missiles, mines and sensors, with a storyboard that narrates the run and a red team that asks how often it comes out that way. The simulation runs in the browser; a small service keeps the shared scenario library. | [exercise/README.md](exercise/README.md) |

```bash
# the mooring assistant
cd mooring && uv sync --all-packages && make mock      # services on :8000 and :8001
cd mooring/frontend/packages/web && npm ci && npm run dev   # UI on :4000

# the exercise simulator
cd exercise && npm install && npm run dev              # UI on :4100
cd exercise/server && uv sync && uv run uvicorn exercise_api.main:app --port 8200   # optional
```

Branch from `dev` and open pull requests with `--base dev`. Each application has its own checks; run the ones for the
application you changed. Instructions for AI agents working here are in [CLAUDE.md](CLAUDE.md) (and the identical
[AGENTS.md](AGENTS.md)).

Repository: [fleethacker/pier-review](https://github.com/fleethacker/pier-review).
