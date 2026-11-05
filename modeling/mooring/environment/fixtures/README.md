# Environment provider fixtures

Fixtures are small, legally shareable provider responses used only for offline
tests and replay. Keep each provider in its own directory. JSON recorded by
`scripts/record_provider_fixture.py` is key-sorted and compact so identical
responses are byte-identical across clocks and machines.

Record only the minimum response needed for a test. Do not commit credentials,
request headers, bulk history, or restricted data. The recorder requires an
explicit `MOORING_FIXTURE_RECORD=1` opt-in and is never run by CI.
