"""Process-wide state for the modeling service: job store and interactive simulation sessions."""

from mooring.core.jobs import JobStore

API_PREFIX = "/api/v1"
JOBS = JobStore(API_PREFIX, persist=True)
SESSIONS: dict = {}  # session_id -> berthing simulator model (mooring.berthing.mock.simulator.BerthingModel)
