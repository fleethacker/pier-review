"""Phase 1, moored: static analysis, limiting wind, tide sweep, rules, gust risk, holding tugs, optimizer."""

from typing import Annotated

from fastapi import APIRouter, Body

from mooring.core.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ExceedanceRequest,
    HoldTugRequest,
    JobAccepted,
    LimitEnvelopeRequest,
    LimitEnvelopeResponse,
    RecommendRequest,
    Rule,
    TideSweepRequest,
    TideSweepResponse,
    TimelineRequest,
    TugPlanResponse,
)
from mooring.examples import ex

from ..inputs import check_analyze
from ..backend import moored_tugs, optimizer, risk, solver
from ..state import JOBS

router = APIRouter()


# ---- M4 Static mooring ----

@router.post("/mooring/analyze", response_model=AnalyzeResponse, tags=["M4 Static mooring"],
             summary="Line, fitting and fender loads plus NSTM 582 findings for one environment")
def analyze(req: Annotated[AnalyzeRequest, Body(openapi_examples=ex("mooring_analyze"))]):
    check_analyze(req)
    return solver.analyze(req)


@router.post("/mooring/envelope", response_model=LimitEnvelopeResponse, tags=["M4 Static mooring"],
             summary="Limiting wind speed for each wind direction")
def envelope(req: Annotated[LimitEnvelopeRequest, Body(openapi_examples=ex("mooring_envelope"))]):
    check_analyze(req)
    return solver.limit_envelope(req)


@router.post("/mooring/tide-sweep", response_model=TideSweepResponse, tags=["M4 Static mooring"],
             summary="Line tensions through the tide and a tending schedule")
def tide_sweep(req: Annotated[TideSweepRequest, Body(openapi_examples=ex("mooring_tide_sweep"))]):
    check_analyze(req)
    return solver.tide_sweep(req)


@router.get("/rules", response_model=list[Rule], tags=["M4 Static mooring"], summary="NSTM 582 rule registry")
def rules():
    return solver.rules()


# ---- M5 Risk ----

@router.post("/risk/exceedance", response_model=JobAccepted, status_code=202, tags=["M5 Risk"],
             summary="Monte Carlo probability of exceeding line limits (job; result is an ExceedanceResponse)")
def exceedance(req: Annotated[ExceedanceRequest, Body(openapi_examples=ex("risk_exceedance"))]):
    check_analyze(req)
    return JOBS.submit("risk.exceedance", risk.exceedance(req))


@router.post("/risk/timeline", response_model=JobAccepted, status_code=202, tags=["M5 Risk"],
             summary="Plan status through the forecast (job; result is a TimelineResponse)")
def timeline(req: Annotated[TimelineRequest, Body(openapi_examples=ex("risk_timeline"))]):
    check_analyze(req)
    return JOBS.submit("risk.timeline", risk.timeline(req))


# ---- M6 Holding tugs ----

@router.post("/tugs/hold-plan", response_model=TugPlanResponse, tags=["M6 Tugs"],
             summary="Tugs needed to relieve overloaded lines on a moored ship")
def hold_plan(req: Annotated[HoldTugRequest, Body(openapi_examples=ex("tugs_hold_plan"))]):
    check_analyze(req)
    return moored_tugs.hold_plan(req)


# ---- M7 Optimizer ----

@router.post("/mooring/recommend", response_model=JobAccepted, status_code=202, tags=["M7 Planning"],
             summary="Recommend line configurations (job; result is a RecommendResponse)")
def recommend(req: Annotated[RecommendRequest, Body(openapi_examples=ex("mooring_recommend"))]):
    return JOBS.submit("mooring.recommend", optimizer.recommend(req))
