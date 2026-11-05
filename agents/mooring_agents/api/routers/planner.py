"""Planner endpoints: acknowledge bounded work, then stream actual computed events."""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Body, Header
from fastapi.responses import StreamingResponse

from mooring import refdata
from mooring.core import access
from mooring.core.envelopes import new_id
from mooring.core.jobs import TERMINAL, sse

from ...backend import planner
from ...physics.client import ModelingError
from ...planner.schemas import (AgentDoneEvent, AgentMessage, AgentMessageAccepted, AgentPlan,
                                AgentPlanAccepted, AgentPlanRequest)
from ..execution import submit_async
from ..state import API_PREFIX, JOBS, PlannerTools

router = APIRouter(tags=["Planner agent"])
PLAN_JOBS: dict[str, str] = {}
PLAN_REQUESTS: dict[str, AgentPlanRequest] = {}


def _job(plan_id: str):
    job = JOBS.get(PLAN_JOBS[plan_id]) if plan_id in PLAN_JOBS and access.allowed("agent_plan", plan_id) else None
    if job is None:
        raise refdata.NotFound(f"Plan '{plan_id}' not found")
    return job


def plan_record(plan_id: str):
    job = _job(plan_id)
    if job.state != 'succeeded':
        raise ModelingError(409, f"Plan is {job.state}; a completed plan is required")
    if plan_id not in planner.PLANS:
        raise refdata.NotFound(f"Plan '{plan_id}' is unavailable")
    return planner.PLANS[plan_id], job


@router.post("/agent/plans", response_model=AgentPlanAccepted, status_code=202,
             summary="Start the planner on a saved scenario, optionally designing for an intake report")
async def create_plan(tk: PlannerTools, req: Annotated[AgentPlanRequest, Body(openapi_examples={"default": {
        "summary": "Plan for a saved scenario",
        "value": {"scenario_id": "<scenario_id from modeling POST /scenarios>",
                  "intake_report_id": "<optional report_id from POST /intake/reports>",
                  "objective": "moor_for_forecast", "target_margin_pct_wll": 80}}})]):
    if req.constraints or req.objective != 'moor_for_forecast':
        raise ModelingError(422, 'Only moor_for_forecast without unsupported constraints is implemented')
    plan_id = new_id('plan')
    access.claim('agent_plan', plan_id)
    tk.plan_id = plan_id
    scenario = await tk.scenario(req.scenario_id)

    async def operation(ctx):
        def emit(name, data):
            ctx.check_cancelled()
            if name != 'done':  # terminal event is emitted only after the job commits its result
                ctx.emit(name, data)
        rec = await planner.run(req, tk, plan_id=plan_id, scenario=scenario, on_event=emit)
        return rec.plan

    accepted = submit_async(JOBS, 'agent.plan', tk, operation)
    PLAN_JOBS[plan_id], PLAN_REQUESTS[plan_id] = accepted.job_id, req
    return AgentPlanAccepted(plan_id=plan_id, job_id=accepted.job_id,
                             events_url=f'{API_PREFIX}/agent/plans/{plan_id}/events')


@router.get('/agent/plans/{plan_id}', response_model=AgentPlan)
def get_plan(plan_id: str):
    job = _job(plan_id)
    if job.state == 'succeeded':
        return plan_record(plan_id)[0].plan
    req = PLAN_REQUESTS[plan_id]
    return AgentPlan(plan_id=plan_id, scenario_id=req.scenario_id, intake_report_id=req.intake_report_id,
                     state=job.state, status='RED' if job.state in TERMINAL else None,
                     open_questions=[job.error] if job.error else [])


@router.get('/agent/plans/{plan_id}/events', response_class=StreamingResponse,
            summary='SSE computed step/proposal events and terminal done; follow=true includes subsequent answers.',
            responses={200: {'content': {'text/event-stream': {}}}})
def plan_events(plan_id: str, follow: bool = True,
                last_event_id: int | None = Header(default=None, ge=0)):
    job = _job(plan_id)

    async def gen():
        sent = last_event_id + 1 if last_event_id is not None else 0
        last_heartbeat = asyncio.get_running_loop().time()
        while True:
            JOBS.get(job.job_id)  # enforce cooperative deadline while streaming
            with job.lock:
                pending = list(enumerate(job.log))[sent:]
            for index, (name, data) in pending:
                sent = index + 1
                if name == 'done':
                    rec = planner.PLANS.get(plan_id)
                    data = AgentDoneEvent(plan_id=plan_id,
                        status=rec.plan.status if job.state == 'succeeded' and rec else 'RED',
                        state=job.state, error=job.error).model_dump(mode='json')
                yield sse(name, data, event_id=index)
            if job.state in TERMINAL and sent >= len(job.log):
                break
            now = asyncio.get_running_loop().time()
            if now - last_heartbeat >= 15:
                yield ': keepalive\n\n'
                last_heartbeat = now
            await asyncio.sleep(0.02)
        if not follow or job.state != 'succeeded':
            return
        rec = planner.PLANS[plan_id]
        offset = len(job.log)
        msent = max(0, sent - offset)
        idle = 0.0
        while idle < 600:
            while msent < len(rec.messages):
                name, data = rec.messages[msent]
                yield sse(name, data, event_id=offset + msent)
                msent, idle = msent + 1, 0.0
            await asyncio.sleep(0.5)
            idle += 0.5
            if idle % 15 == 0:
                yield ': keepalive\n\n'

    return StreamingResponse(gen(), media_type='text/event-stream')


@router.post('/agent/plans/{plan_id}/messages', response_model=AgentMessageAccepted, status_code=202,
             summary='Ask a follow-up; the answer streams as a message event')
async def plan_message(plan_id: str, req: AgentMessage, tk: PlannerTools):
    rec, _ = plan_record(plan_id)
    tk.plan_id = plan_id
    msg = await planner.answer(rec, req.text, tk)
    return AgentMessageAccepted(message_id=msg.message_id)
