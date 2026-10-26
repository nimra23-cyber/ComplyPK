# Implementation Plan: ComplyPK

## Overview

This plan builds the minimum needed for a working, deployed demo of ComplyPK: a layered FastAPI backend (routers → services → repositories → models) plus a static frontend, both deployable to managed hosts. A deploy checkpoint comes early (hello-world backend + frontend) before any business logic. Backend is Python 3.11 + FastAPI + SQLAlchemy + Pydantic, with pytest/Hypothesis tests for scoring, gap mapping, and the fallback generator (Req 12.6). Tasks marked optional (`*`) can be skipped for the demo.

## Tasks

- [x] 1. Project setup and configuration
  - Create `/backend` and `/frontend` folders with `/backend/app/{routers,services,repositories,models}` package structure
  - Add `backend/requirements.txt` (fastapi, uvicorn, sqlalchemy, pydantic, pytest, hypothesis, httpx)
  - Add `.env.example` documenting `ALLOWED_FRONTEND_ORIGIN`, `DATABASE_URL`, `LLM_API_KEY` with placeholder values only
  - Add `.gitignore` excluding `.env` and secret-bearing files
  - Implement `app/config.py` reading env vars at startup: default `DATABASE_URL` to local SQLite, fail fast if `ALLOWED_FRONTEND_ORIGIN` is unset or `DATABASE_URL` is malformed (without echoing its value)
  - _Requirements: 12.1, 9.1, 9.2, 9.4, 9.5, 9.6, 9.7_

- [x] 2. Deployable hello-world backend and frontend (early deploy checkpoint)
  - [x] 2.1 Minimal FastAPI app with health endpoint and CORS
    - Implement `app/main.py` creating the FastAPI app, a `GET /health` endpoint, and `CORSMiddleware` using `ALLOWED_FRONTEND_ORIGIN` from config
    - Add a `Dockerfile` (or documented `pip install -r requirements.txt && uvicorn app.main:app` run steps) for the backend host
    - _Requirements: 12.4, 12.5, 12.7, 9.1_
  - [x] 2.2 Minimal static frontend page
    - Create `/frontend/index.html` + `app.js` that reads an injected `API_BASE_URL` and calls `/health`, with build/deploy notes for static hosting
    - _Requirements: 12.1, 12.7_
  - [x] 2.3 Checkpoint - deploy hello-world backend and frontend
    - Ensure health endpoint responds and frontend reaches it; ask the user if questions arise.

- [x] 3. Data models and schemas
  - [x] 3.1 SQLAlchemy Assessment model and single `assessments` table
    - Define `app/models/assessment.py` with `id`, `answers` (JSON), `overall_score`, `domain_scores` (JSON), `gaps` (JSON), `remediation_plan` (JSON nullable), `created_at`; wire DB engine/session from `DATABASE_URL`
    - _Requirements: 2.4, 2.5, 4.2_
  - [x] 3.2 Pydantic schemas
    - Define `AnswerSubmission`, `QuestionnaireResponse`/`Question`, `AssessmentResponse`, `AssessmentSummary`, `RemediationPlanResponse`, `ErrorResponse`
    - _Requirements: 12.3, 10.1, 1.3, 4.5, 11.2_
  - [x] 3.3 JSON content files and loader
    - Add `questions.json` (20 questions, six domains), `control_mapping.json`, `demo.json`; implement `ContentLoader` that validates them and raises a typed error (no partial data, no stack trace)
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 3.4, 7.4_

- [x] 4. Scoring and gap-mapping services
  - [x] 4.1 Implement ScoringService
    - Compute overall score `round(sum(weight)/20*100)` and per-domain scores with weights yes=1.0, partial=0.5, no=0.0, clamped to [0,100]
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ]* 4.2 Write property tests for ScoringService
    - **Property 1: Overall score formula and bounds** (Hypothesis, ≥100 iterations)
    - **Property 2: Domain score formula and bounds**
    - **Validates: Requirements 2.1, 2.2, 2.3**
  - [x] 4.3 Implement GapMappingService
    - Classify "no"/"partial" answers as gaps, attach ISO/NIST refs from `control_mapping.json` (empty list when unmapped), assign severity no→high, partial→medium
    - _Requirements: 3.1, 3.2, 3.3, 3.5_
  - [ ]* 4.4 Write property tests for GapMappingService
    - **Property 5: Gap classification matches non-passing answers**
    - **Property 6: Gap control references match the mapping**
    - **Property 7: Gap severity rule**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.5**

