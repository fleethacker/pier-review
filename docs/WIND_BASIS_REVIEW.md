# Wind-basis source check — 5 November 2026

Reviewed the official [UFC 4-159-03, 12 March 2020](https://www.wbdg.org/FFC/DOD/UFC/ufc_4_159_03_2020.pdf), section 3-8.1 and Figure 3-5, printed pages 36–37. The figure was inspected visually, not inferred from PDF text extraction.

The stationary-wind design basis is 30 seconds at 10 metres. Figure 3-5 gives separate synoptic and hurricane curves relative to the hourly mean. It is a graph, not a tabulated conversion; choosing a curve requires a regime assumption. The existing 1.31/1.25 synoptic readings remain approximate and are identified as such in `loads/coefficients.py` and response assumptions.

No new conversion factors were introduced. Extending support needs a documented curve-selection policy and independently reviewed digitization or a primary-source analytic expression. Height normalization also needs an explicit source and applicability policy; the ship-area height correction must not be mistaken for a sensor-height conversion. This check is not physical qualification.

Current implementation: `loads/validity.py` accepts the supported metadata bases, discloses the legacy assumption when metadata is absent, and marks unsupported duration/height conversions limited. Unsupported sustained averaging still uses the documented legacy ratio; that is an approximation, not a validated conversion. Public adapters must preserve unknown averaging, gust duration and sensor height instead of supplying convenient defaults.
