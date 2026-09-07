// EpistemicStatus.swift
// Canonical epistemic states. These MUST mirror the backend legend exactly;
// do not add new states unless the backend adds them.

import Foundation

/// The canonical epistemic legend returned by the Pocket OS backend.
public enum EpistemicStatus: String, Codable, CaseIterable, Sendable {
    case observed = "OBSERVED"
    case verified = "VERIFIED"
    case inferred = "INFERRED"
    case uncertain = "UNCERTAIN"
    case rejected = "REJECTED"
    case stale = "STALE"

    public init?(rawValue: String) {
        switch rawValue.uppercased() {
        case "OBSERVED": self = .observed
        case "VERIFIED": self = .verified
        case "INFERRED": self = .inferred
        case "UNCERTAIN": self = .uncertain
        case "REJECTED": self = .rejected
        case "STALE": self = .stale
        default: return nil
        }
    }

    /// Whether this status may be presented as an established fact.
    /// INFERRED / UNCERTAIN / PROPOSED-adjacent states are advisory only.
    public var isAuthoritative: Bool {
        switch self {
        case .verified, .observed: return true
        case .inferred, .uncertain, .rejected, .stale: return false
        }
    }
}

/// A single derived belief: text + how the system knows it.
public struct TwinItem: Codable, Equatable, Sendable {
    public var text: String
    public var epistemic: EpistemicStatus?
    public var confidence: Double?
    public var evidence: [Int]
    public var provenance: String

    public init(text: String, epistemic: EpistemicStatus?, confidence: Double?,
                evidence: [Int], provenance: String) {
        self.text = text
        self.epistemic = epistemic
        self.confidence = confidence
        self.evidence = evidence
        self.provenance = provenance
    }
}

/// The Cognitive Twin projection — a deterministic fold over the ledger.
public struct CognitiveTwinProjection: Codable, Equatable, Sendable {
    public var modelVersion: String
    public var lastUpdateSeq: Int
    public var epistemicLegend: [EpistemicStatus]
    public var summary: String
    public var state: TwinState
    public var relevantMemories: [TwinItem]
    public var decisionHistory: [TwinItem]
    public var relationships: [TwinItem]
    public var recentObservations: [TwinItem]

    public struct TwinState: Codable, Equatable, Sendable {
        public var currentFocus: TwinItem?
        public var openLoops: [TwinItem]
        public var closedLoops: [TwinItem]
        public var activeProjects: [TwinItem]

        enum CodingKeys: String, CodingKey {
            case currentFocus = "current_focus"
            case openLoops = "open_loops"
            case closedLoops = "closed_loops"
            case activeProjects = "active_projects"
        }
    }

    enum CodingKeys: String, CodingKey {
        case modelVersion = "model_version"
        case lastUpdateSeq = "last_update_seq"
        case epistemicLegend = "epistemic_legend"
        case summary, state
        case relevantMemories = "relevant_memories"
        case decisionHistory = "decision_history"
        case relationships
        case recentObservations = "recent_observations"
    }
}
