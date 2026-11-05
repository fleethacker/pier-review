# Contract semantics (S00a)

Additive rules for validity, diagnostics, inputs and metadata. Generated schemas are in [contract/](../contract/README.md); this page explains what the fields *mean*. New fields are optional; contradictory inputs described below now return 422. Unused additions are omitted from serialized responses so existing strict clients can still read legacy payloads.

## Validity

Every envelope may carry `validity: {state, reasons[], diagnostics}`.

| `state` | Meaning | Status rule |
| --- | --- | --- |
| `valid` | Inside the model's qualified domain | any |
| `limited` | Usable with stated caveats (needs at least one reason) | never GREEN (AMBER or RED) |
| `invalid` | Do not rely on the numbers (needs at least one reason) | RED |
| `unknown` / field absent | Not assessed. **Every response produced before S00a is unknown, never valid.** | any |

- The `Envelope` model rejects a contradictory status/validity pair, so it holds for both services. `status_with_validity()` lifts a computed status; `validity_state()` reads a model or JSON dict and returns `unknown` when validity is missing.
- Reason `code`s are `UPPER_SNAKE` strings with `affected_components` (element ids). Utilization stays in the result (`min_margin`, `pct_wll`); validity never rewrites it.
- `backend="real"`, a converged solver, or GREEN never implies `valid`.
- New real computations must always populate validity. Legacy or remaining mock responses that omit it stay unknown.
- Compatibility: unset `validity`, `manifest`, environment `metadata`, and per-line `condition`/`paid_out_unstretched_length_ft` are omitted, including nested payloads, stored results and job results. Unknown ledger `validity_state` is also omitted; parsing it still defaults to `unknown`. Existing optional fields retain their legacy null/default serialization. Explicitly populated additions are serialized and require upgraded consumers: deploy the S00a schemas to consumers before enabling producers that populate them. Current producers populate these additions where available; use consumers generated from the matching contract.

## Failure taxonomy

| Situation | Response |
| --- | --- |
| Malformed body, conflicting duplicated inputs, reference in the body that does not exist | `422` |
| Unknown id in the URL path | `404` |
| Data provider unavailable | documented service error (defined per provider packet) |
| Physically infeasible case | `200`, status RED, findings |
| Numerical failure, search timeout | `200` with `validity.state="invalid"` and a reason, or a failed job. A numerical failure is *not* proof that no equilibrium exists; a timeout means undetermined, not infeasible |

Unknown quantities are `null`. NaN and infinity are rejected on input (`422`) and never emitted.

## Solver diagnostics

`validity.diagnostics` (`SolverDiagnostics`): `converged` (null if no iterative solve), `iterations`, `residuals[]` (each with its own unit and `tolerance`, so surge, sway and yaw balances are judged independently), `active_constraints`, `rank` against `degrees_of_freedom`, `notes`.

## Input precedence

- The request body is authoritative. `scenario_id` is a label: it must exist (else 422) and must not contradict the body's `ship_class_id`, `loading`, `berth_id` or `config.side_to`. All conflicts are listed together. Editing lines against a saved scenario is allowed.
- `environment.wind_rel_ship_deg` / `current_rel_ship_deg` duplicate the true bearing plus ship heading. If supplied they must agree within 0.5 degrees, else 422.
- `ScenarioCreate`: `config.side_to` must equal `side_to`; `env_source.mode="scenario"` requires `env_scenario_id`, and the id is invalid with any other mode.
- `EnvScenarioCreate`: ramp fields only with `kind="ramp"` (and both required), replay fields only with `kind="replay"` (start required, end after start), gust not below sustained wind (except ramps, where the gust is a ratio).

## Line semantics

- `pretension_lbf`: initial tension. Legacy default: 2% of effective MBS, or 0 if `slack_ft > 0`.
- `slack_ft`: extra length beyond the straight-line distance. A positive `slack_ft` with positive `pretension_lbf` is rejected (a slack line carries no tension).
- `paid_out_unstretched_length_ft`: new; defines length directly, so it cannot be combined with `slack_ft`.
- `condition` (`wet`/`dry`): new; omitted means the request's `lines_wet` applies.
- The real mooring solver consumes explicit unstretched length and per-line wet/dry condition. Resolved configurations retain those inputs for rechecks at later tides; omitting installed lengths can create a new installation assumption.
- Tide sweeps apply only explicitly supplied tending actions. Reeving/chock routes and handling procedures still need qualified geometry and operational review; a static configuration does not establish them.

