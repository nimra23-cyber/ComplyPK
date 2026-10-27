// ComplyPK frontend configuration.
//
// This is the SINGLE place the backend base URL is configured.
// At deploy time this value is replaced per environment (e.g. the
// static host build/deploy step overwrites it with the deployed
// backend URL). Do NOT put secrets here — this file is served to
// the browser as-is.
window.API_BASE_URL = "https://complypk.onrender.com";
