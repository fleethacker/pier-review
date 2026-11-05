"""Safety sheet builder (M10): assembles the Mooring Evolution Safety Sheet from a reviewed plan. Real (no LLM).

Every number comes from a cited modeling result. Go/no-go thresholds come from the safety review. A sheet locks on its
first approval; edits create a new version.
"""

import html

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
    worst_lines = sorted(rows, key=lambda r: -r.pct_wll)[:2]
    go_no_go = []
    if limit:
        go_no_go.append(GoNoGo(condition=f"Gusts above {0.8 * limit:.0f} kt (80% of plan limit)",
                               action=f"Tend and double up lines {', '.join(str(r.line_number) for r in worst_lines)}"))
        go_no_go.append(GoNoGo(condition=f"Gusts above {limit:.0f} kt (working-load limit)",
                               action="Call holding tugs; consider an alternate berth"))
    if breaking:
        go_no_go.append(GoNoGo(condition=f"Gusts approaching {breaking:.0f} kt (estimated line breaking)",
                               action="Clear personnel from snap-back zones; get underway or relocate if able"))
    cited = [c for item in plan.rationale for c in item.cites]
    if review:
        cited += review.thresholds.cites
    status = review.status if review else (plan.status or "RED")
    validity = (review.validity if review else None) or a.validity
    if validity and validity.state == "invalid":
        status = "RED"
    elif validity and validity.state == "limited" and status == "GREEN":
        status = "AMBER"
    report = REPORTS.get(plan.intake_report_id) if plan.intake_report_id else None
    forecast_summary = report.summary if report else "No intake forecast attached; only the plan's evaluated conditions are documented."
    validity_findings = [Finding(rule_id=r.code, severity="RED" if validity.state == "invalid" else "AMBER",
        message=r.message, reference="Result validity", element_ids=r.affected_components) for r in validity.reasons] if validity else []
    # Every sheet built for the same plan gets the next version, locked or not, so versions never repeat.
    version = max((sheet.version for sheet in SHEETS.values() if sheet.plan_id == plan.plan_id), default=0) + 1
    sheet = SafetySheet(
        sheet_id=new_id("sheet"), version=version, plan_id=plan.plan_id, review_id=review.review_id if review else None,
        locked=False, status=status, validity=validity,
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
        assumptions=plan.assumptions, cited_result_ids=sorted(set(cited + [a.result_id])),
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


def render_html(s: SafetySheet) -> str:
    e = html.escape
    lines = "".join(f"<tr><td>{r.line_number}</td><td>{e(r.role)}</td><td>{e(r.spec_id)}</td><td>{r.parts}</td>"
                    f"<td>{e(r.ship_fitting_id)}</td><td>{e(r.pier_fitting_id)}</td><td>{r.tension_lbf:,.0f}</td>"
                    f"<td>{r.pct_wll:.0f}%</td><td>{r.status}</td></tr>" for r in s.line_plan)
    steps = "".join(f"<li>{e(st.action.replace('_', ' '))} line {st.line_number or '-'} ({e(st.station)}): "
                    f"{e(st.trigger)}{(' <em>' + e(st.caution) + '</em>') if st.caution else ''}</li>" for st in s.sequence)
    validity_banner = (f"<p><strong>Validity: {e(s.validity.state)}. "
        "Seed or estimated reference data is not qualified for operational use.</strong></p>" if s.validity
        else "<p><strong>Validity unknown; qualification is not established.</strong></p>")
    seq_banner = ""
    if s.sequence_review_status and s.sequence_review_status != "reviewed":
        seq_banner = (f"<p><b>DRAFT, not reviewed by a deck officer or pilot ({e(s.sequence_review_status)}).</b> "
                      + " ".join(e(x) for x in s.sequence_limitations) + "</p>")
    gng = "".join(f"<li><b>{e(g.condition)}</b>: {e(g.action)}</li>" for g in s.go_no_go)
    warn = "".join(f"<li>[{w.severity}] {e(w.message)} <small>({e(w.reference)})</small></li>" for w in s.warnings)
    why = "".join(f"<li>{e(r.text)} <small>[{', '.join(r.cites)}]</small></li>" for r in s.rationale)
    appr = "".join(f"<li>{e(a.role.upper())}: {e(a.name)}, {a.decision} {a.at_utc:%Y-%m-%d %H:%MZ}</li>" for a in s.approvals)
    thresholds = "".join(
        f"<tr><td>{row.wind_rel_deg:.0f}°</td><td>{e(row.governing_element or '-')}</td>"
        + (f"<td>{row.limit_wll_gust_kt:.0f} kt</td>" if row.limit_wll_gust_kt is not None else "<td>Unavailable</td>")
        + (f"<td>{row.estimated_breaking_gust_kt:.0f} kt (legacy estimate)</td></tr>"
           if row.estimated_breaking_gust_kt is not None else "<td>Unavailable; not established</td></tr>")
        for row in s.directional_thresholds)
    tug = s.tug_plan
    tug_line = (f"{tug.recommended_tug_count} tugs, {tug.total_power_hp:,.0f} hp, {tug.total_bollard_pull_lbf:,.0f} lbf "
                f"bollard pull" if tug else "None")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Mooring Evolution Safety Sheet</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px;color:#111}}table{{border-collapse:collapse}}
td,th{{border:1px solid #999;padding:4px 8px;text-align:left}}.st{{font-weight:700}}</style></head><body>
<h1>Mooring Evolution Safety Sheet</h1>
{validity_banner}
<p>Sheet {e(s.sheet_id)} v{s.version} &middot; Status <span class="st">{s.status}</span> &middot;
{e(s.header.ship_class_id)} {e(s.header.side_to)} side to {e(s.header.berth_id)}</p>
<p>Wind {s.environment.observed.wind_speed_kt:.0f} kt gusting {s.environment.observed.wind_gust_kt:.0f} kt from
{s.environment.observed.wind_from_true_deg:03.0f}; current {s.environment.observed.current_speed_kt:.1f} kt;
MST {s.environment.mst}</p>
{f'<h2>Bridge brief</h2><p>{e(s.brief)}</p>' if s.brief else ''}
<h2>Directional gust thresholds</h2>
<table><tr><th>Relative wind</th><th>Governing element</th><th>Working-load limit</th>
<th>Breaking threshold estimate</th></tr>{thresholds}</table>
<h2>Line plan</h2><table><tr><th>#</th><th>Role</th><th>Line</th><th>Parts</th><th>Ship fitting</th>
<th>Pier fitting</th><th>Tension (lbf)</th><th>% WLL</th><th>Status</th></tr>{lines}</table>
<h2>Tugs</h2><p>{tug_line}</p>
<h2>Go / no-go</h2><ul>{gng}</ul>
<h2>Sequence</h2>{seq_banner}<ol>{steps}</ol>
<h2>Warnings</h2><ul>{warn or '<li>None</li>'}</ul>
<h2>Agent rationale</h2><ul>{why}</ul>
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
