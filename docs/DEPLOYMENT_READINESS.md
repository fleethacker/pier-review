# Deployment readiness (S21): what exists and what does not

**The modeling service is not ready for live use.** The controls below are implemented locally, pending review. This is not deployment approval or a completed S21 gate.

## Implemented controls

| Control | Configuration / implementation | Limits |
| --- | --- | --- |
| Durable results | `MOORING_DB`: SQLite WAL, numbered migrations | Results, resolved snapshots, scenarios, batch frames, jobs and ownership; one process/host. Unset is in-memory and lost on restart. |
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

Clients use `Authorization: Bearer <key>` on HTTP and WebSocket handshakes. Native browser WebSocket clients cannot set arbitrary headers; a trusted gateway or a future secure session-cookie design is needed before enabling this mode for the current browser UI. The agents service also needs credential forwarding before an authenticated end-to-end deployment. The old telemetry key, if configured, is an additional check. No query-string credentials are accepted.

HTTP controls apply to the modeling application, not the separate agents server. Existing `/ws/env`, `/ws/alerts` and `/ws/telemetry` handlers are unchanged; middleware authenticates their handshakes and carries ownership context, but their traffic limits/lifecycle have not been hardened here. Only `/ws/sim` has the new command-rate/size and backpressure controls. Authorized principals can see aggregate metrics; deployment policy must decide whether that is appropriate.

## Agent job controls

The separate agents service now uses bounded real background jobs (`AGENTS_WORKERS=2`, `AGENTS_QUEUE=16`,
`AGENTS_JOB_TIMEOUT_S=300`), cancellation, terminal failure events and resumable SSE. Steps reflect actual
work. It still lacks persistent plan/report/sheet storage and authenticated resource ownership in this packet;
modeling SQLite durability does not cover those objects. Restart loses agent records. This is not operational
readiness or a distributed worker system.

## Backup and restoration rehearsal

Run the backup helper against the configured SQLite file; it uses SQLite's backup API, not a raw copy of a live WAL database. Choose an unused backup path. To recover, stop the service, restore into a **new** path, check the restored database and restart with `MOORING_DB` pointing to that path. Never overwrite the live file. Restrict access to backup files and directories; the helper does not encrypt, rotate, upload or automatically schedule backups. The CLI opens the source with the current database implementation; use a matching service version when taking backups. Test restoration in the deployment environment before relying on it.

## Still missing before live use

* TLS, trusted reverse proxy configuration, identity lifecycle/rotation, frontend and agents authentication integration, role/admin policy, audit retention and independent security review.
* Multi-process/multi-host coordination, distributed jobs/sessions/rate limits and deployment load/abuse testing. CPU work shares the GIL; simulation may lag elapsed time under load.
* Production concurrency, upload time, idle connection, forecast freshness and numerical-work budgets measured against real workloads; per-principal job concurrency quotas.
* Provider freshness/error dashboards, solver-specific latency distributions, durable metrics/log export and alerts.
* Automated retention and backup scheduling, encryption/off-host copies and operational recovery rehearsal. `JobStore.purge` is manual; results and ownership rows are not automatically removed.
* Vessel/berth/rope/tug data qualification, supported operating envelopes, independent contact benchmarks and accountable human acceptance. Real implementation and passing tests supply none of these.
