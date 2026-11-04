from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobAccepted,
    LimitEnvelopeRequest,
    LimitEnvelopeResponse,
    RecommendRequest,
    Rule,
    SequenceRequest,
    SequenceResponse,
    TideSweepRequest,
    TideSweepResponse,
)
from mooring.mock.examples import ex

from ..backend import planning, solver
from ..state import JOBS

router = APIRouter()


@router.post("/mooring/analyze", response_model=AnalyzeResponse, tags=["M4 Static mooring"],
             summary="Line, fitting and fender loads plus NSTM 582 findings for one environment")
def analyze(req: Annotated[AnalyzeRequest, Body(openapi_examples=ex("mooring_analyze"))]):
    return solver.analyze(req)


@router.post("/mooring/envelope", response_model=LimitEnvelopeResponse, tags=["M4 Static mooring"],
             summary="Limiting wind speed for each wind direction")
def envelope(req: Annotated[LimitEnvelopeRequest, Body(openapi_examples=ex("mooring_envelope"))]):
    return solver.limit_envelope(req)


@router.post("/mooring/tide-sweep", response_model=TideSweepResponse, tags=["M4 Static mooring"],
             summary="Line tensions through the tide and a tending schedule")
def tide_sweep(req: Annotated[TideSweepRequest, Body(openapi_examples=ex("mooring_tide_sweep"))]):
    return solver.tide_sweep(req)


@router.get("/rules", response_model=list[Rule], tags=["M4 Static mooring"], summary="NSTM 582 rule registry")
def rules():
    return solver.rules()


@router.post("/mooring/recommend", response_model=JobAccepted, status_code=202, tags=["M7 Planning"],
             summary="Recommend line configurations (job; result is a RecommendResponse)")
def recommend(req: Annotated[RecommendRequest, Body(openapi_examples=ex("mooring_recommend"))]):
    return JOBS.submit("mooring.recommend", planning.recommend(req))


@router.post("/mooring/sequence", response_model=SequenceResponse, tags=["M7 Planning"],
             summary="Ordered line-handling steps for a configuration")
def sequence(req: Annotated[SequenceRequest, Body(openapi_examples=ex("mooring_sequence"))]):
    return planning.sequence(req)
