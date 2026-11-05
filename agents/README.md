# agents

LLM agent service (FastAPI, port 8001). Agents reason and explain; **they never compute physics**. Every number
comes from the modeling service through the Physics agent's logged toolkit and is cited by its `result_id`.

## The agents

| Folder | Agent | Job | Status |
| --- | --- | --- | --- |
| [`intake/`](mooring_agents/intake/README.md) | Environment/Intake | Environment data → windows of concern, MST assessment, conditions to design for | real core + optional LLM summary |
| [`physics/`](mooring_agents/physics/README.md) | Physics/Load | Logged tool gateway to modeling: forces, line geometry, bollard strain. No LLM, no math | real gateway |
| [`planner/`](mooring_agents/planner/README.md) | Planner | Proposes tugs, lines and sequence; runs physics; iterates to acceptable margins | real deterministic core; optional guarded LLM |
| [`safety/`](mooring_agents/safety/README.md) | Safety/Brief | Independent review, gust warnings vs working-load and breaking limits, Safety Sheet | real review and sheet; guarded optional narration |
| [`vision/`](mooring_agents/vision/README.md) | Berth Map | Berth image → draft berth and line placement, human-confirmed | real deterministic core; optional guarded LLM |

Each folder's README is that agent's plan and spec. Each folder holds `schemas.py` (its API types), `mock.py` (the
placeholder where still needed) and the real agent beside it. Intake's mock is only a compatibility import.

## How they work together

```text
            ┌──────────────┐  IntakeReport   ┌──────────────┐  AgentPlan   ┌───────────────┐
 UI ──────▶ │ Intake agent │ ──────────────▶ │ Planner      │ ───────────▶ │ Safety/Brief  │ ──▶ Safety Sheet
            └──────┬───────┘                 └──────┬───────┘              └──────┬────────┘     + approvals
                   │                                │                             │  live gust warnings (SSE)
                   └──────────────┬─────────────────┴─────────────┬───────────────┘
                                  ▼                               ▼
                       Physics agent: tool catalog + ledger  ──HTTP──▶  modeling/ (:8000)
```

API flow: `POST /intake/reports` → `POST /agent/plans` (with `intake_report_id`) → `POST /safety/reviews` →
`POST /safety-sheets` → `POST /safety-sheets/{id}/approvals`, with `GET /safety/watch/{plan_id}` for live warnings.
Full spec: `contract/agents.openapi.yaml`.

## Layout

```text
mooring_agents/
  shared/llm.py   provider-agnostic LLM interface; optional OpenAI text provider
  physics/        client.py, tools.py, toolkit.py (ledger), schemas.py
  intake/ planner/ safety/ vision/   README.md, schemas.py, mock.py (+ safety/sheet.py)
  schemas.py      re-exports every agent's schemas for the contract
  backend.py      swap point: which implementation serves each agent
  api/            main.py, state.py, routers/ (one per agent)
tests/            run modeling in-process behind an HTTP transport
```

## Rules for every agent

1. Physics only through `PhysicsToolkit`, never by importing `mooring` physics or mock code, and never by doing
   arithmetic on physics quantities.
2. Pass/fail, thresholds, budgets and stop rules are code. The LLM chooses moves and writes words.
3. Every number in LLM-written text must come from a cited tool result or a structured field. Test it.
4. LLM access only through `shared/llm.py`. Provider, model and keys come from environment variables. With no LLM
   configured, agents fall back to their deterministic behavior so tests and demos run offline.
5. Keep the API shapes. If one must change, run `make contract` and tag the UI team.
6. Replace a mock by adding the real agent beside it and switching one import in `backend.py`.

### Optional Anthropic provider

Set `AGENTS_LLM_PROVIDER=anthropic`, `AGENTS_LLM_MODEL` to an explicitly selected model, and
`ANTHROPIC_API_KEY` in the process environment. No model is selected implicitly. `none` remains the default.
The Messages adapter supports text, image inputs and tool proposals; the existing code-owned fact, severity,
unit and plan-adjustment guards still apply. Truncated, refused, malformed and unsupported responses fall
back through each agent's deterministic path. Tests use a fake transport; live provider quality is unverified.

