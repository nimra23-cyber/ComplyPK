"""Pydantic request/response schemas (Req 12.3, 10.1).

All data crossing the API boundary is defined here as Pydantic models so that
FastAPI validates request bodies before any processing or persistence
(Req 10.1, 10.2) and serializes responses consistently.

The fixed readiness-only disclaimer is defined here as a single source of truth
and attached to user-facing result and plan responses (Req 8.2, 8.3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Allowed answer values shared across request/response schemas (Req 1.3, 2.6).
AnswerValue = Literal["yes", "partial", "no"]

# Severity levels for gaps (Req 3.3).
Severity = Literal["low", "medium", "high"]

# Source of a generated remediation plan (Req 5.6).
PlanSource = Literal["llm", "fallback"]

# Fixed readiness-only disclaimer text (Req 8.2, 8.3, 8.4). Never implies
# certification or guaranteed compliance (Req 8.1).
DISCLAIMER = (
    "ComplyPK provides a readiness assessment only. It does not constitute "
    "certification or a guarantee of compliance with any standard or regulation."
)


# --- Questionnaire -----------------------------------------------------------

class Question(BaseModel):
    """A single questionnaire item (Req 1.3)."""

    id: str
    domain: str
    text: str
    allowed_answers: list[AnswerValue] = Field(default_factory=lambda: ["yes", "partial", "no"])


class QuestionnaireResponse(BaseModel):
    """Questionnaire grouped by domain (Req 1.2, 1.3).

    ``domains`` maps each domain name to its ordered list of questions.
    """

    domains: dict[str, list[Question]]


# --- Submission --------------------------------------------------------------

class AnswerSubmission(BaseModel):
    """Submitted answers for the questionnaire (Req 2.6, 10.4).

    Structural validation (value must be one of the allowed answers) happens
    here. Completeness (all 20 question ids present) and unknown-id rejection are
    enforced in the service/router layer against the loaded questionnaire.
    """

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, AnswerValue]


# --- Gaps and assessments ----------------------------------------------------

class Gap(BaseModel):
    """A failed or partially satisfied question mapped to controls (Req 3)."""

    question_id: str
    domain: str
    answer: AnswerValue
    severity: Severity
    iso_27001: list[str] = Field(default_factory=list)
    nist_csf: list[str] = Field(default_factory=list)


class AssessmentResponse(BaseModel):
    """Full assessment result returned to the client (Req 4.2, 8.2)."""

    id: int
    created_at: datetime
    overall_score: int
    domain_scores: dict[str, int]
    gaps: list[Gap]
    company: dict | None = None
    disclaimer: str = DISCLAIMER


class AssessmentSummary(BaseModel):
    """Compact assessment entry used in history listings (Req 4.5)."""

    id: int
    created_at: datetime
    overall_score: int


# --- Remediation -------------------------------------------------------------

class RemediationStep(BaseModel):
    """A single prioritized remediation step (Req 5.2)."""

    question_id: str
    severity: Severity
    action: str


class RemediationPlanResponse(BaseModel):
    """A prioritized remediation plan and its source (Req 5.2, 5.6)."""

    source: PlanSource
    steps: list[RemediationStep]
    disclaimer: str = DISCLAIMER


# --- Auth & tenancy ----------------------------------------------------------

class RegisterInput(BaseModel):
    """New-user registration payload."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginInput(BaseModel):
    """Login payload."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class CompanyCreateInput(BaseModel):
    """Create a new company (the creator becomes its admin)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)


class CompanyJoinInput(BaseModel):
    """Join an existing company by id (controlled membership)."""

    model_config = ConfigDict(extra="forbid")

    company_id: int


class MembershipInfo(BaseModel):
    """A company the user belongs to, with their role."""

    company_id: int
    company_name: str
    role: str


class MeResponse(BaseModel):
    """Current authenticated user and their memberships."""

    user_id: int
    email: str
    email_verified: bool = False
    memberships: list[MembershipInfo]
    csrf_token: str


# --- Company profile ---------------------------------------------------------

class CompanyProfileInput(BaseModel):
    """Create/update payload for the company profile.

    ``name`` is required; all other fields are optional. Input is validated by
    Pydantic before persistence (Req 10.1).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=120)
    size: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=120)
    contact_email: EmailStr | None = None


class CompanyProfileResponse(BaseModel):
    """Company profile returned to the client."""

    id: int
    name: str
    industry: str | None = None
    size: str | None = None
    country: str | None = None
    contact_email: str | None = None
    created_at: datetime
    updated_at: datetime


class LegacyDataInfo(BaseModel):
    """Count of pre-existing unowned records available to claim (Req 5)."""

    unowned_assessments: int
    unowned_profiles: int


class LegacyClaimResult(BaseModel):
    """Result of claiming legacy records into the active company."""

    claimed_assessments: int
    claimed_profiles: int


# --- Invitations -------------------------------------------------------------

class EmailInviteInput(BaseModel):
    """Create an email-bound invitation (admin only)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class LinkInviteInput(BaseModel):
    """Create a shareable link invitation (admin only)."""

    model_config = ConfigDict(extra="forbid")

    expires_in_hours: int = Field(default=72, ge=1, le=720)
    max_uses: int = Field(default=1, ge=1, le=100)


class InvitationResponse(BaseModel):
    """Invitation metadata. Never includes the token hash."""

    id: int
    invite_type: str
    email: str | None = None
    role: str
    status: str
    max_uses: int
    use_count: int
    created_at: datetime
    expires_at: datetime


class InvitationCreatedResponse(InvitationResponse):
    """Returned once at creation. ``share_url`` carries the raw token for links.

    The raw token is returned exactly once and never stored or logged.
    """

    share_url: str | None = None


class InvitationValidateResponse(BaseModel):
    """Safe, non-consuming validation of an invitation token."""

    valid: bool
    status: str
    company_name: str | None = None
    invite_type: str | None = None
    requires_email: str | None = None  # the email that must match, if email-type


class InvitationAcceptInput(BaseModel):
    """Accept an invitation by token."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=10, max_length=256)


class InvitationAcceptResult(BaseModel):
    """Result of accepting an invitation."""

    company_id: int
    company_name: str
    role: str
    already_member: bool = False


# --- Demo mode ---------------------------------------------------------------

class DemoResponse(BaseModel):
    """Sample fintech company profile plus prefilled answers (Req 7.1)."""

    company: dict[str, str]
    answers: dict[str, AnswerValue]


# --- Errors ------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Consistent error body shape (Req 11.2)."""

    message: str
    error_ref: str
