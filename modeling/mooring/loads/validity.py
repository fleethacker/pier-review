"""M3 validity (S03): the one wind-basis conversion boundary and the classification of range warnings.

Wind basis. UFC 4-159-03 loads use a 30 s, 10 m wind. `wind_basis()` is the only place that converts a snapshot's wind
to that basis:
  * gust: used as given when its duration is 30 s or unknown (legacy: assumed 30 s). Any other duration cannot be
    converted with a sourced factor, so the value is used unchanged and the result is `limited`.
  * sustained: averaging 60 s or unknown (legacy) uses the Figure 3-5 synoptic ratio; 30 s needs no conversion;
    other averaging times are not supported (legacy ratio applied, result `limited`).
  * reference height: no height conversion is implemented; a height other than 10 m makes the result `limited`.
Missing metadata keeps the legacy numbers and is stated in the assumptions. Whether a shorter-duration gust is
conservative for a coupled mooring model is not established here, and nothing claims it is.
"""

from dataclasses import dataclass, field

from mooring.core.schemas import EnvironmentSnapshot, Finding, ValidityReason

from . import coefficients as c

LEGACY_NOTE = "Wind averaging/gust duration/height not documented in the snapshot: legacy assumption applied (10 m, 60 s sustained, 30 s gust)."


@dataclass
class WindBasis:
    speed_kt: float            # speed on the UFC 30 s basis
    factor: float              # applied to wind_speed_kt (sustained path); 1.0 for gusts
    notes: list[str] = field(default_factory=list)
    reasons: list[ValidityReason] = field(default_factory=list)
    verified: bool = False     # True only when metadata documents a supported basis


def wind_basis(env: EnvironmentSnapshot, use_gust: bool) -> WindBasis:
    meta = env.metadata
    out = WindBasis(speed_kt=0.0, factor=1.0)
    duration = meta.gust_duration_s if meta else None
    averaging = meta.wind_averaging_s if meta else None
    height = meta.wind_reference_height_m if meta else None
    documented = meta is not None and (duration is not None if use_gust else averaging is not None) and height is not None
    if use_gust:
        out.speed_kt = env.wind_gust_kt
        if duration is None:
            out.notes.append("Gust duration not given: assumed 30 s (legacy).")
        elif duration == 30:
            out.notes.append("Gust duration documented as 30 s: used as given.")
        else:
            out.reasons.append(ValidityReason(code="WIND_GUST_DURATION_UNSUPPORTED", affected_components=["wind"],
                                              message=f"Gust duration {duration:g} s has no sourced conversion to the 30 s UFC basis; value used unchanged."))
    else:
        if averaging in (None, 60):
            out.factor = c.SUSTAINED_TO_30S
            out.notes.append(f"Sustained wind {'documented as' if averaging else 'assumed'} 60 s; converted to 30 s by {c.SUSTAINED_TO_30S:.3f} (UFC Figure 3-5 synoptic curve, approximate).")
        elif averaging == 30:
            out.notes.append("Sustained wind documented as 30 s average: no conversion applied.")
        else:
            out.factor = c.SUSTAINED_TO_30S
            out.reasons.append(ValidityReason(code="WIND_AVERAGING_UNSUPPORTED", affected_components=["wind"],
                                              message=f"Averaging time {averaging:g} s is not supported; the 60 s ratio was applied anyway."))
        out.speed_kt = env.wind_speed_kt * out.factor
    if height is not None and height != 10:
        out.reasons.append(ValidityReason(code="WIND_HEIGHT_NOT_CONVERTED", affected_components=["wind"],
                                          message=f"Wind reference height {height:g} m is not converted to 10 m."))
    if meta is None or not documented:
        out.notes.append(LEGACY_NOTE)
    out.verified = documented and not out.reasons
    return out


# rule_id -> (validity state, reason code). Depth at or below draft cannot be a valid floating-mooring result.
CLASSIFICATION = {
    "UFC-DEPTH-RANGE": ("invalid", "DEPTH_NOT_ABOVE_DRAFT"),
    "UFC-CURRENT-SPEED": ("limited", "CURRENT_OUTSIDE_COEFFICIENT_RANGE"),
    "UFC-LOW-REYNOLDS": ("limited", "LOW_REYNOLDS_REGULARIZED"),
}


def classify_findings(findings: list[Finding]) -> list[tuple[str, ValidityReason]]:
    """(state, reason) for each load-model range finding."""
    out = []
    for f in findings:
        if f.rule_id in CLASSIFICATION:
            state, code = CLASSIFICATION[f.rule_id]
            out.append((state, ValidityReason(code=code, message=f.message, affected_components=list(f.element_ids) or ["loads"])))
    return out


def merge_reasons(reasons: list[ValidityReason]) -> list[ValidityReason]:
    """One reason per code, affected components unioned (no thousand duplicate findings)."""
    merged: dict[str, ValidityReason] = {}
    for r in reasons:
        if r.code in merged:
            merged[r.code].affected_components = sorted(set(merged[r.code].affected_components) | set(r.affected_components))
        else:
            merged[r.code] = r.model_copy(deep=True)
    return list(merged.values())


