"""Safety sheet builder (M10): assembles the Mooring Evolution Safety Sheet from a reviewed plan. Real (no LLM).

Every number comes from a cited modeling result. Go/no-go thresholds come from the safety review. A sheet locks on its
first approval; edits create a new version.
"""

import html
from datetime import UTC

from mooring.core import access
from mooring.core.envelopes import new_id, utcnow
from mooring.core.schemas import Provenance, Finding

from ..planner.agent import PlanRecord
from ..intake.agent import REPORTS
from .schemas import (
    Approval,
    ApprovalCreate,
    GoNoGo,
    SafetyReview,
    SafetySheet,
    SheetEnvironment,
    SheetHeader,
    SheetLineRow,
)

from ..shared.storage import AgentStore

SHEETS = AgentStore("agent_sheet", SafetySheet)

DISCLAIMER = ("Decision aid only. The Commanding Officer and pilot retain authority for the mooring evolution. "
              "Values marked mock or estimated are not validated.")


def build(rec: PlanRecord, review: SafetyReview | None = None) -> SafetySheet:
    with SHEETS.atomic():
        return _build(rec, review)


def _build(rec: PlanRecord, review: SafetyReview | None = None) -> SafetySheet:
    plan, a = rec.plan, rec.analysis
    if a is None or plan.config is None:
        raise ValueError("Plan has no analysis to build a sheet from")
    by_line = {r.line_number: r for r in a.result.lines}
    rows = [SheetLineRow(line_number=ln.line_number, role=by_line[ln.line_number].role, spec_id=ln.spec_id,
                         parts=ln.parts, ship_fitting_id=ln.ship_fitting_id, pier_fitting_id=ln.pier_fitting_id,
                         tension_lbf=by_line[ln.line_number].tension_lbf, pct_wll=by_line[ln.line_number].pct_wll,
                         status=by_line[ln.line_number].status) for ln in plan.config.lines]
    top = a.result.min_margin
    limit = review.thresholds.limit_wll_gust_kt if review else None
    breaking = review.thresholds.limit_breaking_gust_kt if review else None
    go_no_go = []
    if limit:
        go_no_go.append(GoNoGo(condition=f"Gusts above {0.8 * limit:.0f} kt (80% of plan limit)",
                               action="Reassess the plan with the bridge and pilot; use only an independently reviewed tending or assistance procedure"))
        go_no_go.append(GoNoGo(condition=f"Gusts above {limit:.0f} kt (working-load limit)",
                               action="Call holding tugs; consider an alternate berth"))
    if breaking:
        go_no_go.append(GoNoGo(condition=f"Gusts approaching {breaking:.0f} kt (estimated line breaking)",
                               action="Clear personnel from snap-back zones; get underway or relocate if able"))
    cited = [c for item in plan.rationale for c in item.cites]
    if review:
        cited += review.thresholds.cites
        cited += [cite for check in review.checks for cite in check.cites]
    status = review.status if review else (plan.status or "RED")
    validity = (review.validity if review else None) or a.validity
    if validity and validity.state == "invalid":
        status = "RED"
    elif validity and validity.state == "limited" and status == "GREEN":
        status = "AMBER"
    report_id = review.intake_report_id if review and review.intake_report_id else plan.intake_report_id
    report = REPORTS.get(report_id) if report_id else None
    forecast_summary = report.summary if report else "No intake forecast attached; only the plan's evaluated conditions are documented."
    validity_findings = [Finding(rule_id=r.code, severity="RED" if validity.state == "invalid" else "AMBER",
        message=r.message, reference="Result validity", element_ids=r.affected_components) for r in validity.reasons] if validity else []
    # Every sheet built for the same plan gets the next version, locked or not, so versions never repeat.
    version = max((sheet.version for sheet in SHEETS.values() if sheet.plan_id == plan.plan_id), default=0) + 1
    sheet = SafetySheet(
        sheet_id=new_id("sheet"), version=version, plan_id=plan.plan_id, review_id=review.review_id if review else None,
        locked=False, status=status, validity=validity,
        analysis_result_id=a.result_id, sequence_result_id=plan.sequence_result_id,
        installed_at_water_level_mllw_ft=plan.installed_at_water_level_mllw_ft,
        threshold_result_ids=review.thresholds.cites if review else [],
        holding_tugs=getattr(rec, "holding_tugs", []) or [],
        header=SheetHeader(ship_class_id=rec.scenario.ship_class_id, berth_id=rec.scenario.berth_id,
                           side_to=rec.scenario.side_to, evolution="moor", planned_utc=utcnow()),
        environment=SheetEnvironment(observed=rec.env, forecast_summary=forecast_summary,
                                     mst=rec.mst),
        line_plan=rows, fitting_utilization=a.result.pier_fittings, tug_plan=plan.tug_plan,
        sequence=plan.sequence.steps if plan.sequence else [],
        sequence_review_status=plan.sequence.review_status if plan.sequence else None,
        sequence_limitations=plan.sequence.limitations if plan.sequence else [], go_no_go=go_no_go,
        brief=review.brief if review else None,
        directional_thresholds=review.thresholds.directions if review else [],
        warnings=[f for f in [*a.result.findings, *a.warnings, *validity_findings] if f.severity != "INFO"], rationale=plan.rationale,
        assumptions=plan.assumptions, cited_result_ids=sorted(set(cited + [a.result_id] + ([plan.sequence_result_id] if plan.sequence_result_id else []))),
        sources=[Provenance(source="NSTM 582 (paragraph references only)", confidence="published"),
                 Provenance(source="UFC 4-159-03 Chapter 4", confidence="published"),
                 Provenance(source=f"{a.model} ({a.backend}); reference data qualification is reported in validity", confidence="estimated")],
        approvals=[], disclaimer=DISCLAIMER)
    access.claim("agent_sheet", sheet.sheet_id)
    SHEETS[sheet.sheet_id] = sheet
    return sheet


