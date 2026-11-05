# Deployment readiness (S21): what exists and what does not

**The modeling service is not ready for live use.** The controls below are implemented locally, pending review. This is not deployment approval or a completed S21 gate.

## Implemented controls

| Control | Configuration / implementation | Limits |
| --- | --- | --- |
| Durable results | `MOORING_DB`: SQLite WAL, numbered migrations | Results, resolved snapshots, scenarios, confirmed shared berths, batch frames, jobs and ownership; one process/host. Unset is in-memory and lost on restart. |
| Bounded jobs | `MOORING_WORKERS=2`, `MOORING_QUEUE=16`, `MOORING_JOB_DEADLINE_S` unset | Overload 429 with `Retry-After`. Cancellation/deadlines cooperative. Cancelled workers retain capacity until they exit. Queued/running jobs become failed on restart; not resumed. |
| API identity | `MOORING_API_KEYS` JSON object mapping principal names to unique bearer keys of at least 32 characters | Constant-time byte comparisons. Applies to HTTP except health, and WebSocket handshakes. No identity provider, roles or revocation service. |
| Ownership | SQLite ownership records plus worker context propagation | Jobs/status/SSE/cancellation, results, scenarios and simulator sessions separated by principal. Unknown or another owner's ids return 404 / WS 4404. Legacy unowned resources remain inaccessible when enforcement is enabled. |
| HTTP body cap | `MOORING_MAX_BODY_BYTES=1048576` | 413 before JSON parsing; proxy must also cap upload size/time and connections. Invalid limit configuration returns 503. |
| HTTP rate cap | `MOORING_RATE_PER_MINUTE=600` with auth; `0` (disabled) in demo mode | Fixed 60-second window per principal, injected clock in tests; 429 plus `Retry-After`. Process-local; counter resets on restart. Explicit 0 disables. |
| Simulation sessions | [Simulation control and limits](BERTHING_SIMULATION.md) | Bounded count/duration/commands; one controller; disconnect pauses; latest-frame backpressure. Ephemeral, one process. |
| Logs | JSON events on logger `mooring.operations` | Job ids, terminal state/duration/result id; stored result id, validity and reason codes. No bodies or credentials. Configure the logger at INFO to retain events. |
| Metrics | Authenticated `GET /api/v1/metrics` when auth is enabled | Queue depth, active jobs, saturation, cancellation, terminal-job counts and total duration seconds. `solver_failures` counts invalid stored results; failed jobs have a separate counter. Aggregate operational data, shared across authorized principals; no ids. In-process counters, no exporter/histograms. |
| Backup/restore | `python -m mooring.core.backup backup SOURCE NEW_BACKUP` / `restore BACKUP NEW_DATABASE` | SQLite online backup; integrity check; exclusive new target path, file mode 0600. Restore migrates the copy. Tests preserve result ids/hashes/snapshots/ownership and migrate v1 to current. |
| Capability statement | `/capabilities`, `/qualification`, `/rules` | Machine-readable limitations. Synthetic dynamics remain unqualified. |

## Authentication default and deployment boundary

**Unset credentials mean open local-demo mode**, not a secure deployment. Bind that mode to loopback. For a fail-closed configuration, set `MOORING_AUTH_REQUIRED=1` and supply `MOORING_API_KEYS` through a secret manager or protected environment (never commit keys). Required-but-missing or malformed key configuration returns 503; missing/incorrect bearer credentials return 401. `/api/v1/health` remains public. Production keys should be randomly generated with sufficient entropy; the length check does not establish entropy.

Clients use `Authorization: Bearer <key>` on HTTP and WebSocket handshakes. Native browser WebSocket clients cannot set arbitrary headers; a trusted gateway or a future secure session-cookie design is needed before enabling this mode for the current browser UI. The agents service forwards the validated caller bearer credential to modeling; configure matching principal/key mappings. Browser credential UX and trusted gateway integration remain unimplemented. The old telemetry key, if configured, is an additional check. No query-string credentials are accepted.

The agents application now has its own HTTP body/rate controls and resource ownership checks, described below. Middleware authenticates `/ws/env`, `/ws/alerts` and `/ws/telemetry` handshakes and carries ownership context. Alerts now preserve the selected scenario source on every frame and close explicitly on provider failure; their traffic limits/backpressure have not been hardened here. Environment and telemetry lifecycle controls remain separate. Only `/ws/sim` has the new command-rate/size and backpressure controls. Authorized principals can see aggregate metrics; deployment policy must decide whether that is appropriate.

## Agent job controls

The separate agents service now uses bounded real background jobs (`AGENTS_WORKERS=2`, `AGENTS_QUEUE=16`,
`AGENTS_JOB_TIMEOUT_S=300`), cancellation, terminal failure events and resumable SSE. Steps reflect actual
work. Default in-memory mode loses agent records on restart. Opt-in file-backed persistence now covers
plans/reports/sheets and terminal jobs as described below; interrupted work is failed, not resumed. This is not
operational readiness or a distributed worker system.

### Agents authentication and ownership

`AGENTS_API_KEYS` and `AGENTS_AUTH_REQUIRED` override the corresponding `MOORING_*` settings; absent overrides
inherit them. Unset keys/required flags keep open local-demo mode. Set required=1 for fail-closed deployment;
missing/malformed configuration returns 503, invalid/missing credentials 401. Health is public. Keys use
constant-time comparison. The validated incoming bearer credential is forwarded to modeling, including from
background workers; no shared service credential collapses caller identity.

