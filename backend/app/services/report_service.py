"""Report service: render an assessment as a Markdown report (Req 6).

Produces a Markdown document containing the Overall_Score, each Domain_Score,
every gap with its severity and ISO 27001 / NIST CSF references, the remediation
plan (or a placeholder when none has been generated), and the fixed disclaimer.
A report is never produced without the disclaimer (Req 6.5, 8.3, 8.4).

Layering: depends only on schemas and the standard library; no upward
dependency on routers (Req 12.2).
"""

from __future__ import annotations

from datetime import datetime

from app.schemas import DISCLAIMER, Gap, RemediationPlanResponse


def _format_refs(refs: list[str]) -> str:
    return ", ".join(refs) if refs else "—"


def render_markdown_report(
    assessment_id: int,
    created_at: datetime,
    overall_score: int,
    domain_scores: dict[str, int],
    gaps: list[Gap],
    remediation_plan: RemediationPlanResponse | None,
) -> str:
    """Render a complete Markdown report for an assessment (Req 6.2, 6.3, 6.4, 6.5)."""
    lines: list[str] = []
    lines.append(f"# ComplyPK Readiness Assessment Report")
    lines.append("")
    lines.append(f"- **Assessment ID:** {assessment_id}")
    lines.append(f"- **Created:** {created_at.isoformat()}")
    lines.append(f"- **Overall readiness score:** {overall_score} / 100")
    lines.append("")

    # Domain scores (Req 6.3).
    lines.append("## Domain scores")
    lines.append("")
    lines.append("| Domain | Score |")
    lines.append("| --- | --- |")
    for domain, score in domain_scores.items():
        lines.append(f"| {domain} | {score} / 100 |")
    lines.append("")

    # Gaps with severity and control references (Req 6.3).
    lines.append("## Identified gaps")
    lines.append("")
    if not gaps:
        lines.append("No gaps were identified. All controls were answered \"yes\".")
    else:
        lines.append("| Question | Domain | Answer | Severity | ISO 27001 | NIST CSF |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for gap in gaps:
            lines.append(
                f"| {gap.question_id} | {gap.domain} | {gap.answer} | "
                f"{gap.severity} | {_format_refs(gap.iso_27001)} | "
                f"{_format_refs(gap.nist_csf)} |"
            )
    lines.append("")

    # Remediation plan (Req 6.3, 6.4).
    lines.append("## Remediation plan")
    lines.append("")
    if remediation_plan is None or not remediation_plan.steps:
        lines.append("_No remediation plan has been generated for this assessment yet._")
    else:
        lines.append(f"_Source: {remediation_plan.source}_")
        lines.append("")
        for i, step in enumerate(remediation_plan.steps, start=1):
            lines.append(f"{i}. **[{step.severity}] {step.question_id}** — {step.action}")
    lines.append("")

    # Disclaimer — always present (Req 6.5, 8.3).
    lines.append("## Disclaimer")
    lines.append("")
    lines.append(DISCLAIMER)
    lines.append("")

    report = "\n".join(lines)

    # Never return a report without the disclaimer (Req 8.4).
    if DISCLAIMER not in report:  # pragma: no cover - defensive
        raise RuntimeError("Report could not be generated without the disclaimer.")

    return report