## Environment metadata

`EnvironmentSnapshot.metadata` (`EnvironmentMetadata`): `basis` (observation, prediction or scenario), `source`, `issued_at_utc`, `valid_from_utc`/`valid_to_utc`, `wind_averaging_s`, `gust_duration_s`, `wind_reference_height_m`, `current_depth_ft`/`current_bin`, `vertical_datum` (only MLLW accepted), `quality`, `age_s`, `original` (provider values as received). Absent means undocumented and remains a limitation. Current loads read wind basis metadata to select supported conversions and report unsupported or unknown bases. Quality and validity intervals can invalidate an assessment; component provenance also controls forecast availability. Metadata never supplies missing physical coefficients. Metadata timestamps and environment-scenario replay start/end timestamps must include an explicit UTC offset (including `Z`). Missing offsets return 422; different explicit offsets are compared by instant.

## Result manifest

`manifest` (`ResultManifest`): `resolved_inputs_hash`, `code_version`, resolved `records` (kind, id, revision), `environment_hash`, `numerical_settings`, `rng_seed`, `rng_model_revision`. `inputs_hash` preserves its legacy serialization: typed requests include existing defaults/nulls, while dictionary requests use sorted JSON. It is not a hash of raw HTTP bytes. Omitting inactive new fields preserves legacy typed hashes; populated additions participate in the hash. `resolved_inputs_hash()` hashes canonical key-sorted JSON after defaults and references are resolved. Mocks leave the manifest empty.

## Berth reference identity

`POST /berths` registers immutable shared reference data. Retrying identical data under the same ID returns the existing ID; different data under a seed or runtime ID returns HTTP409. Submit revised geometry, depth, ratings or provenance under a new `berth_id` and explicitly select it in a new/revised scenario. This prevents a catalog write from silently changing another saved scenario's physical reference. Vision confirmation preserves its draft ID, so changed data after confirmation requires a new draft. Runtime references persist with file-backed MOORING_DB and are included in backup/restore; unset storage remains ephemeral. Reads remain shared across principals. An installed seed definition that conflicts with a stored ID fails explicitly. This is not an asset administration or engineering approval workflow.

A `MooringConfig` requires unique `line_number` values. Duplicate IDs return422 at request validation because analysis rows and line-handling commands must identify one line unambiguously. Numbering gaps and an empty layout remain valid inputs; an empty layout still needs a physical determination from the solver. Inputs are never silently renumbered.

Berths require at least one depth sample, unique depth-profile x stations, unique IDs across fittings/fenders, and geographic latitude/longitude bounds. Malformed assets return422 before catalog registration. A single depth sample and unordered unique stations remain supported; these checks establish structural consistency, not hydrographic qualification.

## Recommendation assignments and installations

A recommendation candidate’s config retains assignment-only search semantics. Its optional resolved_config is the installation used by analysis_result_id, with explicit unstretched line spans and wet/dry condition. Use resolved_config plus candidate.tugs when rechecking that fixed installation at another tide; absence means the resolved installation is unavailable, not zero-length rope. This separates an assessed installation from assignments that advance-arrival planning can install at each arrival’s own water level. These modeled spans are not cutting lengths or handling instructions.

## Risk quantities and interpretation

Risk element percentiles named `tension_p50_lbf` and `tension_p95_lbf` report forces: line tension, fitting resultant or fender reaction. Fender exceedance is separately compared against rated energy in ft·lbf; its energy is not a force percentile. `p_exceed_mbs=null` on fittings/fenders means no MBS comparison exists, never zero probability.

Read validity and successful-sample counts before displaying probabilities. For compatibility, the legacy required aggregate scalar can be zero when no samples succeeded; with `n_valid=0`/invalid validity it is not an estimated zero risk. Bounds retain the unknown outcomes. Unqualified uncertainty models produce scenario statistics, not operational probabilities. `pointwise_only=true` is not an event probability over the requested horizon.
