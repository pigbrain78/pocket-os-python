// PocketOSClient.swift
// Transport + projection client. UI → ViewModel → projections → client → API.
// This is the ONLY place raw HTTP happens. The client is untrusted: it sends
// only what the API accepts and never fabricates authority/hash/sequence.
//
// The live SSE consumer (/api/stream) is implemented in the Apple-gated file
// PocketEventStream+iOS.swift using a URLSession delegate for incremental
// parsing. The Linux build of this package omits that file; SSE is exercised
// end-to-end in the Xcode/iOS build (see ios/README.md).

import Foundation

#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// PocketOSClient: session + canonical projection transport.
public final class PocketOSClient: @unchecked Sendable {
    public let baseURL: URL
    private var session: PocketSession?

    public init(baseURL: URL) { self.baseURL = baseURL }

    // MARK: Session

    /// Log in against the real backend. The server issues the bearer token and
    /// owns its lifecycle.
    @discardableResult
    public func login(username: String, password: String) async throws -> PocketSession {
        struct LoginBody: Encodable { let username: String; let password: String }
        let s: PocketSession = try await request(
            path: "/api/login", method: "POST",
            body: LoginBody(username: username, password: password)
        )
        self.session = s
        return s
    }

    public func logout() async {
        guard let token = session?.token else { session = nil; return }
        var req = URLRequest(url: endpoint("/api/logout"))
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        _ = try? await URLSession.shared.data(for: req)
        session = nil
    }

    /// Refresh the current session against `/api/session/me`; a 401 clears it.
    @discardableResult
    public func refreshSession() async throws -> PocketSession? {
        guard session?.token != nil else { return nil }
        do {
            let me: PocketSession = try await request(path: "/api/session/me", method: "GET")
            self.session = me
            return me
        } catch PocketAPIError.authentication {
            session = nil
            return nil
        }
    }

    // MARK: Canonical projections

    public func fetchTwin() async throws -> CognitiveTwinProjection {
        let r: TwinResponse = try await request(path: "/api/twin", method: "GET")
        guard let twin = r.cognitiveTwin else { throw PocketAPIError.server }
        return twin
    }

    public func fetchShadow() async throws -> ShadowProjection {
        let r: ShadowResponse = try await request(path: "/api/shadow", method: "GET")
        guard let s = r.aiShadow else { throw PocketAPIError.server }
        return s
    }

    public func fetchDecisions() async throws -> [PocketDecision] {
        let r: DecisionsResponse = try await request(path: "/api/decisions", method: "GET")
        return r.decisions
    }

    public func fetchState() async throws -> PocketStateProjection {
        try await request(path: "/api/state", method: "GET")
    }

    /// The authoritative live event stream endpoint.
    public var eventStreamURL: URL { endpoint("/api/stream") }

    // MARK: Transport

    private func endpoint(_ path: String) -> URL {
        URL(string: path, relativeTo: baseURL)!.absoluteURL
    }

    private func request<D: Decodable & Sendable>(path: String, method: String,
                                                  body: (any Encodable)? = nil)
        async throws -> D {
        var req = URLRequest(url: endpoint(path))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token = session?.token {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONEncoder().encode(body)
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            throw PocketAPIError.network
        }
        guard let http = response as? HTTPURLResponse else { throw PocketAPIError.network }
        switch http.statusCode {
        case 200...299:
            do { return try JSONDecoder().decode(D.self, from: data) }
            catch { throw PocketAPIError.server }
        case 401:
            session = nil
            throw PocketAPIError.authentication
        case 403:
            throw PocketAPIError.authorization
        case 409:
            throw PocketAPIError.conflict
        case 422:
            throw PocketAPIError.validation
        default:
            throw PocketAPIError.server
        }
    }
}