Protocol references: [Messages](https://platform.claude.com/docs/en/api/http/messages/create),
[images](https://platform.claude.com/docs/en/build-with-claude/vision), and
[versioning](https://platform.claude.com/docs/en/api/versioning). The adapter pins API version `2026-10-21`
and omits sampling parameters, which that version removes. The handoff's `claude-api` skill was not installed;
implementation was checked against these primary docs instead.

### Agent jobs and progress

Intake, planner, safety review and vision uploads acknowledge work with `202`, then run on a bounded
worker pool. Poll the returned job URL until terminal; a `202` is not a completed result. Planner SSE
steps/proposals are emitted when computed. Terminal `done` includes optional `state`/`error`; failed or
cancelled plans cannot be reviewed or turned into a safety sheet. Both SSE endpoints accept `Last-Event-ID`.

`AGENTS_WORKERS=2`, `AGENTS_QUEUE=16`, and `AGENTS_JOB_TIMEOUT_S=300` bound work. Saturation returns
`429` with `Retry-After`. `DELETE /api/v1/jobs/{job_id}` cancels; late results are discarded. Toolkit
checkpoints and async deadlines are cooperative: a cancelled worker retains capacity until it exits.
The legacy `MOCK_JOB_DELAY_S` does not control agent jobs. Shutdown fails unfinished work. Agent job,
plan/report/sheet stores remain process-local in this packet; a restart loses them. Modeling result
persistence and the optional tool ledger do not make those agent objects durable.

### Opt-in authentication

Agent HTTP requests inherit `MOORING_API_KEYS` / `MOORING_AUTH_REQUIRED`, or use `AGENTS_API_KEYS` /
`AGENTS_AUTH_REQUIRED` overrides. Unset means open local-demo mode; required without valid configuration
fails closed. Use matching principal/key mappings across agents and modeling: the validated caller token is
forwarded, never replaced with a shared service identity. Jobs, plans, reports, reviews, sheets, vision jobs and
ledger reads are owner-scoped. `/health` is public. `AGENTS_MAX_BODY_BYTES` defaults to 9000000 (8 MB image
plus multipart/metadata); `AGENTS_RATE_PER_MINUTE` defaults to 600 with auth, otherwise 0. See
[deployment boundaries](../docs/DEPLOYMENT_READINESS.md); this is not a role system or deployment approval.

### Optional durable agent state

Set `AGENTS_PERSIST=1` and a file-backed `MOORING_DB` before starting the agents service to retain intake reports,
completed plans, reviews, sheets/approvals, vision drafts, plan messages, job results and ownership. The tool-call ledger
uses that same file unless `AGENTS_LEDGER_DB` explicitly selects another file (back up both in that case). Unset/default
`AGENTS_PERSIST=0` retains local-demo memory behavior. Invalid persistence configuration fails startup.

Use one agents process per database. Jobs are scoped separately from modeling jobs: restarting agents cannot fail
modeling work. Completed job event logs retain their SSE ids. Interrupted jobs become failed, never resumed; clients
must fetch job status after a restart (in-flight event history is not journaled). Plan records omit live toolkits,
HTTP clients and credentials; follow-up requests use the caller's current credentials. A restored plan does not make
its forecast current: rerun intake and independent review before a new operation.

This is single-host restart durability, not a distributed scheduler or deployment qualification. There is no automatic
retention policy; protect and back up the database, and do not purge referenced modeling results. Confirmed runtime
berths still require a separate durable reference-data/admin workflow. Role/name approval fields remain declarations,
not verified command authority. Concurrent approvals are appended under the store lock without changing sheet content.

## PDF rendering on macOS

If WeasyPrint reports missing GObject/Pango libraries although Homebrew has installed them, start the stack with the library directory in the child process environment:

```sh
make mock PDF_LIBRARY_PATH=/opt/homebrew/lib
# Or for the combined API/UI launcher:
PDF_LIBRARY_PATH=/opt/homebrew/lib ./app.sh
```

Use `/usr/local/lib` instead for an Intel Homebrew installation, and install `pango` first if absent. The Makefile assigns `DYLD_FALLBACK_LIBRARY_PATH` inside the agents recipe: macOS system launchers can strip a `DYLD_` variable set outside `make`. Passing the plain `PDF_LIBRARY_PATH` make variable preserves the requested path until that assignment. This does not change the renderer or bypass its checks; it makes the installed libraries discoverable. See [WeasyPrint missing-library troubleshooting](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#missing-library). The documented make command was exercised through real TCP services on 5 November 2026: the supported intake→plan→review→approved-sheet flow returned PDF HTTP 200. An outer DYLD assignment instead returned 501 on this macOS host. Without the libraries, the API returns explicit 501 and HTML remains available for browser printing.

Optional narration rejects model-authored operational approval/readiness/suitability and proceed/go-ahead claims, as well as uncited numbers, units and risk labels. A rejected narrative falls back to code-owned text. These are conservative lexical guards, not proof of every natural-language implication; structured code results and independent review remain authoritative.
