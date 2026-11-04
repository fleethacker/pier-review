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
