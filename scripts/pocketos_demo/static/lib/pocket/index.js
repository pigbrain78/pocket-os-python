/* PocketClient — the domain-oriented facade the UI consumes.
 *
 * The UI must interact with Pocket OS through this object and NEVER call raw
 * API routes, fetch(), or server internals directly. index.js knows domain
 * concepts and response schemas; transport.js owns the wire.
 *
 *   UI  -->  PocketClient (index.js)  -->  PocketTransport (transport.js)
 *          -->  Pocket OS API (/api/v1)
 *
 * Server state is authoritative. Any local cache is a projection, and when a
 * cache and the server disagree the server wins.
 */
(function (global) {
  "use strict";

  var t = global.__pocketTransport;
  if (!t) throw new Error("pocket transport not loaded");
  var PocketError = t.PocketError;
  var CODES = t.CODES;

  var _token = null;

  // ---- auth helpers (session is owned by the client, kept in memory only;
  // never persisted to localStorage — the browser must not hold canonical
  // state or credentials on disk). -----------------------------
  function setToken(tok) { _token = tok; }
  function token() { return _token; }
  function clearToken() { _token = null; }

  var http = t.create(function () { return _token; });

  // ---- live event spine (SSE) -----------------------------------------
  // The pocket client owns the EventSource lifecycle. Subscribers register via
  // pocket.events.subscribe(cb); the client forwards normalized observations
  // and lets the subscriber reconcile with the authoritative server. Receiving
  // an event never means this client caused it.
  //
  // Reconnection strategy: exponential backoff with jitter, resync on reconnect.
  var _es = null;
  var _reconnectAttempts = 0;
  var _maxReconnectAttempts = 6; // 1s, 2s, 4s, 8s, 16s, 30s, then capped at 30s
  var _statusListeners = [];
  var _lastEventSequence = null; // Track last successful event for cursor-based recovery

  function status(s) {
    for (var i = 0; i < _statusListeners.length; i++) {
      try { _statusListeners[i](s); } catch (e) {}
    }
  }

  function _safeParse(text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  function _backoffDelay(attempt) {
    // Exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (capped).
    var delays = [1000, 2000, 4000, 8000, 16000, 30000];
    var base = delays[Math.min(attempt, delays.length - 1)];
    // Add jitter: ±10% of base delay
    var jitter = (Math.random() - 0.5) * 0.2 * base;
    return Math.max(0, base + jitter);
  }

  function _attemptReconnect() {
    if (_reconnectAttempts >= _maxReconnectAttempts) {
      // Cap at max delay (30s) rather than growing forever.
      _reconnectAttempts = _maxReconnectAttempts - 1;
    }
    var delay = _backoffDelay(_reconnectAttempts);
    _reconnectAttempts += 1;
    status("reconnecting");
    setTimeout(function () {
      if (_es === null) {
        // Still disconnected; attempt to reconnect.
        connect();
      }
    }, delay);
  }

  function connect() {
    if (typeof EventSource === "undefined") { status("unsupported"); return; }
    if (_es) return;
    status("connecting");
    var config = global.__pocketConfig;
    var streamUrl = config ? config.streamURL : "/api/stream";
    var es = new EventSource(streamUrl);
    _es = es;

    es.addEventListener("hello", function (e) {
      var payload = _safeParse(e.data);
      if (payload) {
        // Reset backoff on successful connection.
        _reconnectAttempts = 0;
      }
      status("live");
    });

    es.addEventListener("event", function (e) {
      var payload = _safeParse(e.data);
      if (!payload) return;

      // Canonical live-event envelope — the same field set the Swift client's
      // EventEnvelope decodes. Forward every provenance field so a client can
      // reason about type, source, and chain position, never just payload.
      var event = {
        type: payload.type || "event",
        event_id: payload.event_id || "",
        sequence: typeof payload.sequence === "number" ? payload.sequence : null,
        occurred_at: typeof payload.occurred_at === "number" ? payload.occurred_at : null,
        source: payload.source || "",
        kind: payload.kind || "",
        previous_hash: payload.previous_hash || "",
        schema_version: payload.schema_version || "v2",
        payload: payload.payload || {},
      };

      // Track the last successfully processed event sequence for cursor-based
      // recovery (when the server supports it). This allows the client to
      // request only events after this sequence on reconnect, rather than
      // refetching the entire state.
      if (typeof event.sequence === "number" && event.sequence > 0) {
        _lastEventSequence = event.sequence;
      }

      emit(event);
      status("live");
    });

    es.onerror = function () {
      // EventSource auto-reconnect is disabled; we manage reconnection with
      // exponential backoff. On error, close the connection and schedule
      // a reconnect attempt.
      if (_es) {
        _es.close();
        _es = null;
      }
      _attemptReconnect();
    };
  }

  function disconnect() {
    if (_es) { _es.close(); _es = null; }
    _reconnectAttempts = 0;
  }

  function onStatus(cb) { _statusListeners.push(cb); }

  // Events: the UI registers one or more listeners; on a live SSE event the
  // client forwards normalized observations and the subscriber reconciles by
  // refetching authoritative projections.
  var _listeners = [];
  function subscribe(fn) {
    _listeners.push(fn);
    return function () { _listeners = _listeners.filter(function (x) { return x !== fn; }); };
  }
  function emit(event) {
    for (var i = 0; i < _listeners.length; i++) {
      try { _listeners[i](event); } catch (e) {}
    }
  }

  // ---- domain methods (queries) ----------------------------------------
  var pocket = {
    // system
    system: {
      getStatus: function () { return http.get("/status"); },
    },

    // memory
    memory: {
      list: function () { return http.get("/memory"); },
      get: function (id) { return http.get("/memory/" + encodeURIComponent(id)); },
    },

    // cognitive twin
    cognitiveTwin: {
      getState: function () { return http.get("/cognitive-twin"); },
    },

    // ai shadow
    aiShadow: {
      listObservations: function () { return http.get("/ai-shadow"); },
    },

    // decisions
    decisions: {
      list: function () { return http.get("/decisions"); },
      get: function (id) { return http.get("/decisions/" + encodeURIComponent(id)); },
      // commands — never execution; they record proposals / ratification
      propose: function (input) { return http.post("/decisions/propose", input || {}); },
      ratify: function (id) { return http.post("/decisions/" + encodeURIComponent(id) + "/ratify", {}); },
      reject: function (id) { return http.post("/decisions/" + encodeURIComponent(id) + "/reject", {}); },
    },

    // ledger
    ledger: {
      getStatus: function () { return http.get("/ledger"); },
      listEvents: function () { return http.get("/ledger"); },
      getEvent: function (id) { return http.get("/ledger/events/" + encodeURIComponent(id)); },
    },

    // replay
    replay: {
      getStatus: function () { return http.get("/replay/status"); },
      inspect: function (opts) {
        var q = "";
        opts = opts || {};
        if (opts.end) q += (q ? "&" : "?") + "end=" + encodeURIComponent(opts.end);
        if (opts.include_decisions) q += (q ? "&" : "?") + "include_decisions=true";
        return http.get("/replay/inspect" + q);
      },
    },

    // evidence
    evidence: {
      getVerificationStatus: function () { return http.get("/evidence/verification"); },
    },

    // events (subscription + live SSE spine ownership)
    events: {
      subscribe: subscribe,
      onStatus: onStatus,
      connect: connect,
      disconnect: disconnect,
      lastSequence: function () { return _lastEventSequence; },
    },

    // session (transport-level concerns exposed deliberately for login UI)
    session: {
      login: function (username, password) { return http.postLegacy("/login", { username: username, password: password }); },
      logout: function () { return http.postLegacy("/logout", {}); },
      me: function () { return http.getLegacy("/session/me"); },
      setToken: setToken,
      clearToken: clearToken,
      token: token,
    },

    // console: composite projections the current web console renders. These
    // mirror the legacy /api response shapes exactly so the existing UI keeps
    // working unchanged; they are routed through the transport, never direct
    // fetch. A future UI should consume the canonical domain methods above.
    console: {
      state: function () { return http.getLegacy("/state"); },
      scrub: function (end) {
        return http.getLegacy("/scrub" + (end ? "?end=" + encodeURIComponent(end) : ""));
      },
      twin: function () { return http.getLegacy("/twin"); },
      shadow: function () { return http.getLegacy("/shadow"); },
      decisions: function () { return http.getLegacy("/decisions"); },
      streamUrl: function () { return global.__pocketConfig ? global.__pocketConfig.streamURL : "/api/stream"; },
    },

    // demo: demo-gated mutators (reset/tamper) and the decision command verbs
    // that the console issues. Commands are never execution on their own —
    // they still travel the governance/constitutional path server-side.
    demo: {
      tamper: function () { return http.postLegacy("/demo/tamper", {}); },
      reset: function () { return http.postLegacy("/demo/reset", {}); },
    },
    command: function (decisionId, verb) {
      // council-approve / ratify / reject / execute against a decision.
      return http.postLegacy("/decisions/" + encodeURIComponent(decisionId) + "/" + verb, {});
    },
    propose: function (title, sendToCouncil) {
      return http.postLegacy("/decisions/propose", { title: title, send_to_council: !!sendToCouncil });
    },

    // Transport-level access for advanced uses; keep minimal.
    transport: { CODES: CODES, PocketError: PocketError, http: http },
  };

  // Expose a typed-ish guard helper so callers can test error codes without
  // string parsing.
  pocket.isError = function (e) { return e instanceof PocketError; };
  pocket.errorCode = function (e) { return (e && e.code) || null; };

  global.pocket = pocket;
})(window);
