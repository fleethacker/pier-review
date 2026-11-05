# Environment provider fixtures

Fixtures are small, legally shareable provider responses used only for offline
tests and replay. Keep each provider in its own directory. JSON recorded by
`scripts/record_provider_fixture.py` is key-sorted and compact so identical
responses are byte-identical across clocks and machines.

Record only the minimum response needed for a test. Do not commit credentials,
request headers, bulk history, or restricted data. The recorder requires an
explicit `MOORING_FIXTURE_RECORD=1` opt-in and is never run by CI.

`replay_sample.json` is a synthetic recorded-format training fixture, not a NOAA observation archive. The bundled
replay service reports `metadata.basis=scenario` and an explicit synthetic source label. Provider-shaped unit-test
fixtures likewise establish parser behavior, not observation provenance or operational qualification.

`env_availability_partial.json` is the deterministic D1 contract example. It contains status and provenance only,
not environmental measurements. The missing current is unavailable rather than represented by a numeric zero.

`recorded_real/noaa-coops-norfolk-2026-01-01-v1/` is the offline, recorded-real replay package. Its manifest binds the
normalized observations to the three source fixtures by SHA-256, declares berth applicability and exact coverage, and
retains acquisition and engineering limitations. The package revision hashes the complete manifest (apart from the
revision field itself), so changing applicability or policy metadata invalidates it. Build or verify it without network access:

```bash
uv run --all-packages python scripts/build_recorded_replay.py
uv run --all-packages python scripts/build_recorded_replay.py --check
```

`make demo-check` runs the integrity check and then serves this package through an explicit `recorded_real` replay
scenario. It asserts the NOAA source and observation basis independently for wind, current and water level. No archived
NWS response is available in this repository, so the offline package does not claim forecast wind or waves.

The package covers 2026-01-01 00:00–00:54 UTC and never loops or extrapolates. It is labeled `replay` with an
`observation` basis. It is demonstration replay data, not a forecast or operational qualification.

`ndbc/` contains short, provider-native excerpts from NOAA/NDBC realtime wave products for stations 44099 and 44014,
retrieved on 2026-11-05. The excerpts retain the original headers, units, timestamps, missing-value tokens, total sea,
provider partitions, density bins and alpha1 direction convention. They are parser fixtures, not a complete observation
archive; the production adapter keeps full fetched rows and marks undocumented sample bounds/timestamp position unknown.
The native `data_spec` separation-frequency value `9.999` is the provider's missing sentinel and stays missing. NDBC
directions are directions waves come from, clockwise from true north. These offshore stations are never relabeled as
Pier 12 measurements or berth forcing.
