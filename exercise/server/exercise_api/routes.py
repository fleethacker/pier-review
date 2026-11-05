"""Support for the exercise simulator: a shared scenario library, the public map token, and client error reports.

Scenarios are kept as one JSON file each in ``EXERCISE_DATA_DIR``. Without that variable the first of these that is writable is
used: ``/mnt/data/exercise`` (a Domino project's persistent volume), then ``.exercise-data`` in the working directory. In a
container the working directory is lost on restart, so point ``EXERCISE_DATA_DIR`` at a persistent volume to keep scenarios.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger("exercise")
router = APIRouter(prefix="/exercise", tags=["Exercise"])

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_SCENARIO_BYTES = 1_000_000
MAX_SCENARIOS = 500
_lock = threading.Lock()


def data_dir() -> Path:
    configured = os.environ.get("EXERCISE_DATA_DIR")
    candidates = [Path(configured)] if configured else [Path("/mnt/data/exercise"), Path.cwd() / ".exercise-data"]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.access(path, os.W_OK):
                return path
        except OSError:
            continue
    raise HTTPException(503, "No writable place to keep scenarios. Set EXERCISE_DATA_DIR.")


def _path(scenario_id: str) -> Path:
    if not ID_RE.match(scenario_id):
        raise HTTPException(422, "A scenario id is lowercase letters, digits, - and _, up to 64 characters, starting with a letter or digit.")
    return data_dir() / f"{scenario_id}.json"


def _stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="milliseconds")


@router.get("/config")
def config() -> dict[str, Any]:
    """What the page needs from the server. The Mapbox token is a public one (``pk.``): it ships to every browser anyway.
    A secret token (``sk.``) is never handed out."""
    token = (os.environ.get("MAPBOX_TOKEN") or os.environ.get("VITE_MAPBOX_TOKEN") or "").strip()
    return {"mapboxToken": token if token.startswith("pk.") else None}


class ScenarioPut(BaseModel):
    scenario: dict[str, Any]
    #: The ``updatedAt`` the editor last saw. If the file has changed since, the save is refused so nobody's work is lost.
    baseUpdatedAt: str | None = Field(default=None)


@router.get("/scenarios")
def list_scenarios() -> list[dict[str, Any]]:
    out = []
    for p in sorted(data_dir().glob("*.json")):
        try:
            body = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(body, dict):
            continue
        out.append({"id": p.stem, "name": str(body.get("name", p.stem)), "description": str(body.get("description", "")),
                    "units": len(body.get("units", [])) if isinstance(body.get("units"), list) else 0, "updatedAt": _stamp(p)})
    out.sort(key=lambda s: s["updatedAt"], reverse=True)
    return out


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> dict[str, Any]:
    p = _path(scenario_id)
    if not p.exists():
        raise HTTPException(404, f"No saved scenario '{scenario_id}'.")
    return {"scenario": json.loads(p.read_text()), "updatedAt": _stamp(p)}


@router.put("/scenarios/{scenario_id}")
def put_scenario(scenario_id: str, body: ScenarioPut) -> dict[str, Any]:
    p = _path(scenario_id)
    s = body.scenario
    if not isinstance(s.get("name"), str) or not s["name"].strip() or not isinstance(s.get("units"), list):
        raise HTTPException(422, "That does not look like a scenario: it needs a name and a list of units.")
    text = json.dumps(s, indent=2)
    if len(text.encode()) > MAX_SCENARIO_BYTES:
        raise HTTPException(413, "That scenario is too large to save.")
    with _lock:
        exists = p.exists()
        if exists and body.baseUpdatedAt is not None and _stamp(p) != body.baseUpdatedAt:
            raise HTTPException(409, "Someone saved this scenario after you opened it. Load it again, or save under another name.")
        if not exists and len(list(data_dir().glob("*.json"))) >= MAX_SCENARIOS:
            raise HTTPException(409, "The library is full. Delete some scenarios first.")
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(text)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return {"id": scenario_id, "updatedAt": _stamp(p), "created": not exists}


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str) -> None:
    p = _path(scenario_id)
    with _lock:
        if not p.exists():
            raise HTTPException(404, f"No saved scenario '{scenario_id}'.")
        p.unlink()


class ClientError(BaseModel):
    kind: str = Field(max_length=40)
    message: str = Field(max_length=1000)
    stack: str | None = Field(default=None, max_length=4000)
    page: str | None = Field(default=None, max_length=300)
    userAgent: str | None = Field(default=None, max_length=300)


_recent: deque[float] = deque()
MAX_ERRORS_PER_MINUTE = 60


@router.post("/client-errors", status_code=204)
def client_error(report: ClientError, request: Request) -> None:
    """Browser problems (script errors, WebGL failures, token refusals) land in the server log, where they can be found."""
    now = time.monotonic()
    while _recent and now - _recent[0] > 60:
        _recent.popleft()
    if len(_recent) >= MAX_ERRORS_PER_MINUTE:
        return
    _recent.append(now)
    log.warning("client error [%s] %s | page=%s | ua=%s%s", report.kind, report.message.replace("\n", " "), report.page, report.userAgent,
                f"\n{report.stack}" if report.stack else "")
