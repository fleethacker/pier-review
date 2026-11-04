# Contributing

This repo holds the mooring assistant: `frontend/` (UI), `modeling/` (physics and ML service), `agents/` (LLM agent service) and `contract/` (the generated API specs they share). The [README](README.md) explains the layout. The plan and module list are in [docs/PLAN.md](docs/PLAN.md). Read both before picking up work.

## Branches

| Branch | Purpose | Who writes to it |
| --- | --- | --- |
| `main` | Stable, demo-ready code. Only updated from `dev` by pull request. | PRs from `dev` only |
| `dev` | Default branch. All work is integrated here. | PRs from feature branches |
| feature branches | One piece of work each, branched off `dev`. | You |

`main` has no technical protection (GitHub branch protection isn't available on this repo's plan), so these rules depend on everyone following them:

- Never push directly to `main` or `dev`.
- Never force-push `main` or `dev`.
- Don't delete `main` or `dev`.

## Branch naming

`<area>/<short-description>`, lowercase with hyphens. Use your workstream from the plan as the area:

| Area | Workstream | Example |
| --- | --- | --- |
| `ws-a` | Data and platform (M1, M2, M13, API skeleton) | `ws-a/noaa-replay-feed` |
| `ws-b` | Physics core (M3, M4, rules) | `ws-b/ufc-wind-loads` |
| `ws-c` | Risk and tugs (M5, M6) | `ws-c/gust-monte-carlo` |
| `ws-d` | Planning (M7, in `modeling/`) and agents (M8–M10, in `agents/`) | `ws-d/safety-sheet-render` |
| `ws-e` | Dynamics (M11, M12) | `ws-e/berthing-3dof` |
| `ui` | UI work in `frontend/` | `ui/pier-canvas` |
| `docs` | Documentation only | `docs/update-plan` |
| `fix` | Bug fixes outside a workstream | `fix/env-timezone` |

## Day-to-day workflow

```bash
# 1. Start from an up-to-date dev
git checkout dev
git pull

# 2. Create your branch
git checkout -b ws-b/ufc-wind-loads

# 3. Commit as you go, then push
git push -u origin ws-b/ufc-wind-loads

# 4. Open a PR into dev (dev is the default base)
gh pr create --base dev --fill
```

If `dev` moves while your PR is open, update your branch with `git pull origin dev` (merge) and resolve any conflicts on your branch.

## Pull requests into `dev`

- Get at least **one approval** from another team member before merging.
- Keep PRs small: one module or one feature. Name the module in the title, for example `M3: transverse wind force (UFC 4-159-03)`.
- Describe what changed, how you tested it, and anything the UI team needs to know.
- Run `make test` before asking for review, and add tests for new physics, rules or agent behavior.
- Resolve all review comments before merging.
- Delete your branch after it merges.

### API contract changes

`contract/` is what the UI team builds against, and what the agents service relies on, so contract changes need extra care:

- `contract/` is generated. After changing a schema or endpoint, run `make contract` and commit the result in the same PR. `make test` fails if it's stale.
- Tag a reviewer from each team that consumes the changed spec (UI for either spec; agents for `modeling.openapi.yaml`).
- Adding fields is fine. Renaming or removing fields is a breaking change: discuss it with the team first.
- Follow the conventions in [contract/README.md](contract/README.md) (units in field names, wind *from* / current *toward*, berth and ship frames).
- `agents/` must reach physics only through the modeling API, never by importing `mooring` physics or mock code.

## Releasing `dev` into `main`

1. Make sure `dev` passes its tests and the demo scenario works end to end.
2. Open a PR from `dev` into `main` titled with the milestone, for example `Release: G2 Phase 1 demo`.
3. Get at least one approval, then merge. Don't squash, so `main` keeps the same history as `dev`.

## What not to commit

- **NSTM 582 itself:** not the PDF, and not long verbatim passages. It carries a Distribution B and export-control notice. Cite paragraph and table numbers, and keep only the numeric values the code needs.
- **Secrets:** API keys, tokens and `.env` files. Use environment variables.
- **Non-public Navy data:** for example real pier fitting layouts or ship drawings, unless the team has confirmed they may be shared here.
- **Large data files:** NOAA history and CBOFS downloads. Commit the scripts that fetch them, not the data.
