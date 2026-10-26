# ComplyPK Frontend

Responsive single-page ComplyPK interface built with **plain HTML, CSS, and
JavaScript** — no build step, bundler, or Node dependencies.

## Files

- `config.js` — the SINGLE place the backend base URL is configured via
  `window.API_BASE_URL`. Set this per environment at deploy time. No secrets here.
- `index.html` — app shell and views (assessment, results, history).
- `styles.css` — styling (responsive, mobile-friendly).
- `app.js` — all logic: questionnaire load/submit, results (scores, gaps,
  remediation), history, demo prefill, and report download. Every backend call uses
  `window.API_BASE_URL`; errors are surfaced to the user (never faked as success).

## Run locally

Serve this folder on the origin configured in the backend's
`ALLOWED_FRONTEND_ORIGIN` (default `http://localhost:5173`):

```
python -m http.server 5173
```

Then open http://localhost:5173. Ensure `config.js` points at the backend
(`http://localhost:8000` by default).

## Deploy notes

Deploy to any static host (Netlify, Vercel, GitHub Pages, Cloudflare Pages). Before
deploying, set `config.js`'s `API_BASE_URL` to the deployed backend URL, and set the
backend's `ALLOWED_FRONTEND_ORIGIN` to this frontend's deployed origin.
