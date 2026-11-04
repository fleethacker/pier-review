"""Bounded-label process counters and structured operational events. No payloads or credentials."""
import json
import logging
import threading
from collections import Counter

_lock = threading.Lock()
_values = Counter({name: 0 for name in ("queue_saturation", "solver_failures", "cancellations",
                                       "job_duration_seconds", "jobs_succeeded", "jobs_failed", "jobs_cancelled")})
_log = logging.getLogger("mooring.operations")


def add(name, amount=1):
    with _lock: _values[name] += amount


def snapshot():
    with _lock: return dict(_values)


def event(name, **fields):
    _log.info(json.dumps({"event":name, **fields}, sort_keys=True))
