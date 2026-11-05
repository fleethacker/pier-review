# Berth Map agent

Turns an image of a berth (satellite, chart, NAVFAC berthing plan, photo of a sketch) into a draft `Berth` and a
recommended line placement. A human confirms the draft before anything uses it.

**Status:** mock (`mock.py`). It returns the seed Pier 12 North berth as the "extraction", with synthetic detections
and confirmation questions.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| POST | `/api/v1/berth-vision/analyze` (multipart: `image`, `metadata` JSON) | `202` job → `VisionResponse` |
| POST | `/api/v1/berth-vision/{job_id}/confirm` | `201` `BerthCreated` (saved to modeling) |

## Pipeline to build (from docs/PLAN.md, M8)

1. When the berth is charted, take the pier outline and depths from NOAA ENC vector data. Geometry should be
   deterministic where it can be.
2. A vision LLM extracts fitting positions and types, camels and obstructions, with a confidence per item.
3. Snap detections to the pier face. Fill unknown capacities from NSTM Table 582-5-6 defaults, marked `estimated`.
4. Call `recommend_config` through the Physics toolkit for line placement.

## Guardrails

Nothing is saved until the user confirms. Low-confidence items are flagged `needs_confirmation`, and capacities
the image can't show are always marked as estimates.
