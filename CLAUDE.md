# Instructions for AI agents in this repository

The repository holds two applications, each self-contained:

- **`mooring/`** — the mooring assistant: the modeling and agent services, the contract, the web app, the docs and the
  plan. Everything below refers to this one unless it says otherwise, and its paths are relative to `mooring/`.
- **`exercise/`** — the exercise simulator: a standalone naval-exercise simulator with its own page, build, tests and
  small service. It depends on nothing in `mooring/`. Its own instructions are in `exercise/README.md`; its checks are
  `npm run typecheck && npm run lint && npm test -- --run && npm run build` in `exercise/`, and `uv run pytest -q` in
  `exercise/server`.

Read these before doing anything else, every session:

1. **Product north star — a backup camera for ships.** Like a car's backup camera, the goal is to predict and draw where a ship will go
   over the next minutes from its current state, the commands in force and current conditions (wind, current, tide), with
   an honest uncertainty corridor and contact warnings. Every change should make that prediction more correct, more honest
   about its limits, faster to refresh, or easier to read — or serve the supporting pieces listed in the plan (mooring
   planning and safety sheet, berthing and port-transit simulation, mission storyboarding).
   Initial transit-based S7 prediction and its overlay are merged (#14), with limited validity. Full state fidelity,
   berthing prediction, coastline and calibrated uncertainty remain open; see mooring/docs/PREDICTION.md.
   Details: [mooring/docs/MASTER_PLAN.md — North star](mooring/docs/MASTER_PLAN.md#north-star-a-backup-camera-for-ships).
2. **The plan.** [mooring/docs/MASTER_PLAN.md](mooring/docs/MASTER_PLAN.md) is the single source of priorities, owners and sequence. If you
   work for a team member (Snyder, Kori, Cruz, Bixler), use its Execution ownership table for the lead, collaborators,
   reviewer and dependencies. Work only on that person's items/files unless the user explicitly assigns a cross-team task.
   Read the current dev plan and merged PRs before restarting an item; historical packet IDs are not new assignments.
3. **Rules that do not bend** (master plan §8): never fabricate data; missing is null, never zero; keep `limited`/synthetic
   labels visible; never delete, skip or weaken tests to go green; agents never compute physics; no secrets in the repo;
   everything must run offline with `AGENTS_LLM_PROVIDER=none`. Predictions are decision support for a demonstrator, never
   navigational guidance.
4. **Git:** branch from `dev`, open PRs with `gh pr create --base dev` (the default branch is `main`), never push to `dev`
   or `main`, never force-push. Schema changes are additive; regenerate with `make contract` (and `npm run types` in
   `mooring/frontend/packages/web`); never hand-edit `mooring/contract/`.
5. **Checks before a PR:** in `mooring/`, `make test` and `make contract-check`, and in
   `mooring/frontend/packages/web` `npm run typecheck && npm run lint && npm test -- --run && npm run build`. For a
   change under `exercise/`, run that application's own checks instead (see above).
