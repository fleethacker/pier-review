"""Read-only explanations of caller-owned, immutable S7 prediction results."""

from fastapi import APIRouter

from ...prediction.brief import explain
from ...prediction.schemas import PredictionBrief
from ..state import PredictionTools

router = APIRouter(tags=["Prediction agent"])


@router.get("/predictions/{result_id}/brief", response_model=PredictionBrief,
            summary="Explain a saved prediction, retaining its warnings, validity and unknown coverage")
async def prediction_brief(result_id: str, tk: PredictionTools):
    return explain(await tk.prediction(result_id))
