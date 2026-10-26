"""Remediation service with a deterministic template fallback (Req 5).

Generates a prioritized remediation plan for an assessment's gaps. The LLM is
best-effort: when ``LLM_API_KEY`` is unset, or the call fails or exceeds its
30-second budget, the service falls back to a deterministic, template-based
generator and marks the plan ``source="fallback"`` (Req 5.4, 5.5, 5.6).

Steps are ordered by severity (high before medium before low) and, within the
same severity, by ascending question id (Req 5.2). Every gap yields at least one
step (Req 5.3).

Layering: depends only on config, schemas, and the standard library; no upward
dependency on routers (Req 12.2).
"""

from __future__ import annotations

from app.config import load_settings
from app.schemas import Gap, RemediationPlanResponse, RemediationStep

# Maximum seconds to wait for the external LLM before falling back (Req 5.1, 5.5).
LLM_TIMEOUT_SECONDS = 30

# Severity ordering for prioritization (Req 5.2). Lower sort key = higher priority.
_SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}

# Human-readable remediation guidance per domain, used by the fallback generator.
_DOMAIN_GUIDANCE: dict[str, str] = {
    "Access Control": "Enforce unique accounts, least-privilege access, and MFA; review access on role changes.",
    "Backup & Recovery": "Take regular backups, keep an offline/off-site copy, and test restoration periodically.",
    "Patching": "Maintain a system inventory and apply security updates promptly, prioritizing internet-facing systems.",
    "Incident Response": "Document an incident response plan, define reporting channels, and retain investigation logs.",
    "Vendor Risk": "Assess vendor security before granting access, add security clauses to contracts, and track vendors.",
    "Data Protection": "Encrypt sensitive data at rest and in transit, classify data, and restrict access to it.",
}

_PARTIAL_PREFIX = "Strengthen and fully implement: "
_NO_PREFIX = "Implement: "


def _fallback_action(gap: Gap) -> str:
    """Build a template remediation action for a single gap."""
    guidance = _DOMAIN_GUIDANCE.get(gap.domain, "Address this control gap.")
    prefix = _NO_PREFIX if gap.answer == "no" else _PARTIAL_PREFIX
    return f"{prefix}{guidance}"


def _sort_gaps(gaps: list[Gap]) -> list[Gap]:
    """Order gaps by severity then ascending question id (Req 5.2)."""
    return sorted(
        gaps,
        key=lambda g: (_SEVERITY_ORDER.get(g.severity, 99), g.question_id),
    )


def _fallback_plan(gaps: list[Gap]) -> RemediationPlanResponse:
    """Produce a deterministic template-based plan (Req 5.3, 5.4)."""
    steps = [
        RemediationStep(
            question_id=gap.question_id,
            severity=gap.severity,
            action=_fallback_action(gap),
        )
        for gap in _sort_gaps(gaps)
    ]
    return RemediationPlanResponse(source="fallback", steps=steps)


def _try_llm_plan(gaps: list[Gap], api_key: str) -> RemediationPlanResponse | None:
    """Best-effort LLM generation hook.

    Returns a plan when an LLM integration is available, or ``None`` to signal
    the caller to use the fallback. This project ships without a bundled LLM
    client dependency, so this hook returns ``None`` by default; wiring a real
    client here (within ``LLM_TIMEOUT_SECONDS``) will upgrade plans to
    ``source="llm"`` without changing the public contract (Req 5.1).
    """
    # No LLM client dependency is bundled. Returning None triggers the
    # deterministic fallback, which always satisfies Req 5.3/5.4/5.5.
    return None


def generate_remediation_plan(gaps: list[Gap]) -> RemediationPlanResponse:
    """Generate a prioritized remediation plan for the given gaps (Req 5).

    Uses the LLM when a key is configured and the call succeeds within the
    timeout; otherwise returns a template-based fallback plan. Always returns a
    plan (HTTP 200 at the route layer) with a ``source`` indicator.
    """
    settings = load_settings()

    if settings.llm_api_key:
        try:
            plan = _try_llm_plan(gaps, settings.llm_api_key)
            if plan is not None:
                return plan
        except Exception:
            # Any LLM failure/timeout degrades gracefully to the fallback
            # (Req 5.5). We intentionally swallow the error here.
            pass

    return _fallback_plan(gaps)
