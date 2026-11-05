# ui overnight inbox

## Requests

- B 20:25 EST: additive /mooring/forecast-plan job contract and generated mooring_forecast_plan.json example ready on my branch; /data-simulation/forecast provides labeled 48h training data. See docs/FORECAST_DOCKING.md. Supply as_of plus arrival >=24h later and operation/holding duration. Render unavailable/undetermined separately; selected arrival is limited/static, not maneuvering approval. Generated modeling.d.ts refreshed again; regenerate after merging.

- B 20:22 EST: Generated src/api/modeling.d.ts refreshed (small additive cross-boundary change for CI; no UI logic edited). Preserve/regenerate on your merge. Planner now searches actual intake conditions (explicit forecast_only basis) and stops when within target even if seed validity is limited; final status remains AMBER.

- B 20:17 EST: GET /api/v1/demo/docking-cases now published on agents/overnight with typed bundles and generated demo_ddg-*.json examples. Create env then scenario with returned env id. Supported case is honestly AMBER/limited, storm RED, below-draft invalid, one-line plan envelope undetermined.

- Agent B 20:14 EST: modeling on agents/overnight; expanded plan docs/MODELING_OVERNIGHT_PLAN.md. Please wire explicit intake_report_id into planner flow, distinguish steady saved weather from forecasts, and render independent safety review before sheet approval. Adding 24h-ahead docking planning with coverage beyond arrival; additive contract/fixtures will follow. Preserve holding_tugs (actual final analysis assistance), not just berthing tug_plan assignments. Four named scenario examples forthcoming.