- [x] 5. Repository and API routes
  - [x] 5.1 Implement AssessmentRepository
    - `save`, `list` (ordered `created_at DESC, id DESC`), `get`, `update_remediation`
    - _Requirements: 2.4, 4.1, 4.2, 4.3_
  - [x] 5.2 Implement questionnaire and assessment routers
    - `GET /api/questionnaire` (grouped by domain, 500 on load/invalid), `POST /api/assessments` (validate via schema, score, map gaps, persist, return stored; 422 with offending ids/values and no persistence on invalid), `GET /api/assessments` (history, empty list ok), `GET /api/assessments/{id}` (404 unknown, 422 invalid id)
    - Add centralized error handler returning `{ message, error_ref }` with no stack/secret leaks
    - _Requirements: 1.1, 1.4, 2.4, 2.5, 2.6, 4.1, 4.3, 4.4, 4.5, 4.6, 10.2, 10.4, 11.1, 11.2_
  - [ ]* 5.3 Write API tests for routes
    - **Property 3: Assessment persistence round-trip**
    - **Property 4: Invalid submission is rejected without persistence**
    - **Property 8: History ordering**
    - Plus example tests: questionnaire fields, empty history 200 `[]`, unknown/invalid id 404/422
    - **Validates: Requirements 2.4, 2.5, 2.6, 4.1, 4.3, 10.2, 10.4**

- [x] 6. Remediation service with fallback
  - [x] 6.1 Implement RemediationService and FallbackGenerator
    - Best-effort LLM call (30s cap) ordered by severity then ascending question id with ≥1 step per gap; on missing `LLM_API_KEY`, failure, or timeout use template fallback and return 200 with a `source` indicator; add `POST /api/assessments/{id}/remediation` (404 unknown id)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7_
  - [ ]* 6.2 Write property tests for remediation
    - **Property 9: Remediation step ordering**
    - **Property 10: Remediation covers every gap (including fallback)**
    - **Validates: Requirements 5.2, 5.3, 5.4**

- [x] 7. Markdown report export
  - [x] 7.1 Implement ReportService and report router
    - Render Markdown report (default) with overall score, six domain scores, each gap with severity and ISO/NIST refs, remediation section (placeholder if none), and the fixed disclaimer; never produce a report without the disclaimer; `GET /api/assessments/{id}/report` (404 unknown id, 422 invalid format)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 8.1, 8.3, 8.4_
  - [ ]* 7.2 Write tests for report export
    - **Property 11: Report content completeness**
    - **Property 12: Report always contains the disclaimer**
    - **Property 13: Readiness-only wording**
    - **Validates: Requirements 6.3, 6.5, 8.1, 8.3**

- [x] 8. Frontend pages
  - [x] 8.1 Questionnaire page
    - Fetch questionnaire grouped by domain, render yes/partial/no inputs, submit to `POST /api/assessments`, handle API errors interactively
    - _Requirements: 1.3, 11.4, 11.5_
  - [x] 8.2 Results page
    - Display overall and domain scores, gaps with severity and control refs, remediation plan, and the disclaimer on the same view without extra interaction; use readiness-only wording
    - _Requirements: 8.1, 8.2_
  - [x] 8.3 History page
    - List past assessments (id, created_at, overall_score) and open a single assessment
    - _Requirements: 4.1, 4.5_

- [x] 9. Demo mode
  - [x] 9.1 Backend demo endpoint
    - `GET /api/demo` returns the sample fintech profile plus one valid answer per question from `demo.json`; 500 if demo data missing/invalid
    - _Requirements: 7.1, 7.4, 7.5_
  - [x] 9.2 Frontend demo prefill
    - Add a demo button that loads demo data and prefills the questionnaire, allowing submission of prefilled answers
    - _Requirements: 7.2, 7.3_

- [x] 10. README and final checkpoint
  - Write README with project overview, env var setup, backend run/deploy (Dockerfile/uvicorn), frontend build/deploy notes, and how to run `pytest`
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 12.6, 12.7, 9.6_

### Optional Tasks

- [ ]* 11. PDF report export (OPTIONAL)
  - Add PDF format support to ReportService; requesting `format=pdf` returns a PDF or a clear "not available" response while markdown stays fully supported
  - _Requirements: 6.1_

- [ ]* 12. Policy generator (OPTIONAL)
  - Generate a basic security policy document from assessment gaps
  - _Requirements: 5.3_

## Notes

- Tasks marked with `*` are optional (property/unit tests and the optional features in tasks 11–12) and can be skipped for a faster demo. Core implementation tasks are never optional.
- Each task references specific requirements for traceability.
- Property tests use Hypothesis (≥100 iterations) and satisfy Req 12.6 coverage for scoring (P1, P2), gap mapping (P5, P6, P7), and the fallback generator (P10).
- The early deploy checkpoint (task 2) lands a working backend + frontend before business logic.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1", "4.3", "5.1"] },
    { "id": 4, "tasks": ["4.2", "4.4", "5.2"] },
    { "id": 5, "tasks": ["5.3", "6.1", "7.1"] },
    { "id": 6, "tasks": ["6.2", "7.2", "9.1"] },
    { "id": 7, "tasks": ["8.1", "8.2", "8.3", "9.2"] },
    { "id": 8, "tasks": ["11", "12"] }
  ]
}
```
