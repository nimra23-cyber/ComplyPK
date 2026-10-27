"""Remediation service: Groq AI with a deterministic template fallback (Req 5).

Generates a prioritized remediation plan for an assessment's gaps. Groq is
best-effort: when ``GROQ_API_KEY`` is unset, or the call fails/rate-limits/
times out, or the response does not validate against our contract, the service
falls back to a deterministic template generator and marks the plan
``source="fallback"`` (Req 5.4, 5.5, 5.6). A validated Groq plan is returned
with ``source="llm"``.

Only non-personal, security-posture data is sent to Groq: question ids and
yes/partial/no answers, the computed overall and per-domain scores, and gap/
control data. Company snapshots, names, emails, and identifiers are NEVER sent.
The API key is read from the environment and sent only to Groq (never exposed to
the frontend or logged).

Deterministic scoring and gap mapping are computed elsewhere and are unchanged;
this service only consumes their results.

Steps are ordered by severity (high before medium before low) and, within the
same severity, by ascending question id (Req 5.2). Every gap yields at least one
step (Req 5.3).

Layering: depends only on config, schemas, httpx, and the standard library; no
upward dependency on routers (Req 12.2).
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import Settings, load_settings
from app.schemas import Gap, RemediationPlanResponse, RemediationStep

logger = logging.getLogger("complypk")

# Maximum seconds to wait for the external LLM before falling back (Req 5.1, 5.5).
LLM_TIMEOUT_SECONDS = 30

# Groq is OpenAI-compatible; chat completions endpoint.
_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

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


def _build_prompt(
    gaps: list[Gap],
    overall_score: int | None,
    domain_scores: dict[str, int] | None,
    answers: dict[str, str] | None,
) -> str:
    """Build the Groq prompt from NON-PERSONAL assessment data only.

    Includes question ids + yes/partial/no answers, computed scores, and gap/
    control data. Never includes company name/profile, emails, or identifiers.
    """
    lines: list[str] = []
    if overall_score is not None:
        lines.append(f"Overall readiness score: {overall_score}/100")
    if domain_scores:
        lines.append("Domain scores: " + ", ".join(
            f"{d}={s}/100" for d, s in sorted(domain_scores.items())
        ))
    if answers:
        # Only question_id -> answer; no free text, no identifiers.
        lines.append("Answers: " + ", ".join(
            f"{qid}={answers[qid]}" for qid in sorted(answers)
        ))
    lines.append("")
    lines.append("Gaps (failed/partial controls):")
    for g in _sort_gaps(gaps):
        iso = ", ".join(g.iso_27001) or "none"
        nist = ", ".join(g.nist_csf) or "none"
        lines.append(
            f'- question_id="{g.question_id}", domain="{g.domain}", '
            f'answer="{g.answer}", severity="{g.severity}", '
            f"ISO 27001=[{iso}], NIST CSF=[{nist}]"
        )
    gaps_block = "\n".join(lines)
    return (
        "You are a cyber-security compliance advisor for a Pakistani SME/fintech. "
        "Using the readiness-assessment data below, produce personalized, actionable "
        "remediation recommendations prioritized by risk and urgency.\n\n"
        "Rules:\n"
        "- Provide AT LEAST ONE step for EVERY question_id listed under Gaps.\n"
        "- Keep each 'action' concrete, specific, and under 60 words.\n"
        '- "severity" MUST copy the severity given for that question_id.\n'
        "- Order steps by severity (high, then medium, then low).\n"
        "- This is a readiness assessment, not certification; do not promise compliance.\n\n"
        "Return ONLY valid JSON of the form:\n"
        '{"steps":[{"question_id":"...","severity":"high|medium|low","action":"..."}]}\n\n'
        f"{gaps_block}\n"
    )


def _extract_content(data: dict) -> str | None:
    """Pull the assistant message content from an OpenAI-compatible response."""
    try:
        choices = data.get("choices") or []
        content = choices[0]["message"]["content"]
        return content.strip() if isinstance(content, str) and content.strip() else None
    except (KeyError, IndexError, TypeError):
        return None


def _parse_steps(text: str, gaps: list[Gap]) -> list[RemediationStep] | None:
    """Parse and validate model JSON into RemediationStep list for these gaps.

    Enforces the existing contract: valid severities, question ids restricted to
    the assessment's gaps, and at least one step per gap. Returns None if the
    output cannot be validated (caller then falls back).
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        payload = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    raw_steps = payload.get("steps") if isinstance(payload, dict) else None
    if not isinstance(raw_steps, list) or not raw_steps:
        return None

    gap_by_id = {g.question_id: g for g in gaps}
    steps: list[RemediationStep] = []
    covered: set[str] = set()
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        qid = item.get("question_id")
        action = item.get("action")
        if qid not in gap_by_id:
            continue  # ignore ids the model invented (stay within the assessment)
        if not isinstance(action, str) or not action.strip():
            continue
        # Trust the gap's true (deterministic) severity over the model's claim.
        severity = gap_by_id[qid].severity
        steps.append(
            RemediationStep(question_id=qid, severity=severity, action=action.strip())
        )
        covered.add(qid)

    if covered != set(gap_by_id.keys()):
        return None  # every gap must be covered (Req 5.3)

    steps.sort(key=lambda s: (_SEVERITY_ORDER.get(s.severity, 99), s.question_id))
    return steps


