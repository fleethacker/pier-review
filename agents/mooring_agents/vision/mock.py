"""Mock Berth Map agent (M8).

Returns a draft of the seed Pier 12 North berth as if extracted from the image, with synthetic detections and
confirmation questions. Workstream D replaces it with: ENC geometry -> vision LLM extraction -> snapping -> M7.
"""

from mooring.core.envelopes import envelope, new_id
from mooring.core.schemas import Provenance

from ..physics.toolkit import PhysicsToolkit
from .schemas import Detection, VisionMetadata, VisionResponse, VisionResult

TEMPLATE_BERTH = "NAVSTA-NORFOLK-P12-N"


async def analyze(image: bytes, filename: str, meta: VisionMetadata, tk: PhysicsToolkit) -> VisionResponse:
    seed = await tk.berth(TEMPLATE_BERTH)
    draft_id = new_id("VISION-DRAFT").upper().replace("_", "-")
    draft = seed.model_copy(update={
        "berth_id": draft_id, "name": meta.berth_name or f"Draft berth from {filename}",
        "provenance": Provenance(source=f"Vision extraction from '{filename}' ({len(image):,} bytes)", confidence="vision",
                                 notes="MOCK: copied from the seed Pier 12 North berth; confirm every fitting.")})
    scale = meta.georef.scale_ft_per_px if meta.georef and meta.georef.scale_ft_per_px else 0.5
    detections = []
    for i, f in enumerate(draft.fittings):
        conf = 0.55 if f.kind.startswith("cleat") or i % 7 == 3 else 0.9
        detections.append(Detection(item_id=f.fitting_id, kind=f.kind,
                                    bbox_px=(f.x_ft / scale - 6, (60 - f.y_ft) / scale - 6, 12, 12),
                                    confidence=conf, needs_confirmation=conf < 0.7))
    questions = [f"Is {d.item_id} a {d.kind.replace('_', ' ')}? (confidence {d.confidence:.0%})"
                 for d in detections if d.needs_confirmation][:5]
    questions.append("Fitting capacities were not visible; defaults from NSTM Table 582-5-6 were used. Confirm.")
    recommended = None
    if meta.ship_class_id:
        rec = await tk.recommend({"ship_class_id": meta.ship_class_id, "berth_id": TEMPLATE_BERTH,
                                      "side_to": meta.side_to or "starboard", "max_candidates": 1})
        recommended = rec.result.candidates[0].config if rec.result.candidates else None
    result = VisionResult(draft_berth=draft, detections=detections, recommended_config=recommended,
                          questions=questions)
    return envelope(VisionResponse, model="agents.berth_vision", request=meta, result=result, status="AMBER",
                    assumptions=["Draft berth needs human confirmation before use (POST /berth-vision/{job_id}/confirm)."])
