"""Named, offline demonstration requests; never qualified operational plans."""
from typing import Literal

from .common import Model
from .environment import EnvScenarioCreate
from .mooring import AnalyzeRequest, LimitEnvelopeRequest
from .plans import ScenarioCreate


class DockingDemoCase(Model):
    case_id: str
    name: str
    expected_outcome: Literal["supported_limited", "overloaded", "invalid_data", "undetermined"]
    explanation: str
    environment_request: EnvScenarioCreate
    scenario_request: ScenarioCreate
    analysis_request: AnalyzeRequest
    envelope_request: LimitEnvelopeRequest | None = None