def _safe_error_category(resp: httpx.Response) -> str:
    """Return a short, non-sensitive error label from a Groq error response.

    Groq error bodies look like ``{"error": {"type": "...", "code": "..."}}``.
    We return only those short labels (e.g. "invalid_api_key",
    "model_not_found"), never the human message, URL, headers, or any secret.
    """
    try:
        err = resp.json().get("error", {})
        if isinstance(err, dict):
            label = err.get("code") or err.get("type")
            if isinstance(label, str) and len(label) <= 64:
                return label
    except (ValueError, AttributeError, TypeError):
        pass
    return "unknown"


def _try_llm_plan(
    gaps: list[Gap],
    settings: Settings,
    overall_score: int | None = None,
    domain_scores: dict[str, int] | None = None,
    answers: dict[str, str] | None = None,
) -> RemediationPlanResponse | None:
    """Call Groq to generate a plan, or return None to use the fallback.

    Secure: the API key is read from settings (env) and sent only in the
    Authorization header to Groq — never returned to the frontend or logged.
    Any error (missing key, HTTP error, 429 rate limit, timeout, or an
    unparseable/invalid response) returns None so the caller falls back
    gracefully (Req 5.4, 5.5).
    """
    if not settings.groq_configured:
        logger.info("groq_skip: no GROQ_API_KEY configured; using template fallback")
        return None
    if not gaps:
        return None

    # Safe diagnostic: confirms the model being requested (model id is not a
    # secret). The API key and headers are NEVER logged.
    logger.info("groq_request: model=%s gaps=%d", settings.groq_model, len(gaps))

    body = {
        "model": settings.groq_model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": "You are a precise assistant that returns only valid JSON.",
            },
            {
                "role": "user",
                "content": _build_prompt(gaps, overall_score, domain_scores, answers),
            },
        ],
    }
    try:
        resp = httpx.post(
            _GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        logger.warning("groq_timeout: no response within %ss", LLM_TIMEOUT_SECONDS)
        return None
    except httpx.HTTPError as exc:
        # Category only (e.g. ConnectError) — never the URL query or headers.
        logger.warning("groq_request_failed: category=%s", type(exc).__name__)
        return None

    if resp.status_code == 429:
        logger.warning("groq_rate_limited: status=429")
        return None
    if resp.status_code != 200:
        # Surface the status and a SANITIZED error category from the body
        # (Groq returns e.g. {"error": {"code": "...", "type": "..."}}). We log
        # only those short labels — never the API key, headers, or full body.
        logger.warning(
            "groq_non_200: status=%s category=%s",
            resp.status_code,
            _safe_error_category(resp),
        )
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.warning("groq_bad_json: status=200 but response body was not JSON")
        return None
    content = _extract_content(data)
    if not content:
        logger.info("groq_empty_content: no message content in response")
        return None
    steps = _parse_steps(content, gaps)
    if steps is None:
        logger.info("groq_response_unvalidated: output did not match the plan contract")
        return None
    logger.info("groq_success: validated plan with %d steps", len(steps))
    return RemediationPlanResponse(source="llm", steps=steps)


def generate_remediation_plan(
    gaps: list[Gap],
    overall_score: int | None = None,
    domain_scores: dict[str, int] | None = None,
    answers: dict[str, str] | None = None,
) -> RemediationPlanResponse:
    """Generate a prioritized remediation plan for the given gaps (Req 5).

    Uses Groq when ``GROQ_API_KEY`` is configured and the call succeeds within
    the timeout and validates against our contract; otherwise returns a
    template-based fallback plan. Extra context (scores/answers) is optional and
    only enriches the AI prompt — it never affects deterministic scoring. Always
    returns a plan with a ``source`` indicator.
    """
    settings = load_settings()

    if settings.groq_configured:
        try:
            plan = _try_llm_plan(
                gaps, settings, overall_score, domain_scores, answers
            )
            if plan is not None:
                return plan
        except Exception:  # noqa: BLE001 - never let AI errors break the request
            logger.warning("groq_unexpected_error_falling_back")

    return _fallback_plan(gaps)
