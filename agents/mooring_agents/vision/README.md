# Berth Map agent

Turns an image of a berth (satellite, chart, NAVFAC berthing plan, photo of a sketch) into a draft `Berth` and a
recommended line placement. A human confirms the draft before anything uses it.

**Status:** real draft pipeline (`agent.py`), always limited/unconfirmed. Deterministic geometry comes from the
selected catalog berth (`metadata.berth_id`). Without it, an explicitly labeled Norfolk demo template is returned;
no image location is inferred. No LLM is needed. Optional image proposals require a configured provider, a supported
image, scale and two pier-face pixel anchors. Modeling projects detected centers; the model cannot supply ratings.

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


## Current contract and limits

`metadata` adds optional `berth_id`, `pier_face_start_px`, `pier_face_end_px`. Scale remains in `georef.scale_ft_per_px`.
With no extraction, detection boxes/centers are null and confidence is zero, never fabricated image coordinates.
All detections require confirmation, even high-confidence model proposals. Extracted fittings are projected onto the
straight face with unresolved setback and suspect condition; ratings come from estimated catalog templates,
not the image. Unknown kinds and out-of-face geometry are rejected.

Response includes extraction source/reason, image hash, modeling geometry result ID and optional catalog-preview
recommendation result ID. Changed image geometry requires confirmation before line search; a catalog preview is
not analysis of modified geometry. Confirmation preserves the draft ID, cannot overwrite another berth, and cannot
promote estimates to published qualification. No draft is registered before confirmation. Confirmed berths persist in modeling
when MOORING_DB is file-backed; unset storage remains ephemeral. Agent drafts/reports additionally require
AGENTS_PERSIST=1. Stored berths are shared references, not private assets or engineering-approved geometry.

Image payload follows [OpenAI Responses image inputs](https://developers.openai.com/api/docs/guides/images-vision).
No real model-perception accuracy is established; tests use a generated fixture and fake model transport.
