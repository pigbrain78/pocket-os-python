/* pocket transport layer.
 *
 * Owns HTTP, authentication/session headers, serialization, error
 * normalization, request-id propagation, and API versioning. It is the ONLY
 * place that knows wire paths. No business logic lives here — that belongs to
 * index.js (the PocketClient domain facade).
 */
(function (global) {
  "use strict";

  var BASE = "/api/v1";
  var AUTH_BASE = "/api";  // auth/session endpoints are not yet versioned

  // Stable machine-readable error codes carried in normalized responses.
  var CODES = {
    AUTHENTICATION_REQUIRED: "AUTHENTICATION_REQUIRED",
    AUTHORIZATION_DENIED: "AUTHORIZATION_DENIED",
    GOVERNANCE_REJECTED: "GOVERNANCE_REJECTED",
    LEASE_EXPIRED: "LEASE_EXPIRED",
    VALIDATION_FAILED: "VALIDATION_FAILED",
    NOT_FOUND: "NOT_FOUND",
    CONFLICT: "CONFLICT",
    REPLAY_REJECTED: "REPLAY_REJECTED",
    VERIFICATION_FAILED: "VERIFICATION_FAILED",
    RATE_LIMITED: "RATE_LIMITED",
    CONTRACT_MISMATCH: "CONTRACT_MISMATCH",
    INTERNAL_ERROR: "INTERNAL_ERROR",
    NETWORK_ERROR: "NETWORK_ERROR",
  };

  // ---- error model ------------------------------------------------------
  // Every failure surfaced to the UI is a PocketError with a machine-readable
  // code. The transport never throws a raw HTTP/network error.
  function PocketError(code, message, requestId, status) {
    this.code = code;
    this.message = message || code;
    this.requestId = requestId || null;
    this.status = status || null;
    this.name = "PocketError";
  }
  PocketError.prototype = Object.create(Error.prototype);

  function codeForStatus(status) {
    switch (status) {
      case 401: return CODES.AUTHENTICATION_REQUIRED;
      case 403: return CODES.AUTHORIZATION_DENIED;
      case 404: return CODES.NOT_FOUND;
      case 409: return CODES.CONFLICT;
      case 422: return CODES.VALIDATION_FAILED;
      case 429: return CODES.RATE_LIMITED;
      default: return CODES.INTERNAL_ERROR;
    }
  }

  // ---- client-side contract enforcement -------------------------------
  // The committed contract spec (contract_spec.js, generated from the golden
  // fixture) is the shape the client is allowed to consume. Every /api/v1
  // success response is validated against it before the UI sees the data, so a
  // drifted server shape cannot silently pass through. If the contract has
  // intentionally changed, the fixture/spec are regenerated and versioned
  // together — the client never silently tolerates drift.
  function validateV1(path, json) {
    var spec = global.__pocketContract;
    if (!spec || !spec.paths) return; // spec not loaded
    var required = spec.paths[path];
    if (!required) return; // path not under the versioned contract spec
    if (!json || typeof json !== "object") {
      throw new PocketError(CODES.CONTRACT_MISMATCH, "response is not an object for " + path, null, null);
    }
    var missing = (required || []).filter(function (k) { return !(k in json); });
    if (missing.length) {
      throw new PocketError(
        CODES.CONTRACT_MISMATCH,
        "contract drift at " + path + ": missing " + missing.join(",") + " — server shape no longer matches the locked contract",
        json.request_id, null
      );
    }
    if (typeof json.api_version === "undefined" || typeof json.schema_version === "undefined") {
      throw new PocketError(
        CODES.CONTRACT_MISMATCH,
        "contract drift at " + path + ": missing version envelope (api_version/schema_version)",
        json.request_id, null
      );
    }
  }

  function transport(tokenProvider) {
    function headers(method, body) {
      var h = { "Accept": "application/json", "Content-Type": "application/json" };
      if (method === "POST" && body === undefined) {
        // keep content-type for POST even with empty body
      }
      var tok = tokenProvider ? tokenProvider() : null;
      if (tok) h["Authorization"] = "Bearer " + tok;
      return h;
    }

    function request(method, path, body, basePath) {
      // basePath selects the wire prefix: /api/v1 (default, versioned), /api
      // (legacy auth + the composite console projections the current UI reads),
      // or any origin-relative path. The transport alone owns these.
      var base = basePath || BASE;
      var url = base + path;
      return fetch(url, {
        method: method,
        headers: headers(method, body),
        body: method === "POST" || method === "PUT" ? JSON.stringify(body || {}) : undefined,
      }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (json) {
          var rid = res.headers.get("x-request-id") || null;
          if (!res.ok) {
            var err = (json && json.error) || {};
            var code = err.code || codeForStatus(res.status);
            if (code === "GOVERNANCE_REJECTED" || code === "SCRUB_REFUSED" || code === "REPLAY_REJECTED") {
              code = CODES.GOVERNANCE_REJECTED;
            }
            throw new PocketError(code, err.message || res.statusText, rid || err.request_id, res.status);
          }
          // Enforce the locked contract shape on the canonical /api/v1 surface
          // before the UI consumes the payload. A drifted server response is
          // rejected as CONTRACT_MISMATCH, never silently passed through.
          // Validate against the FULL wire path (base + path) because the
          // committed spec keys are absolute (/api/v1/status), not relative.
          if (base === BASE) validateV1(base + path, json);
          return json;
        });
      }).catch(function (e) {
        if (e instanceof PocketError) throw e;
        throw new PocketError(CODES.NETWORK_ERROR, e && e.message ? e.message : "network error", null, null);
      });
    }

    return {
      // Versioned /api/v1 contract (default).
      get: function (path) { return request("GET", path); },
      post: function (path, body) { return request("POST", path, body); },
      // Legacy /api prefix — auth/session endpoints and the composite console
      // projections the current UI renders. Owned by the transport only.
      getLegacy: function (path) { return request("GET", path, undefined, AUTH_BASE); },
      postLegacy: function (path, body) { return request("POST", path, body, AUTH_BASE); },
    };
  }

  global.__pocketTransport = {
    CODES: CODES,
    PocketError: PocketError,
    create: transport,
    BASE: BASE,
  };
})(window);
