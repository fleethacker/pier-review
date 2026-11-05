# Instructions for AI agents in this repository (Codex, GPT and other agents; same content as CLAUDE.md)

Read these before doing anything else, every session:

1. **Product north star — a backup camera for ships.** Like a car's backup camera, we predict and draw where a ship will go
   over the next minutes from its current state, the commands in force and current conditions (wind, current, tide), with
   an honest uncertainty corridor and contact warnings. Every change should make that prediction more correct, more honest
   about its limits, faster to refresh, or easier to read — or serve the supporting pieces listed in the plan (mooring
   planning and safety sheet, berthing and port-transit simulation, mission storyboarding).
   Details: [docs/MASTER_PLAN.md — North star](docs/MASTER_PLAN.md#north-star-a-backup-camera-for-ships).
2. **The plan.** [docs/MASTER_PLAN.md](docs/MASTER_PLAN.md) is the single source of priorities, owners and sequence. If you
   work for a team member (Snyder, Kori, Cruz, Bixler), do only that person's items and files, in priority order.
3. **Rules that do not bend** (master plan §8): never fabricate data; missing is null, never zero; keep `limited`/synthetic
   labels visible; never delete, skip or weaken tests to go green; agents never compute physics; no secrets in the repo;
   everything must run offline with `AGENTS_LLM_PROVIDER=none`. Predictions are decision support for a demonstrator, never
   navigational guidance.
4. **Git:** branch from `dev`, open PRs with `gh pr create --base dev` (the default branch is `main`), never push to `dev`
   or `main`, never force-push. Schema changes are additive; regenerate with `make contract` (and `npm run types` in
   `frontend/packages/web`); never hand-edit `contract/`.
5. **Checks before a PR:** `make test`, `make contract-check`, and in `frontend/packages/web`
   `npm run typecheck && npm run lint && npm test -- --run && npm run build`.