def approve(sheet: SafetySheet, req: ApprovalCreate) -> SafetySheet:
    with SHEETS.atomic():
        current = SHEETS[sheet.sheet_id]
        approval = Approval(**req.model_dump(), at_utc=utcnow())
        updated = current.model_copy(update={"approvals": [*current.approvals, approval], "locked": True})
        SHEETS[sheet.sheet_id] = updated
        return updated



def _environment_provenance_html(environment) -> str:
    """Render source timing without treating retrieval as issuance or inventing wind basis."""
    e = html.escape
    metadata = environment.metadata
    if metadata is None:
        return "<p>Wind averaging, gust duration and reference height: not recorded in these inputs.</p>"
    def quantity(value, unit):
        return f"{value:g} {unit}" if value is not None else "unknown"
    def timestamp(value):
        if value is None:
            return "unknown"
        if value.tzinfo is None:
            return value.strftime("%Y-%m-%d %H:%M") + " (timezone unknown)"
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")
    basis = (f"<p>Wind averaging: {quantity(metadata.wind_averaging_s, 's')}; "
             f"gust duration: {quantity(metadata.gust_duration_s, 's')}; "
             f"reference height: {quantity(metadata.wind_reference_height_m, 'm')}.</p>")
    items = []
    for item in metadata.components or [metadata]:
        label = getattr(item, "component", "combined input").replace("_", " ")
        text = (f"{label}: {item.source or 'source not recorded'}; basis {item.basis}; quality {item.quality}; "
                f"issued {timestamp(item.issued_at_utc)}; retrieved {timestamp(getattr(item, 'retrieved_at_utc', None))}; "
                f"valid {timestamp(item.valid_from_utc)} to {timestamp(item.valid_to_utc)}")
        limits = "; ".join(getattr(item, "limitations", []))
        items.append(f"<li>{e(text)}{'; '+e(limits) if limits else ''}</li>")
    return basis + "<p>Retrieval is an availability record, not a provider issue time or proof of freshness.</p><ul>" + "".join(items) + "</ul>"


