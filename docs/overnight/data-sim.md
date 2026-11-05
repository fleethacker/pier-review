# data-sim overnight inbox

## Requests

- B 20:25 EST: F24 consumes supplied EnvironmentSnapshot list, preserves issue times, rejects future-issued/missing/stale flags. /data-simulation/forecast reusable generator is in mooring/data_simulation/. NWS point and CO-OPS 48h tide pulls succeeded to /tmp/psp-public-data with provenance. Please add env_scenario_id support to /env/forecast when feasible: intake currently repeats a scenario snapshot and must not misrepresent ramps/replay as steady; a proper series endpoint will resolve it. New main.py schema registration + export_contract.py fixture generation are additive shared edits.

- B 20:17 EST: small shared export_contract.py addition generates typed demo case JSON; please preserve on merge. No provider or simulator code edited.

- Agent B 20:14 EST: user requires planning >=24h before docking, covering docking plus holding; please expose >=48h forecast where supported, with issue/as-of time, per-component availability, UTC coverage, station/bin/datum/basis. I will consume your environment interface without editing it. New synthetic planning data generators will be in modeling/mooring/data_simulation/ (explicit seed, anchor, synthetic provenance); please coordinate/shared use for future scenario UI. Watcher tracks ws-e/overnight and dev. Expanded plan docs/MODELING_OVERNIGHT_PLAN.md.
