// APIEnvelope.swift
// Canonical API envelope shapes returned by the Pocket OS backend. Every
// projection endpoint carries an integrity + schema_version prefix, and each
// nests its typed payload under a specific key (cognitive_twin / ai_shadow /
// decisions). Concrete response types below decode the real wire contract.

import Foundation

/// Canonical API error classification (master contract §11). Errors are
/// normalized so a client never displays a raw stack trace.
public enum PocketAPIError: Error, Equatable, Sendable {
    case network
    case authentication
    case authorization
    case validation
    case server
    case staleState
    case conflict
    case unknown

    public var humanMessage: String {
        switch self {
        case .network: return "Network error — check your connection and try again."
        case .authentication: return "Authentication failed. Please sign in again."
        case .authorization: return "You are not authorized to perform this action."
        case .validation: return "The request was invalid. Please review and retry."
        case .server: return "The server reported an error. Please try again shortly."
        case .staleState: return "The displayed state is stale. Refreshing…"
        case .conflict: return "A conflict was detected. Refresh and try again."
        case .unknown: return "An unexpected error occurred."
        }
    }
}

/// Cognitive Twin endpoint response: `/api/twin`.
public struct TwinResponse: Codable, Sendable, Equatable {
    public var integrity: String
    public var brokenSeq: Int?
    public var schemaVersion: String?
    public var cognitiveTwin: CognitiveTwinProjection?

    public enum CodingKeys: String, CodingKey {
        case integrity
        case brokenSeq = "broken_seq"
        case schemaVersion = "schema_version"
        case cognitiveTwin = "cognitive_twin"
    }
}

/// AI Shadow endpoint response: `/api/shadow`.
public struct ShadowResponse: Codable, Sendable, Equatable {
    public var integrity: String
    public var brokenSeq: Int?
    public var schemaVersion: String?
    public var aiShadow: ShadowProjection?

    public enum CodingKeys: String, CodingKey {
        case integrity
        case brokenSeq = "broken_seq"
        case schemaVersion = "schema_version"
        case aiShadow = "ai_shadow"
    }
}

/// Decisions endpoint response: `/api/decisions`.
public struct DecisionsResponse: Codable, Sendable, Equatable {
    public var integrity: String
    public var brokenSeq: Int?
    public var schemaVersion: String?
    public var decisions: [PocketDecision]

    public enum CodingKeys: String, CodingKey {
        case integrity
        case brokenSeq = "broken_seq"
        case schemaVersion = "schema_version"
        case decisions
    }
}