def render_html(s: SafetySheet) -> str:
    e = html.escape
    usable = s.validity is not None and s.validity.state in ('valid', 'limited')
    lines = "".join(f"<tr><td>{r.line_number}</td><td>{e(r.role)}</td><td>{e(r.spec_id)}</td><td>{r.parts}</td>"
                    f"<td>{e(r.ship_fitting_id)}</td><td>{e(r.pier_fitting_id)}</td>"
                    + (f"<td>{r.tension_lbf:,.0f}</td><td>{r.pct_wll:.0f}%</td><td>{r.status}</td>"
                       if usable else "<td>Unavailable</td><td>Unavailable</td><td>Unavailable</td>")
                    + "</tr>" for r in s.line_plan)
    steps = "".join(f"<li>{e(st.action.replace('_', ' '))} line {st.line_number or '-'} ({e(st.station)}): "
                    f"{e(st.trigger)}{(' <em>' + e(st.caution) + '</em>') if st.caution else ''}"
                    + (f" <strong>Static check: {'within limits (draft)' if st.state_ok is True else 'blocking' if st.state_ok is False else 'undetermined'}.</strong> {e(st.state_note or '')}" if st.state_ok is not None or st.state_note else "")
                    + "</li>" for st in s.sequence)
    validity_banner = (f"<p><strong>Validity: {e(s.validity.state)}. "
        "Seed or estimated reference data is not qualified for operational use.</strong></p>" if s.validity
        else "<p><strong>Validity unknown; qualification is not established.</strong></p>")
    seq_banner = ""
    if s.sequence_review_status and s.sequence_review_status != "reviewed":
        seq_banner = (f"<p><b>DRAFT, not reviewed by a deck officer or pilot ({e(s.sequence_review_status)}).</b> "
                      + " ".join(e(x) for x in s.sequence_limitations) + "</p>")
    if s.sequence_result_id:
        seq_banner += f"<p>Sequence assessment: <code>{e(s.sequence_result_id)}</code>.</p>"
    gng = "".join(f"<li><b>{e(g.condition)}</b>: {e(g.action)}</li>" for g in s.go_no_go)
    warn = "".join(f"<li>[{w.severity}] {e(w.message)} <small>({e(w.reference)})</small></li>" for w in s.warnings)
    why = "".join(f"<li>{e(r.text)} <small>[{e(', '.join(r.cites))}]</small></li>" for r in s.rationale)
    appr = "".join(f"<li>{e(a.role.upper())}: {e(a.name)}, {a.decision} {a.at_utc:%Y-%m-%d %H:%MZ}</li>" for a in s.approvals)
    thresholds = "".join(
        f"<tr><td>{row.wind_rel_deg:.0f}°</td><td>{e(row.governing_element or '-') if usable else 'Unavailable'}</td>"
        + (f"<td>{row.limit_wll_gust_kt:.0f} kt</td>" if usable and row.limit_wll_gust_kt is not None else "<td>Unavailable</td>")
        + (f"<td>{row.estimated_breaking_gust_kt:.0f} kt (legacy estimate)</td></tr>"
           if usable and row.estimated_breaking_gust_kt is not None else "<td>Unavailable; not established</td></tr>")
        for row in s.directional_thresholds)
    tug = s.tug_plan
    tug_line = (f"{tug.recommended_tug_count} tugs, {tug.total_power_hp:,.0f} hp, {tug.total_bollard_pull_lbf:,.0f} lbf "
                f"bollard pull" if tug else "None")
    if not usable:
        tug_line = "Unavailable: sheet validity does not establish a usable tug assessment."
    holding = "".join(f"<li>{e(t.tug_id)}: {e(t.mode)} at {e(t.push_point_id)}, {t.force_lbf:,.0f} lbf"
        + (f", direction {t.direction_true_deg:.0f}° true" if t.direction_true_deg is not None else ", push-point direction")
        + "</li>" for t in (s.holding_tugs or []))
    holding_note = ("Prescribed assistance included in the holding assessment; continuous availability must be arranged."
                    if s.holding_tugs else "Holding assistance is not recorded in this archived sheet; inspect the cited analysis before use."
                    if s.holding_tugs is None else "No prescribed holding assistance is included in the line assessment.")
    installation = (f"{s.installed_at_water_level_mllw_ft:g} ft MLLW; held fixed across assessed conditions, with no implicit tending"
                    if s.installed_at_water_level_mllw_ft is not None else "not recorded in this legacy sheet; inspect the cited inputs")
    citations = "".join(f"<li>{e(cite)}</li>" for cite in s.cited_result_ids)
    assumptions = "".join(f"<li>{e(item)}</li>" for item in s.assumptions)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Mooring Evolution Safety Sheet</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#111}}table{{border-collapse:collapse}}
