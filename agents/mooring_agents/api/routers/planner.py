"""Planner agent endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from mooring import refdata
from mooring.core.jobs import sse

from ...backend import planner
from ...planner.schemas import AgentMessage, AgentMessageAccepted, AgentPlan, AgentPlanAccepted, AgentPlanRequest
from ..state import API_PREFIX, JOBS, PlannerTools

router = APIRouter(tags=["Planner agent"])
PLAN_JOBS: dict[str, str] = {}  # plan_id -> job_id


def plan_record(plan_id: str):
    if plan_id not in planner.PLANS:
        raise refdata.NotFound(f"Plan '{plan_id}' not found")
    return planner.PLANS[plan_id], JOBS.get(PLAN_JOBS[plan_id])


@router.post("/agent/plans", response_model=AgentPlanAccepted, status_code=202,
             summary="Start the planner on a saved scenario, optionally designing for an intake report")
async def create_plan(tk: PlannerTools, req: Annotated[AgentPlanRequest, Body(openapi_examples={"default": {
        "summary": "Plan for a saved scenario",
        "value": {"scenario_id": "<scenario_id from modeling POST /scenarios>",
                  "intake_report_id": "<optional report_id from POST /intake/reports>",
                  "objective": "moor_for_forecast", "target_margin_pct_wll": 80}}})]):
    rec = await planner.run(req, tk)
    accepted = JOBS.submit("agent.plan", rec.plan)
    PLAN_JOBS[rec.plan.plan_id] = accepted.job_id
    return AgentPlanAccepted(plan_id=rec.plan.plan_id, job_id=accepted.job_id,
                             events_url=f"{API_PREFIX}/agent/plans/{rec.plan.plan_id}/events")


@router.get("/agent/plans/{plan_id}", response_model=AgentPlan)
def get_plan(plan_id: str):
    rec, job = plan_record(plan_id)
    if job.state == "running":
        return AgentPlan(plan_id=plan_id, scenario_id=rec.scenario.scenario_id, state="running")
    return rec.plan


@router.get("/agent/plans/{plan_id}/events",
            summary="SSE: step (AgentStepEvent), proposal (AgentProposalEvent), message (AgentMessageEvent), "
                    "done (AgentDoneEvent). follow=true keeps the stream open for follow-up answers.",
            response_class=StreamingResponse, responses={200: {"content": {"text/event-stream": {}}}})
def plan_events(plan_id: str, follow: bool = True):
    rec, job = plan_record(plan_id)

    async def gen():
        sent = 0
        while True:
            p = job.progress
            due = len(rec.events) if p >= 1 else int(len(rec.events) * p)
            while sent < due:
                name, data = rec.events[sent]
                yield sse(name, data)
                sent += 1
            if p >= 1:
                break
            await asyncio.sleep(min(0.5, max(job.delay_s / 20, 0.05)))
        msent, idle = 0, 0.0
        while follow and idle < 600:
            while msent < len(rec.messages):
                name, data = rec.messages[msent]
                yield sse(name, data)
                msent, idle = msent + 1, 0.0
            await asyncio.sleep(0.5)
            idle += 0.5
            if idle % 15 == 0:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/agent/plans/{plan_id}/messages", response_model=AgentMessageAccepted, status_code=202,
             summary="Ask a follow-up; the answer streams as a `message` event")
async def plan_message(plan_id: str, req: AgentMessage, tk: PlannerTools):
    rec, _ = plan_record(plan_id)
    tk.plan_id = plan_id
    msg = await planner.answer(rec, req.text, tk)
    return AgentMessageAccepted(message_id=msg.message_id)
