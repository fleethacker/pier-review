# Deployment readiness (S21): what exists and what does not

**The modeling service is not ready for live use.** This page lists the controls that exist today, the ones that do not, and the limits of what is implemented. It is not an approval.

## Exists

| Control | Where | Notes |
| --- | --- | --- |
| Durable results | `MOORING_DB` (SQLite, WAL, one process) | Write-once results, resolved-input snapshots, saved scenarios, job records. Numbered migrations; a newer database is refused. Default is in-memory (lost on restart). |
| Bounded work | `MOORING_WORKERS` (2), `MOORING_QUEUE` (16), `MOORING_JOB_DEADLINE_S` (unset) | Overload returns 429 with `Retry-After`. Cancellation and deadlines are cooperative; running threads are not killed. |
| Restart recovery | `JobStore.recover` | Queued/running work becomes `failed: interrupted by restart`. Not resumed. |
| Retention | `JobStore.purge(older_than_s)` | Must be called by an operator; no scheduler. Stored results are never deleted. |
| Telemetry key | `MOORING_TELEMETRY_KEY` | Optional shared key on `POST /telemetry/batch`. Unset means open (local demo only). Batch limit `MOORING_TELEMETRY_MAX_BATCH` (500). |
| Capability statement | `GET /capabilities`, `GET /qualification`, `GET /rules` | Machine-readable qualification, limitations and blockers. |

## Does not exist (required before anything beyond the local demo)

* Authentication and authorization for jobs, results, scenarios and (future) simulation sessions; separation of user and session data.
* Request-size and rate limits beyond the telemetry batch cap; per-user concurrency limits.
* Metrics and structured logs for result/job ids, validity failures, provider freshness, solver failure rate, queue saturation, cancellations.
* Backup/restore, migration rehearsal and cleanup procedures; multi-process or multi-host safety (SQLite is single host).
* Load tests and deployment-specific concurrency, retention and forecast-age limits measured from real workloads.
* A supported-capabilities matrix by ship, loading, environment, data quality and phase (the current matrix is by capability only).
* Accountable human acceptance for intended use. Neither passing tests nor `backend: real` supplies it.

## Local single-host limits

Workers are threads in one process. CPU-bound solves share the GIL, so heavy concurrent jobs slow each other. A process crash loses in-flight work. SSE streams resume with `Last-Event-ID` against the in-process job log only.
