"""Acceptance-runner regressions against the real services over in-memory HTTP."""

from email.message import Message
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("pier_demo_check", SCRIPTS / "demo_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def transport(monkeypatch):
    from modeling_api.main import app as modeling_app
    from mooring_agents.api.main import app as agents_app, get_client
    from mooring_agents.physics.client import ModelingClient

    monkeypatch.setenv("AGENTS_LLM_PROVIDER", "none")
    monkeypatch.setenv("MOORING_ENV_SOURCE", "mock")
    monkeypatch.setenv("MOORING_RATE_PER_MINUTE", "0")
    monkeypatch.setenv("AGENTS_RATE_PER_MINUTE", "0")
    monkeypatch.setitem(agents_app.dependency_overrides, get_client, lambda: ModelingClient(
        base_url="http://modeling/api/v1", transport=httpx.ASGITransport(app=modeling_app)))
    modeling, agents = TestClient(modeling_app), TestClient(agents_app)

    def response(method, url, body=None):
        marker = "/api/modeling" if "/api/modeling/" in url else "/api/agents"
        client = modeling if marker == "/api/modeling" else agents
        path = url.split(marker, 1)[1]
        result = client.request(method, path, json=body)
        assert result.is_success, result.text
        return result

    def http(method, url, body=None):
        result = response(method, url, body)
        return result.status_code, result.json() if "application/json" in result.headers.get("content-type", "") else result.content

    return http, response


class EventResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = Message()
        self.headers["Content-Type"] = "text/event-stream"


def test_all_four_full_chains_retain_initial_and_final_status(demo, transport, monkeypatch):
    import demo_check_planning as planning

    http, response = transport
    # TestClient buffers streaming bodies; stop after done instead of waiting for
    # the optional ten-minute follow-up message channel.
    monkeypatch.setattr(planning.urllib.request, "urlopen", lambda url, **kwargs: EventResponse(response("GET", url + "?follow=false").content))
    results = []

    def check(name, fn):
        results.append((name, fn()))

    supported = planning.four_case_checks("http://demo/app-prefix", http, check)
    assert len(results) == 4
    assert supported["plan"]["status"] == "AMBER" and supported["intake"]["report_id"]
    assert "initial RED/invalid → final AMBER/limited" in next(detail for name, detail in results if "undetermined" in name)
    from mooring_agents.safety.schemas import SafetySheet
    from mooring_agents.safety.sheet import render_html

    _, plan = http("GET", "http://demo/api/agents/api/v1/agent/plans/" + supported["plan_id"])
    _, saved = http("GET", "http://demo/api/agents/api/v1/safety-sheets/" + plan["safety_sheet_id"])
    sheet = SafetySheet.model_validate(saved)
    assert f"Independent review: {sheet.review_id}" in render_html(sheet)
    sheet.review_id = '<script>alert("review")</script>'
    assert "<script>" not in render_html(sheet) and "&lt;script&gt;" in render_html(sheet)
    sheet.review_id = None
    assert "Independent review: not recorded in this sheet; independent review is not established" in render_html(sheet)


def test_advance_story_preserves_installation_and_rejects_uncovered_arrival(demo, transport):
    import demo_check_planning as planning

    detail = planning.advance_planning_check("http://demo", ROOT / "contract/examples/modeling", transport[0])
    assert "uncovered arrivals unavailable" in detail


@pytest.mark.parametrize("event", [
    b'event: step\ndata: {}\n\nevent: done\ndata: {"state":"failed","error":"solver timeout"}\n\n',
    b'event: step\ndata: {}\n\n',
])
def test_sse_failure_or_truncation_cannot_pass(demo, monkeypatch, event):
    import demo_check_planning as planning

    monkeypatch.setattr(planning.urllib.request, "urlopen", lambda *args, **kwargs: EventResponse(event))
    with pytest.raises(AssertionError):
        planning.plan_events("http://demo/events")


def test_sse_heartbeats_cannot_extend_completion_deadline(demo, monkeypatch):
    import demo_check_planning as planning

    ticks = iter([0, 0.5, 1.5, 2.5])
    monkeypatch.setattr(planning, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    monkeypatch.setattr(planning.urllib.request, "urlopen", lambda *args, **kwargs: EventResponse(b": heartbeat\n\n" * 10))
    with pytest.raises(AssertionError, match="SSE exceeded demo-check deadline"):
        planning.plan_events("http://demo/events", timeout=2)


def test_hosted_websocket_keeps_tls_and_domino_path(demo):
    assert demo.websocket_url("https://demo.example/domino/app/", "session_123") == "wss://demo.example/domino/app/api/modeling/ws/sim/session_123"
    assert demo.websocket_url("http://127.0.0.1:8888", "session_123") == "ws://127.0.0.1:8888/api/modeling/ws/sim/session_123"


@pytest.mark.parametrize("state", ["created", "reset"])
def test_motion_check_waits_for_frame_after_lifecycle(demo, state):
    frame = {"t_s": 0, "pose": {"x_ft": 0, "y_ft": 20, "yaw_deg": 0}}
    messages = iter([{"type": "session_lifecycle", "state": state, "t_s": 0}, frame])

    async def recv():
        return json.dumps(next(messages))

    assert asyncio.run(demo.motion_frame(SimpleNamespace(recv=recv))) == frame


def test_motion_check_rejects_protocol_error_before_frame(demo):
    async def recv():
        return json.dumps({"type": "error", "message": "session ended"})

    with pytest.raises(AssertionError, match="simulation protocol error"):
        asyncio.run(demo.motion_frame(SimpleNamespace(recv=recv)))


def test_readiness_cannot_pass_missing_build_dependencies(demo):
    demo.readiness_checks({"motion_frame": {"t_s": 0}}, "readiness")
    failed = [name for status, name, _ in demo.RESULTS if status == "FAIL"]
    assert any("S1" in name for name in failed) and any("D1" in name for name in failed)
    assert any("A3" in name for name in failed) and any("U1" in name for name in failed)


def test_hosted_mode_does_not_require_or_launch_local_node(demo, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["demo_check.py", "--base-url", "https://demo.example/prefix/", "--no-browser"])
    monkeypatch.setattr(demo.shutil, "which", lambda _: None)
    seen = []
    monkeypatch.setattr(demo, "api_checks", lambda stack: seen.append(stack.ui) or {})
    assert demo.main() == 0
    assert seen == ["https://demo.example/prefix"]