def environment_findings(env: EnvironmentSnapshot, use_gust: bool = True) -> list[tuple[str, ValidityReason]]:
    """Honor explicit input quality without applying a wall-clock expiry to archived scenarios.

    No age threshold is invented here: providers own freshness policy and flag stale data.
    Forecast as-of/coverage checks belong to the planning service. Missing/bad inputs cannot
    establish a physical limit; suspect/stale inputs retain diagnostic values but stay limited.
    """
    out = []

    def add(state, code, message, components=None):
        out.append((state, ValidityReason(code=code, message=message,
                                       affected_components=components or ["environment"])))

    meta = env.metadata
    if env.valid_at_utc.tzinfo is None:
        add("invalid", "ENVIRONMENT_TIME_UNSPECIFIED", "Environment validity time has no timezone.")
    elif meta:
        if ((meta.valid_from_utc and env.valid_at_utc < meta.valid_from_utc)
                or (meta.valid_to_utc and env.valid_at_utc > meta.valid_to_utc)):
            add("invalid", "ENVIRONMENT_OUTSIDE_VALID_INTERVAL", "Snapshot time lies outside its declared validity interval.")
    for item in meta.components if meta else []:
        if ((item.valid_from_utc and env.valid_at_utc < item.valid_from_utc)
                or (item.valid_to_utc and env.valid_at_utc > item.valid_to_utc)):
            add("invalid", "ENVIRONMENT_COMPONENT_OUTSIDE_VALID_INTERVAL",
                f"{item.component} snapshot lies outside the source validity interval.", [item.component])
        if item.quality == "poor":
            add("invalid", "ENVIRONMENT_COMPONENT_POOR_QUALITY",
                f"{item.component} provider marks the component as poor quality.", [item.component])
        elif item.quality in ("suspect", "unknown"):
            add("limited", "ENVIRONMENT_COMPONENT_QUALITY_UNVERIFIED",
                f"{item.component} quality is {item.quality}; qualification is not established.", [item.component])
        if item.basis == "prediction" and item.issued_at_utc is None:
            add("limited", "FORECAST_COMPONENT_ISSUANCE_UNKNOWN",
                f"{item.component} provider issuance is unknown; recorded retrieval establishes only an availability bound.", [item.component])
        if item.limitations:
            add("limited", "ENVIRONMENT_COMPONENT_LIMITATIONS",
                f"{item.component}: {'; '.join(item.limitations)}", [item.component])
    if meta and meta.quality == "poor":
        add("invalid", "ENVIRONMENT_POOR_QUALITY", "Provider marks required environmental inputs as poor quality.")
    elif meta and meta.quality == "suspect":
        add("limited", "ENVIRONMENT_SUSPECT", "Provider marks environmental inputs as suspect; values are diagnostic, not qualified.")
    if env.source in ("live", "forecast", "replay", "ship_sensor"):
        basis = wind_basis(env, use_gust)
        if not basis.verified and not basis.reasons:
            add("limited", "WIND_BASIS_UNVERIFIED", "Public/sensor wind duration or reference height is undocumented.", ["wind"])
        if meta is None or meta.quality == "unknown":
            add("limited", "ENVIRONMENT_QUALITY_UNVERIFIED", "Public/sensor input quality is undocumented.")
    for quality in env.quality:
        flags = " ".join(quality.flags).lower()
        if any(word in flags for word in ("missing", "unavailable", "invalid", "poor", "gap")):
            add("invalid", "ENVIRONMENT_COMPONENT_UNAVAILABLE",
                f"Source {quality.station_id} reports unusable input: {', '.join(quality.flags)}.", [quality.station_id])
        elif any(word in flags for word in ("stale", "suspect")):
            add("limited", "ENVIRONMENT_COMPONENT_FLAGGED",
                f"Source {quality.station_id} requires review: {', '.join(quality.flags)}.", [quality.station_id])
    if env.wind_gust_kt < env.wind_speed_kt:
        add("limited", "WIND_GUST_BELOW_SUSTAINED", "Supplied gust is below sustained wind; duration/alignment needs review.", ["wind"])
    return out


def aggregate_findings(per_context: list[tuple[str, list[Finding]]], max_listed: int = 5) -> list[Finding]:
    """Collapse the same finding repeated across times/samples into one, naming where it occurred."""
    groups: dict[tuple[str, str], list[str]] = {}
    first: dict[tuple[str, str], Finding] = {}
    for label, findings in per_context:
        for f in findings:
            k = (f.rule_id, f.message)
            groups.setdefault(k, []).append(label)
            first.setdefault(k, f)
    out = []
    for k, labels in groups.items():
        f = first[k].model_copy(deep=True)
        shown = ", ".join(labels[:max_listed]) + (f" and {len(labels) - max_listed} more" if len(labels) > max_listed else "")
        f.message = f"{f.message} [{len(labels)} of {len(per_context)} cases: {shown}]"
        out.append(f)
    return out
