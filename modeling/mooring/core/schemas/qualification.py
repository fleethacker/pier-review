"""Reference-data qualification (S01): schema validity is separate from physical-data confidence."""

from typing import Literal

from pydantic import Field

from .common import Model

QualificationLevel = Literal["qualified", "demonstration", "unqualified"]
CapabilityState = Literal["supported", "limited", "unsupported"]


class QualificationIssue(Model):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", examples=["MISSING_SWL"])
    message: str
    element_ids: list[str] = Field(default_factory=list)
    blocking: bool = Field(description="True when a real analysis cannot proceed (level 'unqualified').")


class AssetQualification(Model):
    """How far one catalog record can be trusted.

    `qualified`: published provenance and every required field. `demonstration`: complete but mock, estimated,
    vision or unverified data; usable for demos, results are limited. `unqualified`: required data missing or
    inconsistent; a real analysis must not proceed.
    """

    asset_kind: Literal["ship", "berth", "line_spec", "tug"]
    asset_id: str
    level: QualificationLevel
    provenance_confidence: str
    issues: list[QualificationIssue] = Field(default_factory=list)
    capabilities: dict[str, CapabilityState] = Field(
        default_factory=dict, description="Per capability (e.g. 'static_mooring', 'tug_allocation')."
    )


class CatalogAudit(Model):
    """Whole-catalog integrity (duplicate ids, dangling references) and per-asset qualification."""

    ok: bool
    problems: list[QualificationIssue] = Field(default_factory=list)
    assets: list[AssetQualification]


class CapabilityRow(Model):
    capability: str
    module: str
    backend: Literal["mock", "real"]
    qualification: Literal["qualified", "demonstration", "unqualified", "mock"]
    limitations: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
