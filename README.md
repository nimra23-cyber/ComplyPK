# ComplyPK

**ComplyPK** is an open-source **cyber-security readiness assessment** web app for
Pakistani SMEs and fintechs. A user answers 20 yes/partial/no questions across six
security domains and receives an overall and per-domain readiness score, gaps mapped
to **ISO 27001** and **NIST CSF** controls with severity, a prioritized remediation
plan, and an exportable Markdown report.

> **Disclaimer:** ComplyPK provides a **readiness assessment only**. It does **not**
> constitute certification or a guarantee of compliance with any standard or
> regulation.

## Architecture

```
ComplyPK/
├── backend/            FastAPI service (routers → services → repositories → models)
│   ├── app/
│   │   ├── main.py             App entry, CORS, error handlers, router wiring
│   │   ├── config.py           Env-var configuration (fail-fast)
│   │   ├── db.py               SQLAlchemy engine/session + init_db
│   │   ├── schemas.py          Pydantic request/response models
│   │   ├── errors.py           Centralized error handling ({message, error_ref})
│   │   ├── models/             ORM model (single `assessments` table, JSON columns)
│   │   ├── repositories/       AssessmentRepository (data access)
│   │   ├── services/           content_loader, scoring, gap_mapping, remediation, report
│   │   ├── routers/            questionnaire, assessments, demo
│   │   └── data/               questions.json, control_mapping.json, demo.json
│   ├── tests/          pytest suite
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/           Static app (plain HTML/CSS/JS — no build step)
    ├── index.html
    ├── styles.css
    ├── app.js
    └── config.js       window.API_BASE_URL (the ONLY place the backend URL is set)
```

- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Pydantic. SQLite by default,
  PostgreSQL in production via `DATABASE_URL`.
- **Frontend:** plain HTML/CSS/JS calling the REST API. No React/Vite/Node required.

## Environment variables

Configuration is read from the environment at startup (see `.env.example`). Secrets
are never committed.

| Variable | Required | Purpose | Default |
| --- | --- | --- | --- |
| `ALLOWED_FRONTEND_ORIGIN` | **Yes** | Exact origin allowed by CORS. Backend refuses to start if unset. | — |
| `DATABASE_URL` | No | DB connection string (PostgreSQL in prod). | local SQLite `complypk.db` |
| `LLM_API_KEY` | No | Credential for the external LLM used for remediation plans. | unset → template fallback |

Copy `.env.example` to `.env` for local reference, but note the app reads real
OS environment variables (it does not auto-load `.env`). **Do not commit `.env`.**

## Run locally (Windows PowerShell)

### Backend

```powershell
cd backend
python -m venv venv                      # first time only
.\venv\Scripts\python.exe -m pip install -r requirements.txt   # first time only
$env:ALLOWED_FRONTEND_ORIGIN="http://localhost:5173"
.\venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000
```

Backend is now at `http://localhost:8000` (health: `GET /health`).

### Frontend

The frontend is static. Serve the `frontend/` folder on the origin configured in
`ALLOWED_FRONTEND_ORIGIN` (default `http://localhost:5173`):

```powershell
cd frontend
python -m http.server 5173
```

Open `http://localhost:5173`. Ensure `frontend/config.js` points at the backend:

```js
window.API_BASE_URL = "http://localhost:8000";
```

## Run tests

```powershell
cd backend
$env:ALLOWED_FRONTEND_ORIGIN="http://localhost:5173"
.\venv\Scripts\python.exe -m pytest -q
```

## Implemented features

- **Questionnaire** — 20 questions across Access Control, Backup & Recovery,
  Patching, Incident Response, Vendor Risk, Data Protection (`GET /api/questionnaire`).
- **Assessment scoring** — overall + per-domain readiness scores (weights
  yes=1.0, partial=0.5, no=0.0), persisted (`POST /api/assessments`).
- **Gap mapping** — failed/partial answers mapped to ISO 27001 / NIST CSF with
  severity (no→high, partial→medium) from an editable `control_mapping.json`.
- **History** — list and open past assessments (`GET /api/assessments`,
  `GET /api/assessments/{id}`).
- **Remediation plan** — prioritized steps; LLM best-effort with a deterministic
  template fallback (`POST`/`GET /api/assessments/{id}/remediation`).
- **Report export** — Markdown report with score, domains, gaps, mapping, plan, and
  disclaimer (`GET /api/assessments/{id}/report?format=markdown`).
