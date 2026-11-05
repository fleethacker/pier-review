"""S7 trajectory prediction (the backup camera). Implementation follows in mooring.prediction."""

from fastapi import APIRouter, HTTPException

from mooring.core.schemas import PredictionPreset, PredictionRequest, PredictionResponse

router = APIRouter(tags=["S7 Prediction"])


@router.post("/predict/trajectory", response_model=PredictionResponse,
             summary="Predict a vessel's path, hull footprints, uncertainty corridor and hazard clearance from its current state")
def predict_trajectory(req: PredictionRequest):
    raise HTTPException(status_code=501, detail="S7 not implemented yet; see contract/examples/modeling/predict_trajectory_*.json")


@router.get("/predict/presets", response_model=list[PredictionPreset], summary="Ready-made prediction requests for demos")
def presets():
    raise HTTPException(status_code=501, detail="S7 not implemented yet")