Agent jobs, plans, intake reports, reviews, sheets, vision-job confirmation and tool-ledger reads are owner-scoped.
Cross-owner identifiers return 404; foreign intake reports cannot be attached to an owned plan. Legacy unowned
records are inaccessible with enforcement enabled. `AGENTS_MAX_BODY_BYTES=9000000` bounds the complete upload
before parsing, including chunked requests; the image limit remains 8 MB. `AGENTS_RATE_PER_MINUTE` defaults to
600 with authentication and 0 in local-demo mode; rejection is 429 plus Retry-After. Both controls are single-process.

Confirmed berth records join the shared modeling reference catalog; that catalog still needs an administrator
policy before deployment. Approval role/name fields are declarations, not verified organizational authority.
TLS, browser credential handling, role policy, key rotation and an independent security review remain blockers.
Ownership rows use the modeling core store; persistent ownership does not itself persist agent work objects.

## Backup and restoration rehearsal

Run the backup helper against the configured SQLite file; it uses SQLite's backup API, not a raw copy of a live WAL database. Choose an unused backup path. To recover, stop the service, restore into a **new** path, check the restored database and restart with `MOORING_DB` pointing to that path. Never overwrite the live file. Restrict access to backup files and directories; the helper does not encrypt, rotate, upload or automatically schedule backups. The CLI opens the source with the current database implementation; use a matching service version when taking backups. Test restoration in the deployment environment before relying on it.

## Still missing before live use

* TLS, trusted reverse proxy configuration, identity lifecycle/rotation, frontend authentication UX and gateway integration, role/admin policy, audit retention and independent security review.
* Multi-process/multi-host coordination, distributed jobs/sessions/rate limits and deployment load/abuse testing. CPU work shares the GIL; simulation may lag elapsed time under load.
* Production concurrency, upload time, idle connection, forecast freshness and numerical-work budgets measured against real workloads; per-principal job concurrency quotas.
* Provider freshness/error dashboards, solver-specific latency distributions, durable metrics/log export and alerts.
* Automated retention and backup scheduling, encryption/off-host copies and operational recovery rehearsal. `JobStore.purge` is manual; results and ownership rows are not automatically removed.
* Vessel/berth/rope/tug data qualification, supported operating envelopes, independent contact benchmarks and accountable human acceptance. Real implementation and passing tests supply none of these.

### Agent restart durability (overnight M3)

Opt-in `AGENTS_PERSIST=1` requires file-backed `MOORING_DB` and saves agent documents, approvals, completed job results,
terminal event history and ownership. Its audit ledger defaults to that database. Database migration 4 scopes job
recovery/retention by service, so restarting agents does not interrupt modeling jobs. Interrupted agent work fails
explicitly and must be resubmitted; active event history is not journaled. Completed plans contain no transport or
credential objects. Tests reopen a real SQLite file, retrieve the completed authenticated chain, preserve event ids
and tool-call audit, reject a different principal, and append concurrent approvals without losing entries.

One process per service/database is supported. No distributed jobs, automatic retention, verified approval roles,
or freshness revalidation of archived sheets is claimed. Existing local-demo
mode stays in memory. Back up an explicitly separate AGENTS_LEDGER_DB along with MOORING_DB if configured.

Shared berth references are immutable by ID: identical registration retries are idempotent, and conflicting replacements return HTTP409, including authenticated callers. Reads still expose the shared catalog; this is not a private asset registry. A revised berth needs a new ID, so another principal cannot silently replace the geometry/depth behind an existing scenario. Confirmed runtime entries use the same SQLite file when MOORING_DB is configured, and are included in its backup/restore. Unset storage remains ephemeral. Conflicting seed definitions on a later software update fail explicitly rather than replacing persisted geometry. Asset administration, retirement and engineering approval still require a separate workflow.

A 5 November 2026 local TCP probe exercised two separate service processes with required authentication and a shared file-backed database. Completed scenario, environment scenario, Intake, plan, review, approved sheet and analysis documents survived a full stop/restart unchanged. An online backup restored to a new path preserved the same documents, result hashes, ownership, event log and tool ledger; the approved sheet stayed locked. Safety monitoring resumed against the saved source. This exercised the seeded berth path, not persistence of runtime catalog additions, distributed operation or deployment durability guarantees.

A follow-up authenticated TCP probe used a newly registered berth rather than the seed ID. Full restart and backup restoration preserved its exact geometry, shared catalog visibility, immutable-ID conflicts and an AMBER/limited reanalysis. The same seven owned documents, hashes, terminal events, tool ledger, locked sheet and saved-source Safety watch survived. Unit tests also exercise a separate-process catalog read, database isolation and conflicting independent-process registrations. These are local persistence checks, not asset qualification or multi-process service support.

Agent upstream failures include malformed JSON and invalid typed modeling responses, not just HTTP error statuses. Safety monitoring emits its terminal RED source_unavailable event on those failures and does not fabricate a replacement snapshot or percentage. Malformed job responses fail explicitly and trigger best-effort cancellation; this does not provide exactly-once execution or automatic retry.

A one-hour authenticated local Safety SSE reconnect probe completed with 21,557 warnings across 663 connections from three clients. Every warning used the selected saved synthetic source; maximum observed inter-warning gap was 0.551 seconds, with no cross-stream stall. Service RSS at completion was approximately 82/105 MiB (modeling/agents). Temporary services stopped. This tests local source continuity and reconnect isolation with request-rate caps disabled; it does not establish deployment capacity, guaranteed latest-frame delivery or physical forecast accuracy.

A separate one-hour authenticated slow-reader probe completed with 14,557 saved-source warnings across 603 connections. One reader paused 300 seconds between reads; the other two continued with maximum observed gap 0.558 seconds. End-of-run service RSS was approximately 82/104 MiB. Temporary services stopped. This demonstrates no observed cross-stream stall in this local workload, with request-rate caps disabled. It does not guarantee latest-frame delivery: a delayed reader can receive older timestamped frames and must display their age.