- **Demo mode** — sample fintech company with prefilled answers (`GET /api/demo`).
- **Frontend** — responsive questionnaire, results (scores/gaps/remediation),
  history, demo prefill, and report download.
- **Security/robustness** — env-driven config, exact-origin CORS, Pydantic input
  validation, centralized safe error responses (no stack traces or secrets leaked).

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness probe |
| GET | `/api/questionnaire` | Questionnaire grouped by domain |
| POST | `/api/assessments` | Submit answers → score, map gaps, persist |
| GET | `/api/assessments` | Assessment history (most recent first) |
| GET | `/api/assessments/{id}` | Single assessment |
| POST | `/api/assessments/{id}/remediation` | Generate + cache remediation plan |
| GET | `/api/assessments/{id}/remediation` | Get (or generate) remediation plan |
| GET | `/api/assessments/{id}/report?format=markdown` | Export Markdown report |
| GET | `/api/demo` | Demo company profile + prefilled answers |

## Deployment

### Backend (Docker)

```bash
cd backend
docker build -t complypk-backend .
docker run -p 8000:8000 \
  -e ALLOWED_FRONTEND_ORIGIN="https://your-frontend.example" \
  -e DATABASE_URL="postgresql+psycopg://user:pass@host:5432/dbname" \
  complypk-backend
```

Deploy to any container host (Render, Railway, Fly.io, etc.). Set
`ALLOWED_FRONTEND_ORIGIN` to the deployed frontend URL and `DATABASE_URL` to a
managed PostgreSQL instance.

### Frontend (static host)

1. Deploy the backend first and note its public URL.
2. Set `frontend/config.js` → `window.API_BASE_URL` to the deployed backend URL.
3. Deploy the `frontend/` folder to a static host (Netlify, Vercel, GitHub Pages,
   Cloudflare Pages).
4. Set the backend's `ALLOWED_FRONTEND_ORIGIN` to the deployed frontend origin.

## Team invitations

Company **admins** can invite teammates (who always join as **members** — invitations
never grant admin). Two mechanisms are supported:

- **Email invitation** (`POST /api/invitations/email`) — bound to the recipient's
  email. Requires SMTP to be configured; acceptance requires the accepting account
  to have a **verified, matching** email. If SMTP is not configured the endpoint
  returns 503 and no invitation is created; if delivery fails it returns 502 and the
  invitation is rolled back (never a false "sent").
- **Shareable link** (`POST /api/invitations/link`) — returns a one-time `share_url`
  (the raw token is shown once, never stored or logged). Single-use by default;
  `max_uses > 1` creates a reusable link that stays valid until used up or expired —
  share those only through trusted channels.

Other endpoints: `GET /api/invitations` (admin list), `POST /api/invitations/{id}/revoke`
(admin), `GET /api/invitations/validate?token=...` (authenticated, non-consuming),
`POST /api/invitations/accept` (authenticated). Opening/validating a link never
consumes it; acceptance is explicit and atomic (no duplicate memberships, safe under
concurrency). All management is scoped to the active company via the server-side
authorization dependency — Company A can never manage or accept into Company B.

### Email verification

Email-bound invitations require a verified email. To verify:
`POST /api/auth/request-verification` emails a single-use link (the raw token is
**only** sent by email, never returned by the API), and `POST /api/auth/verify-email`
redeems it. Without SMTP configured, verification requests return 503 — so email
invitations cannot be accepted in that environment, while shareable links still work.

### Invitation / verification URLs

Links are built from `ALLOWED_FRONTEND_ORIGIN` (never a client Host header) as
`<origin>/index.html#invite=<token>` and `<origin>/index.html#verify=<token>`. The
frontend reads the token from the fragment, clears it from the address bar, validates
without consuming, and only redeems on explicit user action.

### Email provider setup

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (see
`.env.example`). Credentials live only in the environment. STARTTLS is used.

## Limitations

- **No authentication / authorization** — out of scope; do not expose sensitive data.
- **PDF export is not implemented** — Markdown is the supported report format.
- **LLM remediation** falls back to deterministic templates unless `LLM_API_KEY` is
  configured and wired to a client (`services/remediation_service.py`).
- **Schema migrations** rely on `create_all` (additive). There is no migration tool
  for altering existing columns in a populated production database.
- This tool is a **readiness assessment**, not certification or guaranteed compliance.

## License

Open source. See repository for details.
