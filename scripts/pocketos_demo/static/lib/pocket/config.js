/* Pocket OS client configuration.
 *
 * Runtime-injected configuration for API endpoints. Defaults to same-origin
 * relative paths. Deployment can provide an alternate origin via:
 *
 *   <script>
 *     window.__pocketConfig = { apiOrigin: "https://api.example.com" };
 *   </script>
 *   <script src="/static/lib/pocket/config.js"></script>
 *
 * The transport layer consumes this config; the UI and domain client never
 * know wire details.
 */
(function (global) {
  "use strict";

  // User-provided config, if any. Must be set before this script loads.
  var userConfig = global.__pocketConfig || {};

  // Runtime configuration singleton.
  var config = {
    // API origin (protocol + host + optional port).
    // Default: same-origin (relative paths).
    // Override: set window.__pocketConfig.apiOrigin before loading this script.
    apiOrigin: userConfig.apiOrigin || "",

    // Resolved API base URL (origin + /api/v1).
    get apiBaseURL() {
      var origin = this.apiOrigin || "";
      if (origin && !origin.endsWith("/")) origin += "/";
      return origin + "api/v1";
    },

    // Resolved legacy API base URL (origin + /api).
    get legacyAPIBaseURL() {
      var origin = this.apiOrigin || "";
      if (origin && !origin.endsWith("/")) origin += "/";
      return origin + "api";
    },

    // Resolved SSE stream URL (origin + /api/stream).
    get streamURL() {
      var origin = this.apiOrigin || "";
      if (origin && !origin.endsWith("/")) origin += "/";
      return origin + "api/stream";
    },

    // For debugging: verify the resolved URLs match expectations.
    describe: function () {
      return {
        apiOrigin: this.apiOrigin,
        apiBaseURL: this.apiBaseURL,
        legacyAPIBaseURL: this.legacyAPIBaseURL,
        streamURL: this.streamURL,
      };
    },
  };

  global.__pocketConfig = config;
})(window);
