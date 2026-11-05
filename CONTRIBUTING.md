# Contributing

This repo holds the mooring assistant: `frontend/` (UI), `modeling/` (physics and ML service), `agents/` (LLM agent service) and `contract/` (the generated API specs they share). The [README](README.md) explains the layout. Read the [master plan](docs/MASTER_PLAN.md) for current priorities, ownership and coordination rules before picking up work.

The repository is now [fleethacker/pier-review](https://github.com/fleethacker/pier-review). Existing checkouts should update their remote:

```bash
git remote set-url origin https://github.com/fleethacker/pier-review.git
git fetch origin
```

New checkouts: `git clone --branch dev https://github.com/fleethacker/pier-review.git`.

## Branches

| Branch | Purpose | Who writes to it |
| --- | --- | --- |
| `main` | Stable, demo-ready code. Only updated from `dev` by pull request. | PRs from `dev` only |
| `dev` | Integration branch. Explicitly use `--base dev` for feature PRs, regardless of GitHub's default. | PRs from feature branches |
| feature branches | One piece of work each, branched off `dev`. | You |

CI runs for pull requests and pushes to both `dev` and `main`. On 5 November 2026, GitHub reported `main` as the default and both branches as unprotected. A repository administrator still needs to configure protection if available; follow these rules regardless:

- Never push directly to `main` or `dev`.
- Never force-push `main` or `dev`.
- Don't delete `main` or `dev`.

## Branch naming

`<area>/<item-id>-<short-description>`, lowercase with hyphens (for example `agents/a1-demo-check`). Use your workstream from the master plan as the area:

| Area | Workstream | Example |
| --- | --- | --- |
| `ws-a` | Data and platform (M1, M2, M13, API skeleton) | `ws-a/noaa-replay-feed` |
| `ws-b` | Physics core (M3, M4, rules) | `ws-b/ufc-wind-loads` |
| `ws-c` | Risk and tugs (M5, M6) | `ws-c/gust-monte-carlo` |
| `ws-d` | Planning (M7, in `modeling/`) | `ws-d/optimizer-search` |
| `ws-e` | Dynamics (M11, M12) | `ws-e/berthing-3dof` |
| `agents` | Agent work in `agents/`; start the description with the agent name | `agents/planner-llm-loop` |
| `ui` | UI work in `frontend/` | `ui/pier-canvas` |
| `docs` | Documentation only | `docs/update-plan` |
| `fix` | Bug fixes outside a workstream | `fix/env-timezone` |

## Day-to-day workflow

```bash
# 1. Start from an up-to-date dev
git checkout dev
git pull --ff-only origin dev

# 2. Create your branch
git checkout -b agents/a1-demo-check

# 3. Commit as you go, then push
git push -u origin agents/a1-demo-check

# 4. Always specify the integration base
gh pr create --base dev --fill
```

If `dev` moves while your PR is open, update your branch with `git pull origin dev` (merge) and resolve any conflicts on your branch.

## Pull requests into `dev`

- Get at least **one approval** from another team member before merging.
- Keep PRs small: one master-plan item per PR. Include its ID in the title, for example `A1: four-case demo checks`.
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
- `agents/` must reach physics only through the Physics agent's `PhysicsToolkit` (which calls the modeling API), never by importing `mooring` physics or mock code. See [agents/README.md](agents/README.md) for the rules every agent follows.

## Releasing `dev` into `main`

1. Confirm the milestone's dependencies in the [master plan](docs/MASTER_PLAN.md). Run `make test`, `make contract-check`, the UI typecheck/lint/test/build and `make demo-check-readiness`. Baseline demo success alone does not satisfy release acceptance.
2. Rehearse a clean checkout on the actual demo target using the [deployment procedure](docs/DEPLOYMENT_READINESS.md). Record the exact commit, target, checks and unresolved limits.
3. Open a PR with `gh pr create --base main --head dev --title 'Release: <milestone>' --body-file <release-notes-file>`. Include qualification limits, source labels, known omissions and verification evidence; see the [release draft](docs/RELEASE_NOTES.md).
4. Get at least one approval and green CI, then merge using a **merge commit**, never squash or rebase. Tag the merged `main` commit with the agreed milestone version and publish the same release notes. Do not tag unrehearsed feature-branch code as a release.

## What not to commit

- **NSTM 582 itself:** not the PDF, and not long verbatim passages. It carries a Distribution B and export-control notice. Cite paragraph and table numbers, and keep only the numeric values the code needs.
- **Secrets:** API keys, tokens and `.env` files. Use environment variables.
- **Non-public Navy data:** for example real pier fitting layouts or ship drawings, unless the team has confirmed they may be shared here.
- **Large data files:** NOAA history and CBOFS downloads. Commit the scripts that fetch them, not the data.
