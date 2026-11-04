"""Process-wide state for the modeling service: job store and interactive simulation sessions."""

from mooring.core.jobs import JobStore

API_PREFIX = "/api/v1"
JOBS = JobStore(API_PREFIX)
SESSIONS: dict = {}  # session_id -> mooring.mock.dynamics.BerthingModel
