# data-sim overnight inbox

## Requests

- B 20:44 EST: watcher found ws-a/dc0-provider-plumbing a820492. Review notes for providers.py: stale age is measured before retries/backoff, so a response can exceed max_stale_s yet be returned with an understated age; recompute clock.now() at fallback. Shared clients also need serialized/rate-limited access or explicit per-request ownership before threaded API use. Please address before integration; no changes made on your branch.

- B 20:43 EST: intake now reads GET /env/scenarios/{id}; only kind=steady is repeated. Ramp/replay returns current-only RED missing coverage until your scenario forecast interface exists. Forecast completeness now requires coverage to current+horizon, so the old mock hourly-rounded start can leave a partial final hour; please anchor forecast coverage to request time or extend endpoint. Future-sample missing/unavailable flags propagate.

- B 20:25 EST: F24 consumes supplied EnvironmentSnapshot list, preserves issue times, rejects future-issued/missing/stale flags. /data-simulation/forecast reusable generator is in mooring/data_simulation/. NWS point and CO-OPS 48h tide pulls succeeded to /tmp/psp-public-data with provenance. Please add env_scenario_id support to /env/forecast when feasible: intake currently repeats a scenario snapshot and must not misrepresent ramps/replay as steady; a proper series endpoint will resolve it. New main.py schema registration + export_contract.py fixture generation are additive shared edits.

- B 20:17 EST: small shared export_contract.py addition generates typed demo case JSON; please preserve on merge. No provider or simulator code edited.

- Agent B 20:14 EST: user requires planning >=24h before docking, covering docking plus holding; please expose >=48h forecast where supported, with issue/as-of time, per-component availability, UTC coverage, station/bin/datum/basis. I will consume your environment interface without editing it. New synthetic planning data generators will be in modeling/mooring/data_simulation/ (explicit seed, anchor, synthetic provenance); please coordinate/shared use for future scenario UI. Watcher tracks ws-e/overnight and dev. Expanded plan docs/MODELING_OVERNIGHT_PLAN.md.
