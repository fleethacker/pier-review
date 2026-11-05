"""S7 trajectory prediction (the backup camera): the S6 transit simulator run forward from an observed state."""

from fastapi import APIRouter, HTTPException

from mooring.core.schemas import PredictionPreset, PredictionRequest, PredictionResponse
from mooring.prediction import engine, presets as prediction_presets

router = APIRouter(tags=["S7 Prediction"])


@router.post("/predict/trajectory", response_model=PredictionResponse,
             summary="Predict a vessel's path, hull footprints, uncertainty corridor and hazard clearance from its current state")
def predict_trajectory(req: PredictionRequest):
    try:
        return engine.predict(req)
    except engine.RequestInvalid as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/predict/presets", response_model=list[PredictionPreset], summary="Ready-made prediction requests built from real recorded NOAA conditions")
def presets():
    return prediction_presets.presets()
