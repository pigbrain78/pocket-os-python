// Pocket OS /api/v1 contract models.
//
// These types mirror the canonical JSON contract exactly — no web-only
// concepts, no localStorage, no DOM. A Swift client (UIKit, SwiftUI, or CLI)
// decodes these from the same `/api/v1` surface the web client consumes.

import Foundation

// MARK: - Epistemic state
// Preserved verbatim from the contract. Never collapse into a generic boolean.
public enum EpistemicStatus: String, Codable, Sendable {
    case observed = "OBSERVED"
    case verified = "VERIFIED"
    case inferred = "INFERRED"
    case proposed = "PROPOSED"
    case uncertain = "UNCERTAIN"
    case rejected = "REJECTED"
    case stale = "STALE"
}

public enum DecisionStatus: String, Codable, Sendable {
    case proposed = "PROPOSED"
    case pending = "PENDING"
    case council = "COUNCIL"
    case ratified = "RATIFIED"
    case rejected = "REJECTED"
    case executed = "EXECUTED"
}

public enum AIShadowType: String, Codable, Sendable {
    case observation = "OBSERVATION"
    case insight = "INSIGHT"
    case warning = "WARNING"
    case opportunity = "OPPORTUNITY"
    case question = "QUESTION"
    case recommendation = "RECOMMENDATION"
    case proposal = "PROPOSAL"
}

public enum LedgerIntegrity: String, Codable, Sendable {
    case intact = "INTACT"
    case compromised = "COMPROMISED"
}

// MARK: - API envelope
public struct APIEnvelope: Codable, Sendable {
    public var requestID: String
    public var apiVersion: String
    public var schemaVersion: String

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case apiVersion = "api_version"
        case schemaVersion = "schema_version"
    }
}

// MARK: - System status
public struct LedgerStatus: Codable, Sendable {
    public var integrity: LedgerIntegrity
    public var valid: Bool
    public var brokenSeq: Int?
    enum CodingKeys: String, CodingKey { case integrity, valid, brokenSeq = "broken_seq" }
}

public struct SystemStatus: Codable, Sendable {
    public var requestID: String
    public var apiVersion: String
    public var schemaVersion: String
    public var status: String
    public var ledger: LedgerStatus
    public var records: Int
    public var revision: Int
    public var serverTime: Int64
    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", apiVersion = "api_version", schemaVersion = "schema_version"
        case status, ledger, records, revision, serverTime = "server_time"
    }
}

// MARK: - Memory
public struct MemoryRecord: Codable, Sendable {
    public var id: String
    public var sequence: Int
    public var event: String
    public var kind: String
    public var payload: [String: JSONValue]
    public var hash: String
    public var provenance: String
}

// Minimal JSON value erasure so nested payloads decode without lossy casts.
public enum JSONValue: Codable, Sendable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null
    /// Convenience accessor for reading nested payload strings.
    public var stringValue: String? {
        if case .string(let s) = self { return s }
        return nil
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if let s = try? c.decode(String.self) { self = .string(s) }
        else if let o = try? c.decode([String: JSONValue].self) { self = .object(o) }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else { throw DecodingError.dataCorruptedError(in: c, debugDescription: "unexpected JSON") }
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .object(let o): try c.encode(o)
        case .array(let a): try c.encode(a)
        case .null: try c.encodeNil()
        }
    }
}

// MARK: - Ledger event
public struct LedgerEvent: Codable, Sendable {
    public var sequence: Int
    public var event: String
    public var timestamp: Int64
    public var source: String
    public var schemaVersion: String
    public var kind: String
    public var payload: [String: JSONValue]
    public var previousHash: String?
    public var hash: String
    enum CodingKeys: String, CodingKey {
        case sequence, event, timestamp, source, kind, payload, hash
        case schemaVersion = "schema_version"
        case previousHash = "previous_hash"
    }
}
