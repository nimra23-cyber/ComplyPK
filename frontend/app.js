// ComplyPK frontend application (plain JS, no framework / build step).
//
// Every backend call uses window.API_BASE_URL (from config.js). The UI never
// fabricates scores, companies, or history, and never shows success when an API
// call fails.

(function () {
  "use strict";

  var REQUEST_TIMEOUT_MS = 30000;

  var DISCLAIMER =
    "ComplyPK provides a readiness assessment only. It does not constitute " +
    "certification or a guarantee of compliance with any standard or regulation.";

  var DOMAIN_DESC = {
    "Access Control": "Who can access systems and data, and how access is controlled.",
    "Backup & Recovery": "Protecting data with backups and the ability to restore it.",
    "Patching": "Keeping systems and software updated against known vulnerabilities.",
    "Incident Response": "Preparedness to detect, report, and respond to incidents.",
    "Vendor Risk": "Managing security risk from third-party vendors and suppliers.",
    "Data Protection": "Encrypting, classifying, and restricting access to sensitive data.",
  };

  // ---- API helpers --------------------------------------------------------

  function baseUrl() {
    return (window.API_BASE_URL || "").replace(/\/+$/, "");
  }

  function ApiError(status, message) {
    this.status = status;
    this.message = message || "An unexpected error occurred.";
  }

  function defaultMessage(status, path) {
    if (status === 404) {
      return "Endpoint not found (404): " + path +
        ". The backend may be out of date — restart the API server so the latest routes are loaded.";
    }
    if (status === 413) return "The request was too large (413).";
    if (status === 422) return "The submitted data was invalid (422). Please check the fields.";
    if (status === 500) return "The server encountered an error (500). Please try again.";
    if (status === 503) return "The service is temporarily unavailable (503). Please try again shortly.";
    return "Request failed (" + status + ").";
  }

  // Auth/session state (populated from /api/auth/me or login).
  var auth = { user: null, csrf: null, memberships: [], activeCompanyId: null };

  function activeCompanyName() {
    var m = auth.memberships.filter(function (x) { return x.company_id === auth.activeCompanyId; })[0];
    return m ? m.company_name : null;
  }

  var UNSAFE = { POST: 1, PUT: 1, PATCH: 1, DELETE: 1 };

  function apiFetch(path, options) {
    options = options || {};
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, REQUEST_TIMEOUT_MS);
    options.signal = controller.signal;
    // Always send the session cookie (HttpOnly) with cross-origin requests.
    options.credentials = "include";

    // Inject CSRF token for state-changing requests and the active company id.
    var headers = options.headers || {};
    var method = (options.method || "GET").toUpperCase();
    if (UNSAFE[method] && auth.csrf) headers["X-CSRF-Token"] = auth.csrf;
    if (auth.activeCompanyId != null) headers["X-Company-Id"] = String(auth.activeCompanyId);
    options.headers = headers;

    return fetch(baseUrl() + path, options)
      .then(function (resp) {
        clearTimeout(timer);
        var ct = resp.headers.get("content-type") || "";
        if (ct.indexOf("application/json") !== -1) {
          return resp.json().then(function (body) {
            if (!resp.ok) throw new ApiError(resp.status, (body && body.message) || defaultMessage(resp.status, path));
            return body;
          });
        }
        return resp.text().then(function (text) {
          if (!resp.ok) throw new ApiError(resp.status, defaultMessage(resp.status, path));
          return { _text: text };
        });
      })
      .catch(function (err) {
        clearTimeout(timer);
        if (err instanceof ApiError) throw err;
        if (err && err.name === "AbortError") throw new ApiError(0, "The request timed out. Please try again.");
        throw new ApiError(0, "Could not reach the backend at " + (baseUrl() || "(unset)") + ". Is the server running?");
      });
  }

  // ---- DOM helpers --------------------------------------------------------

  function $(s) { return document.querySelector(s); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function esc(s) { var d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }

  function showBanner(message, kind, onRetry) {
    var b = $("#banner");
    b.innerHTML = "";
    b.appendChild(el("span", null, message));
    if (onRetry) {
      var r = el("button", "btn btn-ghost retry", "Retry");
      r.addEventListener("click", onRetry);
      b.appendChild(r);
    }
    b.className = "banner " + (kind || "error");
    b.hidden = false;
  }
  function clearBanner() { var b = $("#banner"); b.hidden = true; b.innerHTML = ""; }

  // ---- Risk helper --------------------------------------------------------

  function riskLevel(score) {
    if (score >= 75) return "low";
    if (score >= 50) return "medium";
    return "high";
  }
  function riskLabel(score) {
    var r = riskLevel(score);
    return r === "low" ? "Low risk" : r === "medium" ? "Medium risk" : "High risk";
  }

  // ---- State --------------------------------------------------------------

  var state = {
    domains: {},
    questions: [],
    answers: {},
    lastResult: null,
    workspace: null,  // demo company name when demo is loaded
    profile: null,    // saved CompanyProfile (real, from backend) or null
  };

  var VIEW_TITLES = {
    overview: "Overview",
    company: "Company Profile",
    assess: "New Assessment",
    results: "Assessment Results",
    history: "Assessment History",
    remediation: "Remediation Center",
    reports: "Reports",
    demo: "Demo Workspace",
  };

  // ---- View switching -----------------------------------------------------

  function showView(name) {
    ["overview", "company", "assess", "results", "history", "remediation", "reports", "demo"].forEach(function (v) {
      var sec = $("#view-" + v);
      if (sec) sec.hidden = v !== name;
    });
    document.querySelectorAll(".side-link").forEach(function (b) {
      b.classList.toggle("active", b.dataset.view === name);
    });
    $("#top-view-title").textContent = VIEW_TITLES[name] || "ComplyPK";
    closeSidebar();
    clearBanner();
  }

  function closeSidebar() { $("#sidebar").classList.remove("open"); }

  // ---- Health -------------------------------------------------------------

  function checkHealth() {
    var set = function (ok, text) {
      ["#health-dot", "#conn-dot"].forEach(function (s) { $(s).className = "dot " + (ok ? "ok" : "fail"); });
      $("#health-text").textContent = text;
      $("#conn-text").textContent = ok ? "Backend online" : "Backend offline";
    };
    return apiFetch("/health")
      .then(function () { set(true, "online"); return true; })
      .catch(function () { set(false, "offline"); return false; });
  }

  // ---- Overview -----------------------------------------------------------

  function renderOverview() {
    var root = $("#view-overview");
    root.innerHTML = "";

    var hero = el("div", "card hero");
    var ht = el("div", "hero-text");
    ht.appendChild(el("h2", null, "Welcome to ComplyPK"));
    ht.appendChild(el("p", "muted",
      "Run a cyber-security readiness assessment, review gaps mapped to ISO 27001 and NIST CSF, and get a prioritized remediation plan."));
    var act = el("div", "actions");
    var start = el("button", "btn", "Start assessment");
    start.addEventListener("click", goToAssessmentOrOnboarding);
    act.appendChild(start);
    ht.appendChild(act);
    hero.appendChild(ht);
    var steps = el("ol", "hero-steps");
    ["Answer by domain", "Get scored instantly", "Review gaps & fixes", "Export a report"].forEach(function (t, i) {
      var li = document.createElement("li");
      li.appendChild(el("span", null, String(i + 1)));
      li.appendChild(document.createTextNode(" " + t));
      steps.appendChild(li);
    });
    hero.appendChild(steps);
    root.appendChild(hero);

    var recent = el("div", "card");
    recent.appendChild(el("h3", null, "Recent assessments"));
    var listWrap = el("div", null);
    listWrap.appendChild(el("p", "loading", "Loading recent activity…"));
    recent.appendChild(listWrap);
    root.appendChild(recent);

    apiFetch("/api/assessments")
      .then(function (rows) {
        listWrap.innerHTML = "";
        if (!rows || rows.length === 0) {
          listWrap.appendChild(renderEmptyState());
          return;
        }
        // Latest score + risk (real data only).
        var latest = rows[0];
        var statRow = el("div", "stat-row");
        statRow.appendChild(statCard("Latest score", latest.overall_score + " / 100"));
        statRow.appendChild(statCard("Latest risk level", riskLabel(latest.overall_score)));
        statRow.appendChild(statCard("Assessments saved", String(rows.length)));
        listWrap.appendChild(statRow);

        rows.slice(0, 5).forEach(function (row) {
          listWrap.appendChild(historyRow(row));
        });
      })
      .catch(function (err) {
        listWrap.innerHTML = "";
        var p = el("p", "muted", "Recent activity is unavailable: " + err.message);
        listWrap.appendChild(p);
        var retry = el("button", "btn btn-ghost", "Retry");
        retry.addEventListener("click", renderOverview);
        listWrap.appendChild(retry);
      });
  }

  function statCard(label, value) {
    var s = el("div", "stat");
    s.appendChild(el("div", "label", label));
    s.appendChild(el("div", "value", value));
    return s;
  }

  function renderEmptyState() {
    var wrap = el("div", "empty-state");
    wrap.innerHTML =
      '<svg class="ei" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2 4 5v6c0 5 3.4 8.5 8 11 4.6-2.5 8-6 8-11V5l-8-3Z"/></svg>';
    wrap.appendChild(el("h3", null, "No assessments yet"));
    wrap.appendChild(el("p", "muted", "Run your first readiness assessment to see your score, gaps, and remediation plan here."));
    var btn = el("button", "btn", "Run your first assessment");
    btn.addEventListener("click", goToAssessmentOrOnboarding);
    wrap.appendChild(btn);
    return wrap;
  }

  // ---- Questionnaire ------------------------------------------------------

  function loadQuestionnaire() {
    clearBanner();
    var btn = $("#btn-load");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Loading…'; }
    return apiFetch("/api/questionnaire")
      .then(function (data) {
        state.domains = data.domains || {};
        renderQuestionnaire();
        return true;
      })
      .catch(function (err) {
        showBanner(err.message, "error", loadQuestionnaire);
        return false;
      })
      .finally(function () {
        if (btn) { btn.disabled = false; btn.textContent = "Load questionnaire"; }
      });
  }

  function renderQuestionnaire() {
    var container = $("#domains");
    container.innerHTML = "";
    state.questions = [];

    Object.keys(state.domains).forEach(function (domain) {
      var items = state.domains[domain] || [];
      var block = el("div", "domain-block card");
      var head = el("div", "domain-head");
      head.appendChild(el("h3", null, domain));
      head.appendChild(el("span", "domain-count", items.length + " questions"));
      block.appendChild(head);
      block.appendChild(el("p", "domain-desc", DOMAIN_DESC[domain] || ""));

      items.forEach(function (q) {
        state.questions.push(q);
        var qEl = el("div", "question");
        var textEl = el("div", "q-text");
        textEl.innerHTML = '<span class="q-id">' + esc(q.id) + "</span>" + esc(q.text);
        qEl.appendChild(textEl);
        var choices = el("div", "choices");
        (q.allowed_answers || ["yes", "partial", "no"]).forEach(function (val) {
          var wrap = el("div", "choice " + val);
          var input = document.createElement("input");
          input.type = "radio"; input.name = q.id; input.id = q.id + "_" + val; input.value = val;
          if (state.answers[q.id] === val) input.checked = true;
          input.addEventListener("change", function () { state.answers[q.id] = val; updateProgress(); });
          var label = el("label", null, val.charAt(0).toUpperCase() + val.slice(1));
          label.setAttribute("for", input.id);
          wrap.appendChild(input); wrap.appendChild(label);
          choices.appendChild(wrap);
        });
        qEl.appendChild(choices);
        block.appendChild(qEl);
      });
      container.appendChild(block);
    });

    $("#total-count").textContent = state.questions.length;
    $("#questionnaire-form").hidden = false;
    updateProgress();
  }

  function updateProgress() {
    var total = state.questions.length;
    var answered = state.questions.filter(function (q) { return state.answers[q.id]; }).length;
    $("#answered-count").textContent = answered;
    var pct = total ? Math.round((answered / total) * 100) : 0;
    $("#progress-label").textContent = pct + "% complete";
    $("#progress-fill").style.width = pct + "%";
    $("#btn-submit").disabled = total === 0 || answered !== total;
  }

  function submitAssessment(ev) {
    ev.preventDefault();
    clearBanner();
    var btn = $("#btn-submit");
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Submitting…';
    apiFetch("/api/assessments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: state.answers }),
    })
      .then(function (result) {
        state.lastResult = result;
        renderResults(result);
        showView("results");
      })
      .catch(function (err) { showBanner(err.message); })
      .finally(function () { btn.disabled = false; btn.textContent = "Submit assessment"; });
  }

  function resetAnswers() {
    openConfirm("Discard answers?", "This will clear all your current answers.", function () {
      state.answers = {};
      document.querySelectorAll("#domains input[type=radio]").forEach(function (i) { i.checked = false; });
      updateProgress();
      var note = $("#demo-note"); if (note) { note.hidden = true; note.textContent = ""; }
    });
  }

  // ---- Results ------------------------------------------------------------

  function renderResults(r) {
    $("#overall-score").textContent = r.overall_score;
    // Animate gauge: circumference ~327 for r=52.
    var circ = 327;
    var offset = circ - (circ * (r.overall_score / 100));
    var fill = $("#gauge-fill");
    // Inject gradient + color by risk.
    ensureGaugeGradient();
    var risk = riskLevel(r.overall_score);
    var color = risk === "low" ? "#15803d" : risk === "medium" ? "#d97706" : "#d1332e";
    fill.style.stroke = color;
    // reset then set for transition
    fill.style.strokeDashoffset = circ;
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { fill.style.strokeDashoffset = offset; });
    });

    var badge = $("#risk-badge");
    badge.textContent = riskLabel(r.overall_score);
    badge.className = "risk-badge " + risk;

    $("#result-meta").textContent = "Assessment #" + r.id + " • " + new Date(r.created_at).toLocaleString();
    $("#results-disclaimer").textContent = r.disclaimer || DISCLAIMER;

    var dg = $("#domain-scores");
    dg.innerHTML = "";
    Object.keys(r.domain_scores || {}).forEach(function (d) {
      var score = r.domain_scores[d];
      var card = el("div", "domain-score");
      var name = el("div", "name");
      name.appendChild(el("span", null, d));
      name.appendChild(el("span", "num", score + " / 100"));
      card.appendChild(name);
      var bar = el("div", "bar"); var sp = el("span"); sp.style.width = score + "%"; bar.appendChild(sp);
      card.appendChild(bar);
      dg.appendChild(card);
    });

    var gc = $("#gaps");
    gc.innerHTML = "";
    $("#gap-count").textContent = (r.gaps || []).length + " found";
    if (!r.gaps || r.gaps.length === 0) {
      gc.appendChild(el("p", "no-gaps", "No gaps identified — all controls answered \u201cyes\u201d."));
    } else {
      sortBySeverity(r.gaps).forEach(function (g) { gc.appendChild(gapEl(g)); });
    }

    $("#remediation-card").hidden = true;
    $("#remediation-list").innerHTML = "";
    $("#rem-source").textContent = "";
  }

  function ensureGaugeGradient() {
    var svg = document.querySelector(".gauge svg");
    if (!svg || svg.querySelector("#g")) return;
    var ns = "http://www.w3.org/2000/svg";
    var defs = document.createElementNS(ns, "defs");
    var lg = document.createElementNS(ns, "linearGradient");
    lg.setAttribute("id", "g");
    [["0%", "#2563eb"], ["100%", "#0ea5a4"]].forEach(function (s) {
      var st = document.createElementNS(ns, "stop");
      st.setAttribute("offset", s[0]); st.setAttribute("stop-color", s[1]);
      lg.appendChild(st);
    });
    defs.appendChild(lg);
    svg.insertBefore(defs, svg.firstChild);
  }

  function sortBySeverity(gaps) {
    var order = { high: 0, medium: 1, low: 2 };
    return gaps.slice().sort(function (a, b) {
      return (order[a.severity] - order[b.severity]) || a.question_id.localeCompare(b.question_id);
    });
  }

  function gapEl(g) {
    var gap = el("div", "gap " + g.severity);
    var head = el("div", "gap-head");
    var sev = el("span", "sev " + g.severity, g.severity);
    sev.setAttribute("aria-label", "Severity: " + g.severity);
    head.appendChild(sev);
    head.appendChild(el("strong", null, g.question_id + " — " + g.domain));
    gap.appendChild(head);
    var refs = el("div", "gap-refs");
    refs.innerHTML =
      "<b>ISO 27001:</b> " + esc((g.iso_27001 || []).join(", ") || "—") +
      " &nbsp;•&nbsp; <b>NIST CSF:</b> " + esc((g.nist_csf || []).join(", ") || "—");
    gap.appendChild(refs);
    return gap;
  }

  function loadRemediationInline() {
    if (!state.lastResult) return;
    clearBanner();
    var btn = $("#btn-remediation");
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Generating…';
    apiFetch("/api/assessments/" + state.lastResult.id + "/remediation", { method: "POST" })
      .then(function (plan) {
        var card = $("#remediation-card");
        var list = $("#remediation-list");
        list.innerHTML = "";
        var src = $("#rem-source");
        src.textContent = plan.source === "llm" ? "AI-generated" : "Template (fallback)";
        src.className = "src-badge " + (plan.source === "llm" ? "llm" : "fallback");
        if (!plan.steps || plan.steps.length === 0) {
          list.appendChild(el("li", null, "No remediation steps — no gaps to address."));
        } else {
          plan.steps.forEach(function (s) {
            var li = document.createElement("li");
            li.innerHTML = '<span class="tag ' + esc(s.severity) + '">' + esc(s.severity) + "</span><strong>" +
              esc(s.question_id) + "</strong> — " + esc(s.action);
            list.appendChild(li);
          });
        }
        card.hidden = false;
        card.scrollIntoView({ behavior: "smooth", block: "nearest" });
      })
      .catch(function (err) { showBanner(err.message, "error", loadRemediationInline); })
      .finally(function () { btn.disabled = false; btn.textContent = "View remediation"; });
  }

  function downloadReport(id) {
    clearBanner();
    return apiFetch("/api/assessments/" + id + "/report?format=markdown")
      .then(function (res) {
        var text = res._text != null ? res._text : "";
        var blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url; a.download = "complypk-assessment-" + id + ".md";
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
      })
      .catch(function (err) { showBanner("Report download failed: " + err.message); });
  }

  // ---- Remediation Center -------------------------------------------------

  function renderRemediationCenter() {
    var root = $("#remediation-center");
    root.innerHTML = "";
    if (!state.lastResult) {
      var card = el("div", "card");
      card.appendChild(el("h3", null, "No active assessment"));
      card.appendChild(el("p", "muted", "Submit an assessment or open one from history to generate a remediation plan."));
      var b = el("button", "btn", "Go to history");
      b.addEventListener("click", function () { loadHistory(); showView("history"); });
      card.appendChild(b);
      root.appendChild(card);
      return;
    }

    var loading = el("div", "card loading");
    loading.innerHTML = '<span class="spinner"></span>Generating remediation plan for assessment #' + esc(state.lastResult.id) + "…";
    root.appendChild(loading);

    apiFetch("/api/assessments/" + state.lastResult.id + "/remediation", { method: "POST" })
      .then(function (plan) {
        root.innerHTML = "";
        var head = el("div", "card");
        var srcText = plan.source === "llm"
          ? "These recommendations were generated by an AI model."
          : "These recommendations were generated by ComplyPK's deterministic template engine (no AI key configured).";
        var h = el("h3", null, "Remediation plan for assessment #" + state.lastResult.id);
        var srcBadge = el("span", "src-badge " + (plan.source === "llm" ? "llm" : "fallback"),
          plan.source === "llm" ? "AI-generated" : "Template (fallback)");
        h.appendChild(srcBadge);
        head.appendChild(h);
        head.appendChild(el("p", "muted", srcText));
        root.appendChild(head);

        var bySev = { high: [], medium: [], low: [] };
        (plan.steps || []).forEach(function (s) { (bySev[s.severity] || bySev.low).push(s); });

        [["high", "High severity"], ["medium", "Medium severity"], ["low", "Low severity"]].forEach(function (pair) {
          var items = bySev[pair[0]];
          if (!items || items.length === 0) return;
          var group = el("div", "card rem-group");
          var gh = el("h3", null);
          gh.appendChild(el("span", "sev " + pair[0], pair[0]));
          gh.appendChild(document.createTextNode(" " + pair[1] + " (" + items.length + ")"));
          group.appendChild(gh);
          var ol = el("ol", "rem-list");
          items.forEach(function (s) {
            var li = document.createElement("li");
            li.innerHTML = "<strong>" + esc(s.question_id) + "</strong> — " + esc(s.action);
            ol.appendChild(li);
          });
          group.appendChild(ol);
          root.appendChild(group);
        });

        if (!plan.steps || plan.steps.length === 0) {
          var none = el("div", "card");
          none.appendChild(el("p", "no-gaps", "No gaps to remediate — great work."));
          root.appendChild(none);
        }

        var disc = el("p", "disclaimer", plan.disclaimer || DISCLAIMER);
        root.appendChild(disc);
      })
      .catch(function (err) {
        root.innerHTML = "";
        var card = el("div", "card");
        card.appendChild(el("p", "muted", "Could not generate the remediation plan: " + err.message));
        var retry = el("button", "btn btn-ghost", "Retry");
        retry.addEventListener("click", renderRemediationCenter);
        card.appendChild(retry);
        root.appendChild(card);
      });
  }

  // ---- History ------------------------------------------------------------

  function historyRow(row) {
    var r = el("div", "row");
    var left = el("div");
    left.appendChild(el("div", null, "Assessment #" + row.id));
    left.appendChild(el("div", "meta", new Date(row.created_at).toLocaleString() + " • " + riskLabel(row.overall_score)));
    var right = el("div", "row-actions");
    right.appendChild(el("span", "row-score", row.overall_score + " / 100"));
    var open = el("button", "btn btn-ghost", "Open");
    open.addEventListener("click", function () { openAssessment(row.id); });
    right.appendChild(open);
    r.appendChild(left); r.appendChild(right);
    return r;
  }

  function loadHistory() {
    clearBanner();
    var list = $("#history-list");
    list.innerHTML = '<p class="loading"><span class="spinner"></span>Loading assessments…</p>';
    apiFetch("/api/assessments")
      .then(function (rows) {
        list.innerHTML = "";
        if (!rows || rows.length === 0) { list.appendChild(renderEmptyState()); return; }
        rows.forEach(function (row) { list.appendChild(historyRow(row)); });
      })
      .catch(function (err) {
        list.innerHTML = "";
        var p = el("p", "muted", "Could not load history: " + err.message);
        list.appendChild(p);
        var retry = el("button", "btn btn-ghost", "Retry");
        retry.addEventListener("click", loadHistory);
        list.appendChild(retry);
      });
  }

  function openAssessment(id) {
    clearBanner();
    apiFetch("/api/assessments/" + id)
      .then(function (result) { state.lastResult = result; renderResults(result); showView("results"); })
      .catch(function (err) { showBanner(err.message); });
  }

  // ---- Reports ------------------------------------------------------------

  function loadReports() {
    clearBanner();
    var list = $("#reports-list");
    list.innerHTML = '<p class="loading"><span class="spinner"></span>Loading assessments…</p>';
    apiFetch("/api/assessments")
      .then(function (rows) {
        list.innerHTML = "";
        var note = el("p", "muted", "Markdown report download is available. PDF export is not available in this build.");
        list.appendChild(note);
        if (!rows || rows.length === 0) { list.appendChild(renderEmptyState()); return; }
        rows.forEach(function (row) {
          var r = el("div", "row");
          var left = el("div");
          left.appendChild(el("div", null, "Assessment #" + row.id));
          left.appendChild(el("div", "meta", new Date(row.created_at).toLocaleString() + " • " + row.overall_score + " / 100"));
          var right = el("div", "row-actions");
          var md = el("button", "btn btn-ghost", "Download .md");
          md.addEventListener("click", function () {
            md.disabled = true; md.innerHTML = '<span class="spinner"></span>Preparing…';
            downloadReport(row.id).finally(function () { md.disabled = false; md.textContent = "Download .md"; });
          });
          right.appendChild(md);
          r.appendChild(left); r.appendChild(right);
          list.appendChild(r);
        });
      })
      .catch(function (err) {
        list.innerHTML = "";
        var p = el("p", "muted", "Could not load assessments: " + err.message);
        list.appendChild(p);
        var retry = el("button", "btn btn-ghost", "Retry");
        retry.addEventListener("click", loadReports);
        list.appendChild(retry);
      });
  }

  // ---- Demo ---------------------------------------------------------------

  function setWorkspace(name) {
    state.workspace = name || null;
    var chip = $("#workspace-chip");
    if (name) { chip.hidden = false; chip.textContent = name; }
    else { chip.hidden = true; chip.textContent = ""; }
  }

  function loadDemo(opts) {
    opts = opts || {};
    clearBanner();
    var ensure = state.questions.length
      ? Promise.resolve()
      : apiFetch("/api/questionnaire").then(function (data) { state.domains = data.domains || {}; renderQuestionnaire(); });

    return ensure
      .then(function () { return apiFetch("/api/demo"); })
      .then(function (demo) {
        state.answers = {};
        Object.keys(demo.answers || {}).forEach(function (qid) {
          var val = demo.answers[qid];
          state.answers[qid] = val;
          var input = document.getElementById(qid + "_" + val);
          if (input) input.checked = true;
        });
        updateProgress();
        var name = demo.company && demo.company.name ? demo.company.name : "sample company";
        setWorkspace(name);
        var note = $("#demo-note");
        if (note) { note.hidden = false; note.textContent = "Loaded demo answers for " + name + ". Review and edit, then submit — nothing is submitted automatically."; }
        renderDemoCompany(demo.company);
        return demo;
      })
      .catch(function (err) { showBanner(err.message, "error", function () { loadDemo(opts); }); });
  }

  function renderDemoCompany(company) {
    var root = $("#demo-company");
    if (!root || !company) return;
    root.innerHTML = "";
    Object.keys(company).forEach(function (k) {
      var cell = el("div");
      cell.appendChild(el("div", "k", k));
      cell.appendChild(el("div", null, company[k]));
      root.appendChild(cell);
    });
    root.hidden = false;
  }

  // ---- Company profile ----------------------------------------------------

  function applyProfileToHeader() {
    var chip = $("#workspace-chip");
    // Prefer the saved profile name; else the active company (membership) name;
    // else a neutral placeholder. Never a hardcoded company identity.
    var name = (state.profile && state.profile.name) || activeCompanyName();
    chip.hidden = false;
    chip.textContent = name || "No company profile";
  }

  function loadProfile() {
    // 404 means "no profile yet" — a normal first-run state, not an error.
    return apiFetch("/api/company")
      .then(function (p) { state.profile = p; applyProfileToHeader(); return p; })
      .catch(function (err) {
        if (err.status === 404) { state.profile = null; applyProfileToHeader(); return null; }
        // Other errors (e.g. offline) — leave placeholder, surface quietly.
        applyProfileToHeader();
        return null;
      });
  }

  function fillCompanyForm(p) {
    $("#cf-name").value = p && p.name ? p.name : "";
    $("#cf-industry").value = p && p.industry ? p.industry : "";
    $("#cf-size").value = p && p.size ? p.size : "";
    $("#cf-country").value = p && p.country ? p.country : "";
    $("#cf-email").value = p && p.contact_email ? p.contact_email : "";
  }

  function renderCompanyView() {
    clearBanner();
    $("#company-heading").textContent = state.profile ? "Edit company profile" : "Create company profile";
    fillCompanyForm(state.profile);
    $("#btn-save-company").textContent = state.profile ? "Save changes" : "Save profile";
    // "Continue to assessment" appears only right after a successful save.
    $("#btn-company-to-assess").hidden = true;
    $("#company-saved-note").hidden = true;
    clearFieldError("cf-name"); clearFieldError("cf-email");
    renderLegacyPanel();
  }

  function activeRole() {
    var m = auth.memberships.filter(function (x) { return x.company_id === auth.activeCompanyId; })[0];
    return m ? m.role : null;
  }

  function renderLegacyPanel() {
    var card = $("#legacy-card");
    if (!card) return;
    // Only Company Admins of the active company can see/use this.
    if (activeRole() !== "admin") { card.hidden = true; return; }
    card.hidden = false;

    var summary = $("#legacy-summary");
    var btn = $("#btn-claim-legacy");
    var note = $("#legacy-note");
    note.hidden = true; note.textContent = "";
    summary.textContent = "Checking for unassigned records…";
    btn.disabled = true;

    apiFetch("/api/company/legacy")
      .then(function (info) {
        var a = info.unowned_assessments;
        var p = info.unowned_profiles;
        var total = a + p;
        if (total === 0) {
          summary.textContent = "No unassigned legacy records to claim.";
          btn.disabled = true;
          return;
        }
        summary.textContent =
          "There are " + a + " unassigned assessment(s) and " + p +
          " unassigned profile(s). Claiming assigns them to the currently selected company.";
        btn.disabled = false;
        btn.dataset.count = String(total);
      })
      .catch(function (err) {
        summary.textContent = "Could not check legacy records: " + err.message;
        btn.disabled = true;
      });
  }

  function claimLegacy() {
    var btn = $("#btn-claim-legacy");
    var note = $("#legacy-note");
    var companyName = activeCompanyName() || "the selected company";
    openConfirm(
      "Claim legacy data?",
      "This assigns all existing unassigned records to " + companyName +
        ". Records already owned by another company are not affected.",
      function () {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>Claiming…';
        apiFetch("/api/company/legacy/claim", { method: "POST" })
          .then(function (res) {
            note.hidden = false;
            note.textContent =
              "Claimed " + res.claimed_assessments + " assessment(s) and " +
              res.claimed_profiles + " profile(s).";
            // Refresh profile, dashboard, history, and the legacy panel itself.
            return loadProfile().then(function () {
              applyProfileToHeader();
              updateOnboardingGate();
              renderOverview();
              renderLegacyPanel();
            });
          })
          .catch(function (err) {
            if (err.status === 403) {
              showBanner("Only a Company Admin can claim legacy data.", "error");
            } else {
              showBanner("Could not claim legacy data: " + err.message, "error");
            }
            renderLegacyPanel();
          })
          .finally(function () {
            btn.innerHTML = "Claim legacy data";
          });
      }
    );
  }

  function setFieldError(id, msg) {
    var input = $("#" + id);
    var errEl = $("#" + id + "-error");
    if (input) input.classList.add("invalid");
    if (errEl) { errEl.textContent = msg; errEl.hidden = false; }
  }
  function clearFieldError(id) {
    var input = $("#" + id);
    var errEl = $("#" + id + "-error");
    if (input) input.classList.remove("invalid");
    if (errEl) { errEl.hidden = true; errEl.textContent = ""; }
  }

  function validateCompanyForm() {
    var ok = true;
    clearFieldError("cf-name"); clearFieldError("cf-email");
    var name = $("#cf-name").value.trim();
    if (!name) { setFieldError("cf-name", "Company name is required."); ok = false; }
    var email = $("#cf-email").value.trim();
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFieldError("cf-email", "Enter a valid email address or leave it blank.");
      ok = false;
    }
    return ok;
  }

  function submitCompanyForm(ev) {
    ev.preventDefault();
    clearBanner();
    if (!validateCompanyForm()) return;

    var payload = {
      name: $("#cf-name").value.trim(),
      industry: $("#cf-industry").value.trim() || null,
      size: $("#cf-size").value || null,
      country: $("#cf-country").value.trim() || null,
      contact_email: $("#cf-email").value.trim() || null,
    };
    var method = state.profile ? "PUT" : "POST";
    var btn = $("#btn-save-company");
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>Saving…';

    apiFetch("/api/company", {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (p) {
        state.profile = p;
        applyProfileToHeader();
        updateOnboardingGate();
        var note = $("#company-saved-note");
        note.hidden = false; note.textContent = "Company profile saved.";
        $("#company-heading").textContent = "Edit company profile";
        $("#btn-company-to-assess").hidden = false;
      })
      .catch(function (err) {
        if (err.status === 422) showBanner("Please correct the highlighted fields.", "error");
        else showBanner(err.message, "error");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = state.profile ? "Save changes" : "Save profile";
      });
  }

  function goToAssessmentOrOnboarding() {
    // Direct new users to Company Profile before their first assessment.
    if (!state.profile) { renderCompanyView(); showView("company"); return; }
    updateOnboardingGate();
    showView("assess");
  }

  function updateOnboardingGate() {
    // New Assessment requires a profile first. Show a gate + disable controls
    // until a profile exists. Historical assessments remain fully accessible.
    var gate = $("#onboard-gate");
    var hasProfile = !!state.profile;
    if (!gate) return;
    if (hasProfile) {
      gate.hidden = true;
    } else {
      gate.hidden = false;
      gate.innerHTML = "";
      gate.appendChild(el("span", null,
        "Set up your company profile before running an assessment."));
      var go = el("button", "btn btn-ghost retry", "Go to Company Profile");
      go.addEventListener("click", function () { renderCompanyView(); showView("company"); });
      gate.appendChild(go);
    }
    var loadBtn = $("#btn-load");
    var demoPrefill = $("#btn-demo-prefill");
    if (loadBtn) loadBtn.disabled = !hasProfile;
    if (demoPrefill) demoPrefill.disabled = !hasProfile;
  }

  // ---- Confirm modal ------------------------------------------------------

  var confirmCb = null;
  function openConfirm(title, text, cb) {
    $("#confirm-title").textContent = title;
    $("#confirm-text").textContent = text;
    confirmCb = cb;
    $("#confirm-modal").hidden = false;
  }
  function closeConfirm() { $("#confirm-modal").hidden = true; confirmCb = null; }

  // ---- Auth gate & company switcher --------------------------------------

  function buildAuthOverlay() {
    if ($("#auth-overlay")) return;
    var ov = el("div", "auth-overlay");
    ov.id = "auth-overlay";
    ov.innerHTML =
      '<div class="auth-card">' +
      '  <div class="auth-brand">ComplyPK</div>' +
      '  <div class="auth-sub">Security &amp; compliance readiness platform</div>' +
      '  <div class="auth-tabs"><button id="tab-login" class="auth-tab active">Sign in</button>' +
      '    <button id="tab-register" class="auth-tab">Create account</button></div>' +
      '  <div id="auth-error" class="auth-error" hidden></div>' +
      '  <form id="auth-form">' +
      '    <label>Email<input id="auth-email" type="email" autocomplete="username" /></label>' +
      '    <label>Password<input id="auth-password" type="password" autocomplete="current-password" /></label>' +
      '    <button id="auth-submit" class="btn" type="submit">Sign in</button>' +
      '  </form>' +
      '</div>';
    document.body.appendChild(ov);

    var mode = "login";
    function setMode(m) {
      mode = m;
      $("#tab-login").classList.toggle("active", m === "login");
      $("#tab-register").classList.toggle("active", m === "register");
      $("#auth-submit").textContent = m === "login" ? "Sign in" : "Create account";
      authError("");
    }
    $("#tab-login").addEventListener("click", function () { setMode("login"); });
    $("#tab-register").addEventListener("click", function () { setMode("register"); });
    $("#auth-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = $("#auth-email").value.trim();
      var pw = $("#auth-password").value;
      if (!email || !pw) { authError("Email and password are required."); return; }
      if (mode === "register") {
        apiFetch("/api/auth/register", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email, password: pw }),
        }).then(function () { return doLogin(email, pw); })
          .catch(function (e) { authError(e.message); });
      } else {
        doLogin(email, pw).catch(function (e) { authError(e.message); });
      }
    });
  }

  function authError(msg) {
    var e = $("#auth-error");
    if (!e) return;
    if (!msg) { e.hidden = true; e.textContent = ""; return; }
    e.hidden = false; e.textContent = msg;
  }

  function doLogin(email, pw) {
    return apiFetch("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, password: pw }),
    }).then(function (me) {
      applySession(me);
      hideAuthOverlay();
      return afterAuth();
    });
  }

  function applySession(me) {
    auth.user = { id: me.user_id, email: me.email };
    auth.csrf = me.csrf_token;
    auth.memberships = me.memberships || [];
    if (auth.memberships.length && auth.activeCompanyId == null) {
      auth.activeCompanyId = auth.memberships[0].company_id;
    }
  }

  function hideAuthOverlay() { var o = $("#auth-overlay"); if (o) o.remove(); }

  function clearCompanyUiState() {
    state.domains = {}; state.questions = []; state.answers = {};
    state.lastResult = null; state.profile = null;
    var d = $("#domains"); if (d) d.innerHTML = "";
    var f = $("#questionnaire-form"); if (f) f.hidden = true;
  }

  function renderCompanySwitcher() {
    var host = $("#company-switcher");
    if (!host) return;
    host.innerHTML = "";
    if (auth.memberships.length <= 1) return;  // only for multi-company users
    var sel = document.createElement("select");
    sel.id = "company-select";
    auth.memberships.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = String(m.company_id);
      opt.textContent = m.company_name + " (" + m.role + ")";
      if (m.company_id === auth.activeCompanyId) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", function () {
      auth.activeCompanyId = parseInt(sel.value, 10);
      clearCompanyUiState();            // clear stale company data
      loadProfile().then(function () {  // reload for the new active company
        updateOnboardingGate();
        renderOverview();
        showView("overview");
      });
    });
    host.appendChild(sel);
  }

  function renderUserChip() {
    var host = $("#user-chip");
    if (!host) return;
    host.innerHTML = "";
    if (!auth.user) return;
    host.appendChild(el("span", "user-email", auth.user.email));
    var out = el("button", "btn btn-ghost", "Sign out");
    out.addEventListener("click", logout);
    host.appendChild(out);
  }

  function logout() {
    apiFetch("/api/auth/logout", { method: "POST" }).finally(function () {
      auth = { user: null, csrf: null, memberships: [], activeCompanyId: null };
      clearCompanyUiState();
      showAuth();
    });
  }

  function showAuth() {
    buildAuthOverlay();
  }

  function ensureCompanyThen(cb) {
    // A logged-in user with no company must create/join one first.
    if (!auth.memberships.length) {
      promptCreateCompany().then(cb);
    } else {
      cb();
    }
  }

  function promptCreateCompany() {
    var name = window.prompt("Create your company to get started.\nEnter a company name:");
    if (!name || !name.trim()) return Promise.reject(new ApiError(0, "A company is required."));
    return apiFetch("/api/companies", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    }).then(function (m) {
      auth.memberships.push(m);
      auth.activeCompanyId = m.company_id;
    });
  }

  function afterAuth() {
    renderUserChip();
    renderCompanySwitcher();
    return ensureCompanyThen(function () {
      renderCompanySwitcher();
      checkHealth();
      loadProfile().then(function () {
        updateOnboardingGate();
        renderOverview();
        showView("overview");
      });
    });
  }

  // ---- Init ---------------------------------------------------------------

  function init() {
    $("#footer-disclaimer").textContent = DISCLAIMER;

    document.querySelectorAll(".side-link").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var v = btn.dataset.view;
        if (v === "overview") renderOverview();
        if (v === "company") renderCompanyView();
        if (v === "assess") updateOnboardingGate();
        if (v === "history") loadHistory();
        if (v === "remediation") renderRemediationCenter();
        if (v === "reports") loadReports();
        showView(v);
      });
    });
    document.querySelectorAll(".link-back").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = b.dataset.view;
        if (v === "history") loadHistory();
        showView(v);
      });
    });

    $("#hamburger").addEventListener("click", function () { $("#sidebar").classList.toggle("open"); });

    $("#btn-load").addEventListener("click", loadQuestionnaire);
    $("#btn-demo-prefill").addEventListener("click", function () { loadDemo(); });
    $("#btn-demo-load").addEventListener("click", function () {
      loadDemo().then(function () { showView("assess"); });
    });
    $("#questionnaire-form").addEventListener("submit", submitAssessment);
    $("#btn-reset").addEventListener("click", resetAnswers);
    $("#btn-remediation").addEventListener("click", loadRemediationInline);
    $("#btn-report").addEventListener("click", function () {
      if (state.lastResult) downloadReport(state.lastResult.id);
    });
    $("#btn-history-refresh").addEventListener("click", loadHistory);

    $("#confirm-cancel").addEventListener("click", closeConfirm);
    $("#confirm-ok").addEventListener("click", function () { var cb = confirmCb; closeConfirm(); if (cb) cb(); });

    // Company profile form + continue action.
    $("#company-form").addEventListener("submit", submitCompanyForm);
    $("#btn-company-to-assess").addEventListener("click", function () {
      updateOnboardingGate();
      showView("assess");
    });
    $("#btn-claim-legacy").addEventListener("click", claimLegacy);

    checkHealth();
    // Require authentication before showing any company data.
    apiFetch("/api/auth/me")
      .then(function (me) {
        applySession(me);
        afterAuth();
      })
      .catch(function () {
        // Not authenticated (401) or backend down — show the auth gate.
        showAuth();
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