td,th{{border:1px solid #999;padding:4px 8px;text-align:left}}.st{{font-weight:700}}thead{{display:table-header-group}}tr{{break-inside:avoid}}</style></head><body>
<h1>Mooring Evolution Safety Sheet</h1>
{validity_banner}
<p>Sheet {e(s.sheet_id)} v{s.version} &middot; Status <span class="st">{s.status}</span> &middot;
{e(s.header.ship_class_id)} {e(s.header.side_to)} side to {e(s.header.berth_id)}</p>
<p>Independent review: {e(s.review_id) if s.review_id else 'not recorded in this sheet; independent review is not established'}.</p>
<p>Wind {s.environment.observed.wind_speed_kt:.0f} kt gusting {s.environment.observed.wind_gust_kt:.0f} kt from
{s.environment.observed.wind_from_true_deg:03.0f}° true; current {s.environment.observed.current_speed_kt:.1f} kt
flowing toward {s.environment.observed.current_set_true_deg:03.0f}° true; water level
{s.environment.observed.water_level_mllw_ft:.2f} ft MLLW; assessment MST {s.environment.mst}</p>
<p>Evaluated condition: {s.environment.observed.valid_at_utc:%Y-%m-%d %H:%M %z}; source {e(s.environment.observed.source)}.
These are assessed inputs, not a live observation display.</p>
<p>Line-installation water level: {installation}.</p>
{_environment_provenance_html(s.environment.observed)}
<h2>Forecast assessment</h2><p>{e(s.environment.forecast_summary or 'No forecast summary recorded.')}</p>
{f'<h2>Bridge brief</h2><p>{e(s.brief)}</p>' if s.brief else ''}
<h2>Directional gust thresholds</h2>
<p>Modeling result references: {e(', '.join(s.threshold_result_ids)) or 'Unavailable in this archived sheet'}.</p>
<table><thead><tr><th>Relative wind</th><th>Governing element</th><th>Working-load limit</th>
<th>Breaking threshold estimate</th></tr></thead><tbody>{thresholds}</tbody></table>
<h2>Line plan</h2><p>Static loads for the evaluated condition, result {e(s.analysis_result_id or 'unavailable in this archived sheet')}.
Other reviewed conditions may govern individual elements.</p><table><thead><tr><th>#</th><th>Role</th><th>Line</th><th>Parts</th><th>Ship fitting</th>
<th>Pier fitting</th><th>Tension (lbf)</th><th>% WLL</th><th>Status</th></tr></thead><tbody>{lines}</tbody></table>
<h2>Holding assistance</h2><p>{holding_note}</p><ul>{holding}</ul>
<h2>Berthing tug plan</h2><p>{tug_line}</p>
<h2>Go / no-go</h2><ul>{gng}</ul>
<h2>Sequence</h2>{seq_banner}<ol>{steps}</ol>
<h2>Warnings</h2><ul>{warn or '<li>None</li>'}</ul>
<h2>Assessment assumptions and limits</h2><ul>{assumptions or '<li>No assumptions recorded; inspect the cited inputs before use.</li>'}</ul>
<h2>Agent rationale</h2><ul>{why}</ul>
<h2>Referenced modeling results</h2><ul>{citations}</ul>
<h2>Approvals</h2><ul>{appr or '<li>Pending</li>'}</ul>
<p><small>{e(s.disclaimer)}</small></p></body></html>"""


class PdfUnavailable(RuntimeError):
    """WeasyPrint is installed but its system libraries (Pango/GObject) are missing."""


PDF_SETUP = ("PDF rendering needs the Pango/GObject system libraries used by WeasyPrint: "
             "`brew install pango` (macOS) or `apt-get install libpango-1.0-0 libpangoft2-1.0-0` (Debian/Ubuntu).")


def pdf_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def render_pdf(s: SafetySheet) -> bytes:
    """Render the canonical HTML sheet to PDF with WeasyPrint."""
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:
        raise PdfUnavailable(PDF_SETUP) from exc
    return HTML(string=render_html(s)).write_pdf()
