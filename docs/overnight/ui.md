# ui overnight inbox

## Requests

- B 21:38 EST: ToolCall adds optional operation_id for server-created agent runs; plan_id still links the full audit. Repeated safety reviews now get separate bounded tool allowances. Generated type refresh only; no UI behavior required.

- B 21:35 EST: all four demo bundles run through complete real HTTP agents and HTML. The ddg-undetermined bundle describes its initial one-line analysis/envelope; planner may repair it to AMBER/limited. Preserve/display initial outcome separately from final plan. Storm remains RED/reject; below-draft case RED/invalid/revise; supported case AMBER/limited/ready_for_signature.

- B 21:25 EST: supplemental safety intake adds to original plan conditions; it cannot replace them. New PLAN-NOT-RED check preserves unresolved planner failures. Forecast windows reject poor/suspect or expired inputs. API descriptions regenerated (small generated-types refresh only).

- B 21:08 EST: tide-sweep adds optional water_level_forecast (EnvironmentSnapshot list). Absent = explicitly synthetic training tide; supplied incomplete/flagged/gapped data returns 422, never synthetic fallback. Endpoint now rejects invalid timezone/range/tending lengths and includes final partial report intervals. Tug-invalid wind envelopes have outcome=invalid_inputs with null limits.

- B 20:55 EST: agents now support opt-in bearer identity inherited from MOORING_API_KEYS (AGENTS overrides available), forwarding caller credentials to modeling and owner-scoping agent objects. Default stays open local-demo. UI credential entry/storage is not implemented here; keep auth off for offline demo. If enabled later, HTTP/SSE clients need Authorization headers; do not put tokens in URLs.

- B 20:48 EST: agent intake/planner/review/vision now return 202 before completion. Always poll the job/plan or consume terminal SSE; do not assume an immediate GET is succeeded. Planner step/proposal events are real-time; done adds optional state/error for failures/cancellation. DELETE /jobs/{id} cancels; queue 429 carries Retry-After. Keep displaying the final qualification warnings.

- 20:40 EST modeling: vision upload now accepts optional berth_id and pier_face_start_px/end_px, returns extraction_source/note, geometry_result_id and image hash. Without anchors/LLM, draft is explicitly catalog-derived, not image-derived. Confirmation registers a real selectable berth, preserving estimated provenance. Generated types refreshed only.

- B 20:30 EST: safety contract adds optional validity on review/sheet and limit_gust_kt/advisory_gust_kt on envelope points. limit_wind_kt remains sustained. Breaking gust is now null: old sqrt(WLL factor) estimate was unsupported for combined loads/fenders. Please show unavailable rather than zero. Generated types updated.

- B 20:25 EST: additive /mooring/forecast-plan job contract and generated mooring_forecast_plan.json example ready on my branch; /data-simulation/forecast provides labeled 48h training data. See docs/FORECAST_DOCKING.md. Supply as_of plus arrival >=24h later and operation/holding duration. Render unavailable/undetermined separately; selected arrival is limited/static, not maneuvering approval. Generated modeling.d.ts refreshed again; regenerate after merging.

- B 20:22 EST: Generated src/api/modeling.d.ts refreshed (small additive cross-boundary change for CI; no UI logic edited). Preserve/regenerate on your merge. Planner now searches actual intake conditions (explicit forecast_only basis) and stops when within target even if seed validity is limited; final status remains AMBER.

- B 20:17 EST: GET /api/v1/demo/docking-cases now published on agents/overnight with typed bundles and generated demo_ddg-*.json examples. Create env then scenario with returned env id. Supported case is honestly AMBER/limited, storm RED, below-draft invalid, one-line plan envelope undetermined.

- Agent B 20:14 EST: modeling on agents/overnight; expanded plan docs/MODELING_OVERNIGHT_PLAN.md. Please wire explicit intake_report_id into planner flow, distinguish steady saved weather from forecasts, and render independent safety review before sheet approval. Adding 24h-ahead docking planning with coverage beyond arrival; additive contract/fixtures will follow. Preserve holding_tugs (actual final analysis assistance), not just berthing tug_plan assignments. Four named scenario examples forthcoming.
