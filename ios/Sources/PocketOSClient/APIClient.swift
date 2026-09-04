// Pocket OS API transport.
//
// Owns HTTP, the /api/v1 base path, bearer-session auth, JSON (de)serialization,
// error normalization, and the governance-bound command verbs. The client
// facade never touches URLSession directly. Mirrors the web pocket transport's
// responsibilities so both clients enforce the same boundary.

import Foundation

// MARK: - Errors
public enum PocketAPIError: Error, Sendable {
    case authenticationRequired
    case authorizationDenied
    case governanceRejected
    case validationFailed
    case notFound
    case conflict
    case rateLimited
    case contractMismatch
    case network(Error)
    case unexpectedStatus(Int)

    static func from(code: String) -> PocketAPIError {
        switch code {
        case "AUTHENTICATION_REQUIRED": return .authenticationRequired
        case "AUTHORIZATION_DENIED": return .authorizationDenied
        case "GOVERNANCE_REJECTED", "SCRUB_REFUSED", "REPLAY_REJECTED": return .governanceRejected
        case "VALIDATION_FAILED": return .validationFailed
        case "NOT_FOUND": return .notFound
        case "CONFLICT": return .conflict
        case "RATE_LIMITED": return .rateLimited
        case "CONTRACT_MISMATCH": return .contractMismatch
        default: return .unexpectedStatus(0)
        }
    }
}

struct ServerErrorBody: Codable {
    struct ErrorDetail: Codable { let code: String; let message: String; let requestID: String?
        enum CodingKeys: String, CodingKey { case code, message, requestID = "request_id" } }
    let error: ErrorDetail
}

// MARK: - Transport
public actor PocketTransport {
    private let baseURL: URL
    private var sessionToken: String?
    /// Atomic-ish queue of observers for live events.
    public let eventQueue: EventQueue = EventQueue()

    public init(baseURL: URL) {
        self.baseURL = baseURL
    }

    public func setToken(_ token: String?) {
        self.sessionToken = token
    }

    private var authHeaders: [String: String] {
        sessionToken.map { ["Authorization": "Bearer \($0)"] } ?? [:]
    }

    private func request<T: Decodable>(
        _ method: String, _ path: String, body: Data? = nil, as: T.Type
    ) async throws -> T {
        let url = baseURL.appendingPathComponent(path)
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.httpBody = body
        for (k, v) in authHeaders { req.setValue(v, forHTTPHeaderField: k) }
        if body != nil { req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        req.setValue(UUID().uuidString, forHTTPHeaderField: "x-request-id")

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            throw PocketAPIError.network(error)
        }
        guard let http = response as? HTTPURLResponse else {
            throw PocketAPIError.unexpectedStatus(0)
        }
        guard (200..<300).contains(http.statusCode) else {
            if let server = try? JSONDecoder().decode(ServerErrorBody.self, from: data) {
                throw PocketAPIError.from(code: server.error.code)
            }
            throw PocketAPIError.unexpectedStatus(http.statusCode)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    // MARK: Queries (read-only; never mutate canonical state)
    public func status() async throws -> SystemStatus {
        try await request("GET", "api/v1/status", as: SystemStatus.self)
    }
    public func memory() async throws -> [MemoryRecord] {
        struct W: Codable { let items: [MemoryRecord] }
        let w = try await request("GET", "api/v1/memory", as: W.self)
        return w.items
    }
    public func memory(id: String) async throws -> MemoryRecord {
        try await request("GET", "api/v1/memory/\(id)", as: MemoryRecord.self)
    }
    public func cognitiveTwin() async throws -> CognitiveTwin {
        struct W: Codable { let cognitiveTwin: CognitiveTwin
            enum CodingKeys: String, CodingKey { case cognitiveTwin = "cognitive_twin" } }
        let w = try await request("GET", "api/v1/cognitive-twin", as: W.self)
        return w.cognitiveTwin
    }
    public func aiShadow() async throws -> AIShadow {
        struct W: Codable { let aiShadow: AIShadow
            enum CodingKeys: String, CodingKey { case aiShadow = "ai_shadow" } }
        let w = try await request("GET", "api/v1/ai-shadow", as: W.self)
        return w.aiShadow
    }
    public func decisions() async throws -> DecisionsList {
        try await request("GET", "api/v1/decisions", as: DecisionsList.self)
    }
    public func decision(id: String) async throws -> Decision {
        struct W: Codable { let decision: Decision }
        let w = try await request("GET", "api/v1/decisions/\(id)", as: W.self)
        return w.decision
    }
    public func ledgerEvent(sequence: Int) async throws -> LedgerEvent {
        struct W: Codable { let event: LedgerEvent }
        let w = try await request("GET", "api/v1/ledger/events/\(sequence)", as: W.self)
        return w.event
    }

    // MARK: Commands (governance-bound; never direct execution)
    public func login(username: String, password: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["username": username, "password": password])
        struct R: Codable { let token: String }
        let r = try await request("POST", "api/login", body: body, as: R.self)
        await setToken(r.token)
    }
    public func logout() async throws {
        // Revoke server-side. POST with no body through the auth path.
        let url = baseURL.appendingPathComponent("api/logout")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        for (k, v) in authHeaders { req.setValue(v, forHTTPHeaderField: k) }
        _ = try? await URLSession.shared.data(for: req)
        await setToken(nil)
    }
    public func propose(title: String, sendToCouncil: Bool = true) async throws -> Decision {
        struct Body: Codable { let title: String; let sendToCouncil: Bool
            enum CodingKeys: String, CodingKey { case title, sendToCouncil = "send_to_council" } }
        let data = try JSONEncoder().encode(Body(title: title, sendToCouncil: sendToCouncil))
        struct W: Codable { let decision: Decision }
        let w = try await request("POST", "api/v1/decisions/propose", body: data, as: W.self)
        return w.decision
    }
    public func ratify(decisionID: String) async throws -> Decision {
        struct W: Codable { let decision: Decision }
        let w = try await request("POST", "api/v1/decisions/\(decisionID)/ratify", body: Data("{}".utf8), as: W.self)
        return w.decision
    }
    public func reject(decisionID: String) async throws -> Decision {
        struct W: Codable { let decision: Decision }
        let w = try await request("POST", "api/v1/decisions/\(decisionID)/reject", body: Data("{}".utf8), as: W.self)
        return w.decision
    }
}

/// Minimal live-event queue so an iOS client can subscribe to the SSE spine.
public final class EventQueue: @unchecked Sendable {
    private var observers: [UUID: (EventEnvelope) -> Void] = [:]
    private let lock = NSLock()
    public func add(_ fn: @escaping (EventEnvelope) -> Void) -> UUID {
        let id = UUID(); lock.lock(); observers[id] = fn; lock.unlock(); return id
    }
    public func remove(_ id: UUID) {
        lock.lock(); observers.removeValue(forKey: id); lock.unlock()
    }
    public func deliver(_ event: EventEnvelope) {
        lock.lock(); let fns = Array(observers.values); lock.unlock()
        for fn in fns { fn(event) }
    }
}

public struct EventEnvelope: Codable, Sendable {
    public var type: String
    public var eventID: String?
    public var sequence: Int?
    public var occurredAt: Int64?
    public var schemaVersion: String
    public var payload: [String: JSONValue]
    enum CodingKeys: String, CodingKey {
        case type, sequence, payload
        case eventID = "event_id"
        case occurredAt = "occurred_at"
        case schemaVersion = "schema_version"
    }
}
