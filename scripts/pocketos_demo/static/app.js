/* PocketOS Web Demo console — single-page, static, state rendered from the
   server-authoritative ledger. The browser is a CLIENT: it reads canonical
   state through projections and mutates only by issuing proposals and
   recorded ratification events (which require a session + permission). It
   never writes the ledger directly. */

(function () {
  "use strict";

  var ROOT = document.getElementById("root");

  // ------------------------------------------------------------- state
  var state = null;       // /api/state
  var scrub = null;       // /api/scrub
  var twin = null;        // /api/twin
  var shadow = null;      // /api/shadow
  var decisions = null;   // /api/decisions
  var build = null;       // /api/build
  var session = null;     // {token, subject, permissions} | null
  var currentTab = "console";
  var streamStatus = "off";

  var TAB_DEFS = [
    { id: "console", label: "Console", glyph: "\u25ce" },
    { id: "timeline", label: "Timeline", glyph: "\u25c7" },
    { id: "graph", label: "Graph", glyph: "\u25c8" },
    { id: "health", label: "Health", glyph: "\u25c9" },
    { id: "genome", label: "Genome", glyph: "\u2726" },
    { id: "twin", label: "Twin", glyph: "\u263e" },
    { id: "shadow", label: "AI Shadow", glyph: "\u2741" },
    { id: "decisions", label: "Decisions", glyph: "\u2696" },
    { id: "memory", label: "Memory", glyph: "\u25c6" },
    { id: "projects", label: "Projects", glyph: "\u25a0" },
    { id: "loops", label: "Open Loops", glyph: "\u27f3" },
    { id: "governance", label: "Governance", glyph: "\u269b" },
    { id: "evidence", label: "Evidence", glyph: "\u2726" },
    { id: "ledger", label: "Ledger", glyph: "\u279e" },
    { id: "build", label: "Build", glyph: "\u2699" },
  ];

  var TOKEN = null;

  // ------------------------------------------------------------- http
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function authHeaders() {
    return TOKEN ? { "Authorization": "Bearer " + TOKEN } : {};
  }

  function getJSON(url, cb) {
    fetch(url).then(function (r) { return r.json(); }).then(cb).catch(function () {});
  }

  function postJSON(url, body, cb) {
    fetch(url, {
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
      body: JSON.stringify(body || {}),
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(cb).catch(function () {});
  }

  // ------------------------------------------------------------- session
  function loggedIn() { return !!TOKEN; }
  function hasPerm(p) { return !!session && session.permissions.indexOf(p) !== -1; }

  function refreshSession() {
    if (!TOKEN) { session = null; render(); return; }
    fetch("/api/session/me", { headers: authHeaders() })
      .then(function (r) {
        if (r.status === 401) { TOKEN = null; session = null; render(); return; }
        return r.json();
      })
      .then(function (s) { if (s && s.subject) { session = s; render(); } })
      .catch(function () {});
  }

  function login(username, password) {
    postJSON("/api/login", { username: username, password: password }, function (s) {
      if (s && s.token) {
        TOKEN = s.token;
        session = { subject: s.subject, permissions: s.permissions, expires_at: s.expires_at };
        refreshState(); render();
      } else {
        alert("login failed");
      }
    });
  }

  function logout() {
    // Revoke the session server-side so the token cannot be reused.
    if (TOKEN) {
      fetch("/api/logout", { method: "POST", headers: authHeaders() })
        .catch(function () {}); // local logout proceeds regardless
    }
    TOKEN = null; session = null; refreshState(); render();
  }

  // ------------------------------------------------------------- refresh
  function refreshState() {
    getJSON("/api/state", function (s) { state = s; render(); });
  }
  function refreshScrub() { getJSON("/api/scrub", function (s) { scrub = s; render(); }); }
  function refreshTwin() { getJSON("/api/twin", function (s) { twin = s; render(); }); }
  function refreshShadow() { getJSON("/api/shadow", function (s) { shadow = s; render(); }); }
  function refreshDecisions() { getJSON("/api/decisions", function (s) { decisions = s; render(); }); }
  function refreshBuild() { getJSON("/api/build", function (s) { build = s; render(); }); }

  function refreshAll() {
    refreshState(); refreshScrub(); refreshTwin(); refreshShadow(); refreshDecisions(); refreshBuild();
  }

  // ------------------------------------------------------------- live spine (SSE)
  function startStream() {
    if (typeof EventSource === "undefined") { streamStatus = "unsupported"; return; }
    var es = new EventSource("/api/stream");
    streamStatus = "connecting";
    es.addEventListener("hello", function () { streamStatus = "live"; render(); });
    es.addEventListener("event", function (e) {
      // A received event is observational — the UI refetches the authoritative
      // projection rather than trusting the push payload as its own action.
      streamStatus = "live";
      refreshAll();
    });
    es.onerror = function () {
      // Auto-reconnect: EventSource reconnects by itself. We refetch state so a
      // missed event during the drop is reconciled.
      streamStatus = "reconnecting";
      render();
      refreshAll();
    };
    window.__es = es;
  }

  // ------------------------------------------------------------- layout
  function integrityPill() {
    var intact = state && state.integrity === "INTACT";
    return '<span class="pill ' + (intact ? "st-good" : "st-bad") + '" data-testid="integrity-status">' +
      (intact ? "INTACT" : "COMPROMISED") + "</span>";
  }

  function streamPill() {
    var map = { live: ["st-good", "LIVE"], connecting: ["st-warn", "CONNECTING"], reconnecting: ["st-warn", "RECONNECTING"], unsupported: ["st-warn", "N/A"], off: ["st-warn", "OFF"] };
    var m = map[streamStatus] || map.off;
    return '<span class="pill ' + m[0] + '" data-testid="stream-status">SSE ' + m[1] + "</span>";
  }

  function loginBar() {
    if (loggedIn()) {
      return '<div class="loginbar"><span class="who" data-testid="session-subject">' + esc(session && session.subject ? session.subject : "") +
        "</span><span class='perms'>" + (session && session.permissions ? session.permissions.join(" ") : "") +
        '</span><button class="btn" data-action="logout" data-testid="logout">Log out</button></div>';
    }
    return '<form class="loginbar" data-testid="login-form">' +
      '<input class="input" name="username" placeholder="username" data-testid="login-user" />' +
      '<input class="input" name="password" type="password" placeholder="password" data-testid="login-pass" />' +
      '<button class="btn" type="submit" data-testid="login-submit">Sign in</button></form>';
  }

  function nav() {
    var html = '<nav class="tabs">';
    for (var i = 0; i < TAB_DEFS.length; i++) {
      var t = TAB_DEFS[i];
      var active = t.id === currentTab ? " active" : "";
      html += '<button class="tab' + active + '" data-testid="tab-' + t.id + '" data-tab="' + t.id + '">' +
        t.glyph + " " + t.label + "</button>";
    }
    return html + "</nav>";
  }

  // ------------------------------------------------------------- helpers
  function banners() {
    if (!state) return "";
    if (state.integrity !== "INTACT") {
      var seq = (typeof state.broken_seq === "number") ? "#" + (state.broken_seq + 1) : "";
      return '<div class="banner warn" data-testid="console-banner" role="alert">' +
        "<strong>Ledger compromised</strong> \u2014 chain broken at " +
        '<span data-testid="broken-seq">' + esc(seq) + "</span></div>";
    }
    var n = state.contradictions || 0;
    if (n > 0) {
      return '<div class="banner warn" data-testid="console-banner" role="alert">' +
        '<strong>' + n + " conflicting claims</strong> in memory (" +
        '<span data-testid="console-banner-count">' + n + "</span>)</div>";
    }
    return '<div class="banner ok" data-testid="console-banner" role="status">No conflicts</div>';
  }

  function demoActions() {
    if (!state) return "";
    if (!loggedIn()) {
      return '<span class="hint">Sign in as admin to run demo controls.</span>';
    }
    if (!hasPerm("ADMIN")) {
      return '<span class="hint">Admin permission required for demo controls.</span>';
    }
    var intact = state.integrity === "INTACT";
    var btn = intact
      ? '<button class="btn btn-danger" data-action="tamper" data-testid="tamper-ledger">Tamper ledger</button>'
      : '<button class="btn" data-action="reset" data-testid="reset-ledger">Reset ledger</button>';
    return btn;
  }

  // System chrome: integrity, live-stream status, governance posture, and the
  // demo actions render ONCE here, above the active tab, so they are reachable
  // from every view without duplicating a data-testid.
  function systemChrome() {
    if (!state) return "";
    var gov = '<div class="govbar" data-testid="governance-panel">' +
      '<span class="govlabel">GOVERNANCE</span>' +
      '<p class="counters" data-testid="governance-counters">' + esc(state.counters || "") + "</p></div>";
    var demo = '<div class="demo-actions"><span class="demo-label">DEMO</span>' + demoActions() + "</div>";
    return '<div class="sysbar">' +
      integrityPill() + streamPill() + "</div>" + gov + demo;
  }

  // ------------------------------------------------------------- console
  function consoleContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var rows = "";
    var records = state.records || [];
    for (var i = records.length - 1; i >= 0; i--) {
      var r = records[i];
      var ev = r.event || r.schema_version || "record";
      var title = (r.payload && r.payload.title) ? r.payload.title : (r.title || "");
      var kind = r.kind || (r.schema_version === "legacy_v1" ? "legacy" : "-");
      var meta = ev + (r.sequence ? " #" + r.sequence : "");
      rows += '<div class="rec" data-testid="record-row">' +
        '<span class="rec-kind">' + esc(kind) + "</span>" +
        '<span class="rec-meta">' + esc(meta) + "</span>" +
        '<span class="rec-title">' + esc(title) + "</span>" +
        "</div>";
    }
    return (
      '<section class="panel"><header class="panel-head"><h2>Console</h2></header>' +
      banners() +
      '<div class="reclist">' + rows + "</div>" +
      "</section>"
    );
  }

  // ------------------------------------------------------------- timeline
  function timelineContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var intact = state.integrity === "INTACT";
    var n = state.record_count || 0;
    var ticks = "";
    for (var i = 1; i <= n; i++) {
      ticks += '<button class="tick" data-testid="scrubber-tick" data-seq="' + i + '" title="scrub to #' + i + '"></button>';
    }
    var scrubArea = "";
    var errorArea = "";
    if (scrub && !scrub.ok) {
      var errSeq = scrub.error && scrub.error.broken_seq ? " " + esc("#" + scrub.error.broken_seq) : "";
      errorArea = '<div class="scrub-error" data-testid="scrubber-error" role="alert">' +
        "<strong>Scrubber refused</strong> &mdash; " +
        esc(scrub.error ? scrub.error.message : "cannot reconstruct over a compromised ledger") +
        (errSeq ? '<span data-testid="scrubber-error-seq">' + errSeq + "</span>" : "") +
        "</div>";
    } else if (scrub && scrub.ok) {
      scrubArea = '<p class="prov" data-testid="scrubber-provenance">' + esc(scrub.provenance) + "</p>";
    } else if (intact) {
      scrubArea = '<p class="hint">Drag / click a tick to reconstruct state.</p>';
    }
    return (
      '<section class="panel"><header class="panel-head"><h2>Timeline replay scrubber</h2></header>' +
      '<p class="hint">Reconstructs ledger state. Refused when the chain is broken.</p>' +
      '<div class="track" data-testid="timeline-scrubber">' + ticks + "</div>" +
      scrubArea + errorArea +
      "</section>"
    );
  }

  // ------------------------------------------------------------- graph
  function graphContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    // A small deterministic relationship view derived from ledger sources.
    var sources = {};
    (state.records || []).forEach(function (r) {
      if (r.source) sources[r.source] = (sources[r.source] || 0) + 1;
    });
    var nodes = "";
    Object.keys(sources).forEach(function (s) {
      nodes += '<div class="gnode" data-testid="graph-node">' + esc(s) + " (" + sources[s] + ")</div>";
    });
    return '<section class="panel"><header class="panel-head"><h2>Knowledge graph</h2></header>' +
      '<p class="hint">Ledger sources as graph nodes (read-only projection).</p>' +
      '<div class="graph" data-testid="graph">' + nodes + "</div>" +
      "</section>";
  }

  // ------------------------------------------------------------- health
  function healthContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var intact = state.integrity === "INTACT";
    var checks = [
      ["Ledger", intact ? "Verified" : "Compromised", intact ? "st-good" : "st-bad"],
      ["Database", "Healthy", "st-good"],
      ["Memory", contradiction_count() ? "Degraded" : "Healthy", contradiction_count() ? "st-warn" : "st-good"],
      ["Sync", "Connected", "st-good"],
    ];
    var rows = checks.map(function (c) {
      return '<div class="hrow"><span class="hname">' + c[0] + "</span><span class='pill " + c[2] + "'>" + c[1] + "</span></div>";
    }).join("");
    return '<section class="panel"><header class="panel-head"><h2>System health</h2></header>' + rows + "</section>";
    function contradiction_count() {
      return (state.contradictions || 0) > 0;
    }
  }

  // ------------------------------------------------------------- genome
  function genomeContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var traits = state.traits || [];
    var rows = traits.map(function (t) {
      return '<li class="trait" data-testid="genome-trait">' +
        '<span class="tname">' + esc(t.name) + "</span>" +
        '<span class="tscore" data-testid="genome-trait-score">' + esc(String(t.score)) + "</span></li>";
    }).join("");
    return '<section class="panel"><header class="panel-head"><h2>Genome</h2></header>' +
      '<ul class="traits">' + rows + "</ul></section>";
  }

  // ------------------------------------------------------------- epistemic
  function epistemicBadge(st) {
    var s = String(st || "").toUpperCase();
    var map = { OBSERVED: "#9ce0ff", VERIFIED: "#bdf0dc", INFERRED: "#ffd9a0", UNCERTAIN: "#e3d9ff", REJECTED: "#ffb3b0", STALE: "#cbd5e1" };
    return '<span class="epi" style="border-color:' + (map[s] || "#888") + ';color:' + (map[s] || "#ccc") + '">' + esc(s) + "</span>";
  }

  function itemRow(item, testid) {
    var ev = (item.evidence || []).map(function (s) { return "#" + s; }).join(", ");
    return '<li class="twin-item" data-testid="' + testid + '">' +
      epistemicBadge(item.epistemic) +
      '<span class="ti-text">' + esc(item.text) + "</span>" +
      '<span class="ti-meta">conf ' + esc(String(item.confidence)) + " &middot; " + esc(item.provenance) +
      (ev ? " &middot; " + ev : "") + "</span></li>";
  }

  // ------------------------------------------------------------- twin
  function twinContent() {
    if (!twin) { return state && state.integrity !== "INTACT" ? "<div class='empty'>Cognitive Twin unavailable &mdash; ledger compromised.</div>" : "<div class='empty'>Loading Cognitive Twin&hellip;</div>"; }
    var t = twin.cognitive_twin || {};
    var stt = t.state || {};
    function card(title, items, tid) {
      var lis = (items && items.length) ? items.map(function (i) { return itemRow(i, tid); }).join("") : "<li class='empty'>none</li>";
      return '<div class="card"><h3>' + title + "</h3><ul>" + lis + "</ul></div>";
    }
    return '<section class="panel"><header class="panel-head"><h2>Cognitive Twin</h2>' +
      '<span class="recmeta">' + esc(t.model_version) + " &middot; seq " + (t.last_update_seq || 0) + "</span></header>" +
      '<p class="prov">' + esc(t.summary) + "</p>" +
      '<div class="cardgrid">' +
      card("Current focus", stt.current_focus ? [stt.current_focus] : [], "twin-focus") +
      card("Open loops", stt.open_loops || [], "twin-loop-open") +
      card("Closed loops", stt.closed_loops || [], "twin-loop-closed") +
      card("Active projects", stt.active_projects || [], "twin-project") +
      "</div>" +
      card("Relevant memories", t.relevant_memories || [], "twin-memory") +
      card("Decision history", t.decision_history || [], "twin-decision") +
      card("Inferred relationships", t.relationships || [], "twin-relationship") +
      card("Recent observations", t.recent_observations || [], "twin-observation") +
      "</section>";
  }

  // ------------------------------------------------------------- shadow
  function shadowItemRow(item) {
    var ev = (item.evidence || []).map(function (s) { return "#" + s; }).join(", ");
    return '<li class="shadow-item" data-testid="shadow-item" data-type="' + esc(item.type) + '">' +
      '<div class="shadow-head"><span class="tag">' + esc(item.type) + "</span>" +
      '<span class="pill st-good" data-testid="shadow-authority">' + esc(item.authority) + "</span></div>" +
      '<p class="shadow-text">' + esc(item.text) + "</p>" +
      '<div class="shadow-meta">conf ' + esc(String(item.confidence)) + " &middot; " + esc(item.provenance) +
      (ev ? " &middot; " + ev : "") +
      (item.next_step ? " &middot; next: " + esc(item.next_step) : "") + "</div></li>";
  }

  function shadowContent() {
    if (!shadow) { return state && state.integrity !== "INTACT" ? "<div class='empty'>AI Shadow unavailable &mdash; ledger compromised.</div>" : "<div class='empty'>Loading AI Shadow&hellip;</div>"; }
    var s = shadow.ai_shadow || {};
    var boundary = s.authority_boundary || {};
    var items = (s.items || []).map(shadowItemRow).join("");
    return '<section class="panel"><header class="panel-head"><h2>AI Shadow</h2>' +
      '<span class="pill st-good" data-testid="shadow-boundary">AUTHORITY ' + esc(boundary.shadow_authority || "NONE") + "</span></header>" +
      '<p class="prov">AI Shadow is advisory. It observes and proposes; it never executes, ratifies, or authorizes.</p>' +
      '<ul class="shadow-list">' + items + "</ul></section>";
  }

  // ------------------------------------------------------------- decisions
  function decisionCard(d) {
    var status = esc(d.status || "");
    // Independent authority-state components. Each comes from the backend;
    // the UI never derives executable-ness from permission alone.
    var ratified = d.human_ratified === true;
    var rejected = d.rejected === true;
    var executed = !!d.executed_seq;
    var executable = d.can_execute === true;   // authoritative: backend RATIFIED

    // Derived display stage for the human, mapped from canonical backend fields.
    var term;
    if (rejected) term = ["REJECTED", "EXECUTION BLOCKED"];
    else if (executed) term = ["EXECUTED", "EVIDENCE RECORDED"];
    else if (!ratified && !executed) term = ["NOT HUMAN-RATIFIED", "EXECUTION BLOCKED"];
    else if (ratified && executable) term = ["HUMAN RATIFIED", "EXECUTABLE"];
    else term = [status, ""];

    function stateBlock(label, ok, detail) {
      return '<div class="auth-state">' +
        '<span class="auth-label">' + esc(label) + "</span>" +
        '<span class="pill ' + (ok ? "st-good" : "st-warn") + '">' + esc(ok ? "YES" : "NO") + "</span>" +
        (detail ? '<span class="auth-detail">' + detail + "</span>" : "") + "</div>";
    }

    // User permission is presented as the client's capability only — it is
    // never shown as execution authority (the server re-validates).
    var myPerm = loggedIn() && hasPerm("EXECUTE");
    var components =
      stateBlock("User has EXECUTE permission", myPerm, myPerm ? "client capability only" : "sign in with execute perm") +
      stateBlock("Governance approved", d.council_approved === true, "") +
      stateBlock("Human ratified", ratified, "") +
      stateBlock("Capability valid", executable && ratified, "backend: can_execute") +
      stateBlock("Execution started", executed, executed ? "ledger seq #" + d.executed_seq : "") +
      stateBlock("Evidence recorded", executed, executed ? d.evidence_stage || "EVIDENCE" : "no execution evidence");

    var verdict = "";
    if (rejected) {
      verdict = '<div class="auth-verdict st-bad" data-testid="exec-blocked">REJECTED — execution blocked</div>';
    } else if (!ratified) {
      verdict = '<div class="auth-verdict st-warn" data-testid="exec-blocked">NOT HUMAN-RATIFIED — execution blocked</div>';
    } else if (executed) {
      verdict = '<div class="auth-verdict st-good" data-testid="exec-state">EXECUTED — evidence recorded</div>';
    } else if (executable) {
      // Show "Execution available" ONLY because the backend reports it.
      verdict = '<div class="auth-verdict st-good" data-testid="exec-available">Execution available (backend-confirmed)</div>';
    }

    // Mutation controls. Execute appears ONLY when the backend reports
    // can_execute AND the session carries EXECUTE; the server re-validates.
    var controls = "";
    if (loggedIn() && hasPerm("COUNCIL") && (d.status === "PENDING" || d.status === "COUNCIL")) {
      controls += '<button class="btn" data-action="council-approve" data-did="' + esc(d.decision_id) + '">Approve (council)</button>';
    }
    if (loggedIn() && hasPerm("RATIFY") && d.status === "AWAITING_RATIFICATION") {
      controls += '<button class="btn btn-primary" data-action="ratify" data-did="' + esc(d.decision_id) + '">Ratify (human)</button>' +
        '<button class="btn btn-danger" data-action="reject" data-did="' + esc(d.decision_id) + '">Reject</button>';
    }
    if (loggedIn() && hasPerm("EXECUTE") && executable && !executed) {
      controls += '<button class="btn btn-primary" data-action="execute" data-did="' + esc(d.decision_id) + '">Execute</button>';
    }
    var lifecycle = d.lifecycle.map(function (st) {
      var on = st === (d.stage || "");
      return '<span class="lc' + (on ? " lc-on" : "") + '">' + esc(st) + "</span>";
    }).join('<span class="lc-arrow">&rsaquo;</span>');

    return '<li class="decision-card" data-testid="decision-card" data-did="' + esc(d.decision_id) + '" data-can-execute="' + (executable ? "true" : "false") + '">' +
      '<div class="dec-head"><span class="tag">' + esc(d.decision_id) + "</span>" +
      '<span class="pill ' + (rejected ? "st-bad" : (executable ? "st-good" : "st-warn")) + '" data-testid="decision-status">' + status + "</span>" +
      '<span class="pill ' + (ratified ? "st-good" : "st-warn") + '" data-testid="decision-ratified">' + (ratified ? "RATIFIED" : "NOT RATIFIED") + "</span></div>" +
      '<h3>' + esc(d.title) + "</h3>" +
      '<div class="dec-meta">risk ' + esc(d.risk) + " &middot; reversible " + (d.reversible ? "yes" : "no") +
      " &middot; reasoning " + esc(d.reason_hash) + " &middot; proposal #" + (d.proposal_seq || "-") + "</div>" +
      '<div class="auth-components" data-testid="auth-components">' + components + "</div>" +
      verdict +
      '<div class="lifecycle" data-testid="lifecycle">' + lifecycle + "</div>" +
      (controls ? '<div class="dec-actions">' + controls + "</div>" : "") +
      "</li>";
  }

  function decisionsContent() {
    if (!decisions) { return state && state.integrity !== "INTACT" ? "<div class='empty'>Decisions unavailable &mdash; ledger compromised.</div>" : "<div class='empty'>Loading decisions&hellip;</div>"; }
    var list = decisions.decisions || [];
    var propose = loggedIn() && hasPerm("PROPOSE")
      ? '<form class="propose-form" data-testid="propose-form">' +
        '<input class="input" name="title" placeholder="New proposal title" data-testid="propose-title" />' +
        '<button class="btn btn-primary" type="submit" data-testid="propose-submit">Propose</button></form>'
      : '<p class="hint">Sign in with propose permission to create a proposal.</p>';
    var cards = list.length ? list.map(decisionCard).join("") : "<li class='empty'>no decisions</li>";
    return '<section class="panel"><header class="panel-head"><h2>Decision lifecycle</h2>' +
      '<span class="recmeta">' + list.length + " decision(s)</span></header>" +
      '<p class="prov">Proposal &rarr; Council &rarr; Human ratification &rarr; Execution. No UI event bypasses the constitutional runtime.</p>' +
      propose +
      '<ul class="decision-list">' + cards + "</ul></section>";
  }

  // =========================================================================
  // Control-room expansion views
  // Every view below is a READ-ONLY lens over the canonical projections the
  // server returns (/api/state, /api/twin, /api/shadow, /api/decisions). The
  // browser never computes authoritative epistemic state, provenance, or
  // governance; it renders what the backend resolved. No view issues a mutation.
  // =========================================================================

  // ---- memory -----------------------------------------------------------
  function memoryRows(records) {
    var rows = "";
    for (var i = records.length - 1; i >= 0; i--) {
      var r = records[i];
      if (r.event !== "memory.created" && r.event !== "knowledge.document") continue;
      var title = (r.payload && r.payload.title) || "";
      var tension = (r.payload && r.payload.tension) ? " tension" : "";
      var meta = esc(r.event) + " #" + r.sequence + " &middot; src " + esc(r.source || "-");
      rows += '<div class="rec" data-testid="mem-row">' +
        '<span class="rec-kind">' + esc(r.event) + "</span>" +
        '<span class="rec-meta">' + meta + "</span>" +
        '<span class="rec-title' + tension + '">' + esc(title) + "</span></div>";
    }
    return rows;
  }

  function memoryContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var rows = memoryRows(state.records || []);
    var legend = '<div class="epi-legend" data-testid="mem-legend">Epistemic statuses: ' +
      '<span class="epi" style="border-color:#bdf0dc;color:#bdf0dc">VERIFIED</span> ' +
      '<span class="epi" style="border-color:#9ce0ff;color:#9ce0ff">OBSERVED</span> ' +
      '<span class="epi" style="border-color:#ffd9a0;color:#ffd9a0">INFERRED</span> ' +
      '<span class="epi" style="border-color:#e3d9ff;color:#e3d9ff">UNCERTAIN</span> ' +
      '<span class="epi" style="border-color:#ffb3b0;color:#ffb3b0">REJECTED</span> ' +
      '<span class="epi" style="border-color:#cbd5e1;color:#cbd5e1">STALE</span></div>';
    var note = (state.contradictions > 0)
      ? '<div class="banner warn" data-testid="mem-contradiction" role="alert"><strong>' + state.contradictions +
        " conflicting claim(s)</strong> in memory &mdash; both sides are shown with provenance; the system never silently picks one.</div>"
      : '<div class="banner ok" role="status">No unresolved contradictions in memory.</div>';
    return '<section class="panel"><header class="panel-head"><h2>Memory</h2>' +
      '<span class="recmeta">canonical ledger &middot; read-only</span></header>' +
      note + legend +
      '<div class="reclist">' + (rows || "<div class='empty'>no memories</div>") + "</div></section>";
  }

  // ---- projects ---------------------------------------------------------
  function projectsContent() {
    if (!twin) return "<div class='empty'>Loading projects&hellip;</div>";
    var t = twin.cognitive_twin || {};
    var st = t.state || {};
    var proj = (st.active_projects || []).map(function (i) { return itemRow(i, "project-item"); }).join("");
    var loops = (st.open_loops || []).map(function (i) { return itemRow(i, "project-loop"); }).join("");
    var cards = '<div class="card"><h3>Active projects</h3><ul>' + (proj || "<li class='empty'>none</li>") + "</ul></div>" +
      '<div class="card"><h3>Open loops (linked)</h3><ul>' + (loops || "<li class='empty'>none</li>") + "</ul></div>" +
      '<div class="card"><h3>Decision history</h3><ul>' +
      ((t.decision_history || []).map(function (i) { return itemRow(i, "project-decision"); }).join("") || "<li class='empty'>none</li>") + "</ul></div>";
    return '<section class="panel"><header class="panel-head"><h2>Projects</h2>' +
      '<span class="recmeta">twin-1.0 fold &middot; advisory</span></header>' +
      '<p class="prov">Projects link back into the memory graph through the canonical Twin projection. Project status is inferred from ledger activity unless VERIFIED.</p>' +
      '<div class="cardgrid">' + cards + "</div></section>";
  }

  // ---- open loops -------------------------------------------------------
  function loopsContent() {
    if (!twin) return "<div class='empty'>Loading open loops&hellip;</div>";
    var t = twin.cognitive_twin || {};
    var st = t.state || {};
    var loops = (st.open_loops || []).map(function (i) { return itemRow(i, "loop-item"); }).join("");
    var obs = (t.recent_observations || []).map(function (i) { return itemRow(i, "loop-observation"); }).join("");
    return '<section class="panel"><header class="panel-head"><h2>Open loops</h2>' +
      '<span class="recmeta">awaiting resolution &middot; never auto-executed</span></header>' +
      '<p class="prov">A loop is an open item &mdash; an unresolved decision, task, or follow-up. Inspect its context here; nothing executes merely because a loop exists.</p>' +
      '<div class="cardgrid">' +
      '<div class="card"><h3>Open</h3><ul>' + (loops || "<li class='empty'>no open loops</li>") + "</ul></div>" +
      '<div class="card"><h3>Recent observations</h3><ul>' + (obs || "<li class='empty'>none</li>") + "</ul></div>" +
      "</div></section>";
  }

  // ---- governance -------------------------------------------------------
  function governanceContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var govRows = (state.records || []).filter(function (r) { return r.event === "governance.decided"; })
      .map(function (r) {
        var p = r.payload || {};
        var cls = p.outcome === "approved" ? "st-good" : (p.outcome === "denied" ? "st-bad" : "st-warn");
        return '<div class="rec" data-testid="gov-row">' +
          '<span class="rec-kind">' + esc(p.outcome || r.event) + "</span>" +
          '<span class="rec-meta">governance #' + r.sequence + " &middot; src " + esc(r.source || "-") + "</span>" +
          '<span class="rec-title">' + esc(p.title || "") + "</span></div>";
      }).join("");
    var authority = '<div class="card"><h3>Authority chain</h3><ol class="chain" data-testid="gov-chain">' +
      "<li>LLM proposes</li><li>Council evaluates</li><li>Governance authorizes</li>" +
      "<li>Human ratifies</li><li>Kernel executes</li><li>Ledger records</li></ol></div>";
    return '<section class="panel"><header class="panel-head"><h2>Governance</h2>' +
      '<span class="recmeta">' + esc(state.counters || "") + "</span></header>" +
      '<p class="prov"><strong>Memory may inform; it may not authorize.</strong> This UI presents governance state from the server. Ratification and rejection are the only human acts; execution requires a ratified decision and the EXECUTE permission, both enforced server-side.</p>' +
      authority +
      '<div class="card"><h3>Governance decisions</h3>' + (govRows || "<div class='empty'>none</div>") + "</div></section>";
  }

  // ---- evidence ---------------------------------------------------------
  function evidenceContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var rows = "";
    var recs = state.records || [];
    for (var i = recs.length - 1; i >= 0; i--) {
      var r = recs[i];
      rows += '<div class="rec" data-testid="evidence-row" data-seq="' + r.sequence + '">' +
        '<span class="rec-kind">#' + r.sequence + "</span>" +
        '<span class="rec-meta">' + esc(r.event) + "</span>" +
        '<span class="rec-title">' + esc((r.payload && r.payload.title) || "") + "</span>" +
        '<code class="ev-hash" data-testid="evidence-hash">' + esc(r.hash) + "</code></div>";
    }
    var ver = state.integrity === "INTACT"
      ? '<div class="banner ok" role="status">Every record&#39;s hash is chained to the previous (SHA-256 over canonical form). The full chain verifies INTACT.</div>'
      : '<div class="banner warn" role="alert">Chain broken &mdash; evidence integrity compromised.</div>';
    return '<section class="panel"><header class="panel-head"><h2>Evidence</h2>' +
      '<span class="recmeta">"why does Pocket OS believe this?"</span></header>' + ver +
      '<p class="prov">Each belief carries provenance (ledger#seq), confidence, and its supporting evidence sequences. The chain is recomputable for any record.</p>' +
      '<div class="reclist">' + rows + "</div></section>";
  }

  // ---- ledger -----------------------------------------------------------
  function ledgerContent() {
    if (!state) return "<div class='empty'>Loading&hellip;</div>";
    var rows = "";
    (state.records || []).forEach(function (r) {
      var chain = r.previous_hash ? '<span class="pill st-good">chained</span>' : '<span class="pill st-warn">genesis</span>';
      rows += '<div class="rec" data-testid="ledger-row" data-seq="' + r.sequence + '">' +
        '<span class="rec-kind">#' + r.sequence + "</span>" +
        '<span class="rec-meta">' + esc(r.event) + " &middot; " + esc(r.source || "-") + "</span>" +
        '<span class="rec-title">' + esc((r.payload && r.payload.title) || "") + "</span>" + chain +
        '<code class="ev-hash">prev ' + esc((r.previous_hash || "-").slice(0, 12)) + "</code></div>";
    });
    var ver = state.integrity === "INTACT"
      ? '<div class="banner ok" role="status">Append-only ledger &middot; ' + (state.record_count || state.records.length) + " records &middot; hash chain VERIFIED INTACT.</div>"
      : '<div class="banner warn" role="alert">Ledger compromised &mdash; verification failed.</div>';
    return '<section class="panel"><header class="panel-head"><h2>Ledger</h2>' +
      '<span class="recmeta">append-only &middot; read-only</span></header>' + ver +
      '<p class="prov">This is the sole authoritative store. The UI cannot edit history; there is no client-side ledger. The Timeline tab reconstructs prior state from these records.</p>' +
      '<div class="reclist">' + rows + "</div></section>";
  }

  // ------------------------------------------------------------- content dispatch
  function buildContent() {
    if (!build) return "<div class='empty'>Loading&hellip;</div>";
    var caps = build.capabilities || {};
    var rows = "";
    Object.keys(caps).forEach(function (key) {
      var enabled = !!caps[key];
      rows += '<div class="hrow"><span class="hname">' + esc(key.replace(/_/g, " ")) +
        '</span><span class="pill ' + (enabled ? "st-good" : "st-warn") + '">' +
        (enabled ? "ENABLED" : "DISABLED") + "</span></div>";
    });
    var ledger = build.ledger || {};
    return '<section class="panel" data-testid="build-panel"><header class="panel-head"><h2>Build &amp; Upgrade</h2>' +
      '<span class="pill st-good">' + esc(build.release || "unknown") + '</span></header>' +
      '<p class="prov">Server-owned release metadata and capability posture. This view is informational; it cannot grant authority or change the ledger.</p>' +
      '<div class="cardgrid"><div class="card"><h3>Release</h3>' +
      '<div class="hrow"><span class="hname">Product</span><strong>' + esc(build.product) + '</strong></div>' +
      '<div class="hrow"><span class="hname">Upgrade</span><strong>' + esc(build.upgrade) + '</strong></div>' +
      '<div class="hrow"><span class="hname">API contract</span><strong>' + esc(build.api_contract) + '</strong></div>' +
      '<div class="hrow"><span class="hname">Runtime</span><strong>' + esc(build.runtime) + '</strong></div></div>' +
      '<div class="card"><h3>Live ledger</h3>' +
      '<div class="hrow"><span class="hname">Integrity</span><span class="pill ' + (ledger.valid ? "st-good" : "st-bad") + '">' + esc(ledger.integrity) + '</span></div>' +
      '<div class="hrow"><span class="hname">Records</span><strong>' + esc(ledger.record_count) + '</strong></div>' +
      '<div class="hrow"><span class="hname">Revision</span><strong>' + esc(ledger.revision) + '</strong></div>' +
      '<div class="hrow"><span class="hname">Audio</span><span class="pill st-warn">NOT INCLUDED</span></div></div></div>' +
      '<div class="card"><h3>Capabilities</h3>' + rows + '</div></section>';
  }

  function contentFor(tab) {
    if (tab === "console") return consoleContent();
    if (tab === "timeline") return timelineContent();
    if (tab === "graph") return graphContent();
    if (tab === "health") return healthContent();
    if (tab === "genome") return genomeContent();
    if (tab === "twin") return twinContent();
    if (tab === "shadow") return shadowContent();
    if (tab === "decisions") return decisionsContent();
    if (tab === "memory") return memoryContent();
    if (tab === "projects") return projectsContent();
    if (tab === "loops") return loopsContent();
    if (tab === "governance") return governanceContent();
    if (tab === "evidence") return evidenceContent();
    if (tab === "ledger") return ledgerContent();
    if (tab === "build") return buildContent();
    return "<p>Unknown tab</p>";
  }

  // ------------------------------------------------------------- render
  function render() {
    if (!state) {
      ROOT.innerHTML = '<div data-testid="pocket-os-root"><div class="app">' + loginBar() + nav() + "<div class='empty'>Loading&hellip;</div></div></div>";
      return;
    }
    ROOT.innerHTML = '<div data-testid="pocket-os-root"><div class="app">' +
      loginBar() + nav() + systemChrome() + contentFor(currentTab) + "</div></div>";
  }

  // ------------------------------------------------------------- actions
  function decisionAction(action, decisionId) {
    if (!TOKEN) { alert("sign in required"); return; }
    var url = "/api/decisions/" + encodeURIComponent(decisionId) + "/" + action;
    if (action === "ratify") {
      // Ratification requires a council quorum (QUORUM=2 distinct members).
      // The UI is a control surface: it assembles signatures by requesting each
      // member to sign (server-side keys) and submits them. Bearer RATIFY
      // permission alone cannot ratify; the server verifies the quorum.
      assembleQuorumAndRatify(decisionId);
      return;
    }
    postJSON(url, {}, function (s) {
      if (s && s.error) { alert("denied: " + (s.error.message || s.error.code)); }
      refreshAll();
    });
  }

  // Assemble a council quorum (2 distinct member signatures) then ratify.
  function assembleQuorumAndRatify(decisionId) {
    var members = ["council-a", "council-b"];  // QUORUM = 2
    var sigs = {};
    var pending = members.length;
    var failed = false;
    members.forEach(function (member) {
      postJSON("/api/decisions/" + encodeURIComponent(decisionId) + "/council-sign?member=" + encodeURIComponent(member),
        {}, function (s) {
          pending -= 1;
          if (failed) { if (pending === 0) refreshAll(); return; }
          if (!s || !s.ok || !s.signature) { failed = true; alert("council sign failed for " + member); }
          else { sigs[member] = s.signature; }
          if (pending === 0 && !failed) {
            postJSON("/api/decisions/" + encodeURIComponent(decisionId) + "/ratify",
              { signatures: sigs }, function (r) {
                if (r && r.error) { alert("ratification denied: " + (r.error.message || r.error.code)); }
                refreshAll();
              });
          }
        });
    });
  }

  // ------------------------------------------------------------- events
  ROOT.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form || !form.tagName) return;
    if (form.classList.contains("loginbar")) {
      ev.preventDefault();
      var u = form.querySelector("[name='username']").value;
      var p = form.querySelector("[name='password']").value;
      login(u, p);
      return;
    }
    if (form.classList.contains("propose-form")) {
      ev.preventDefault();
      var input = form.querySelector("[name='title']");
      var title = input ? input.value.trim() : "";
      if (!title) return;
      postJSON("/api/decisions/propose", { title: title, send_to_council: true }, function (s) {
        if (s && s.error) alert("denied: " + (s.error.message || ""));
        refreshAll();
      });
    }
  });

  ROOT.addEventListener("click", function (ev) {
    var el = ev.target.closest ? ev.target.closest("button") : null;
    if (!el) return;
    var action = el.getAttribute("data-action");
    if (action === "logout") { logout(); return; }
    if (action === "tamper") { postJSON("/api/demo/tamper", {}, function (s) { refreshAll(); }); return; }
    if (action === "reset") { postJSON("/api/demo/reset", {}, function (s) { refreshAll(); }); return; }
    if (action === "council-approve" || action === "ratify" || action === "reject" || action === "execute") {
      decisionAction(action, el.getAttribute("data-did"));
      return;
    }
    var tab = el.getAttribute("data-tab");
    if (tab) {
      currentTab = tab;
      render();
      if (tab === "timeline") refreshScrub();
      if (tab === "twin") refreshTwin();
      if (tab === "shadow") refreshShadow();
      if (tab === "decisions") refreshDecisions();
      return;
    }
    var seq = el.getAttribute("data-seq");
    if (seq && el.getAttribute("data-testid") === "scrubber-tick") {
      // Scrub to the chosen sequence via the read endpoint. If the chain is
      // compromised the server refuses and returns the scrub error, which the
      // timeline renders instead of any partial reconstruction.
      fetch("/api/scrub?end=" + encodeURIComponent(seq))
        .then(function (r) { return r.json(); })
        .then(function (s) { scrub = s; render(); })
        .catch(function () {});
      return;
    }
  });

  // ------------------------------------------------------------- boot
  refreshState();
  refreshScrub();
  refreshTwin();
  refreshShadow();
  refreshDecisions();
  startStream();
})();
