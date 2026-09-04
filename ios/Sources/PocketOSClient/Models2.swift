// Cognitive Twin, AI Shadow, and Decision models mirroring /api/v1.

import Foundation

// MARK: - Cognitive Twin
public struct CognitiveItem: Codable, Sendable {
    public var text: String
    public var epistemic: EpistemicStatus
    public var confidence: Double
    public var evidence: [Int]
    public var provenance: String
}

public struct CognitiveState: Codable, Sendable {
    public var currentFocus: CognitiveItem
    public var activeProjects: [CognitiveItem]
    public var openLoops: [CognitiveItem]
    public var closedLoops: [CognitiveItem]
    enum CodingKeys: String, CodingKey {
        case currentFocus = "current_focus"
        case activeProjects = "active_projects"
        case openLoops = "open_loops"
        case closedLoops = "closed_loops"
    }
}

public struct CognitiveTwin: Codable, Sendable {
    public var modelVersion: String
    public var lastUpdateSeq: Int
    public var epistemicLegend: [String]
    public var summary: String
    public var state: CognitiveState
    public var relevantMemories: [CognitiveItem]
    public var decisionHistory: [CognitiveItem]
    public var relationships: [CognitiveItem]
    public var recentObservations: [CognitiveItem]
    enum CodingKeys: String, CodingKey {
        case modelVersion = "model_version"
        case lastUpdateSeq = "last_update_seq"
        case epistemicLegend = "epistemic_legend"
        case summary, state
        case relevantMemories = "relevant_memories"
        case decisionHistory = "decision_history"
        case relationships, recentObservations = "recent_observations"
    }
}

// MARK: - AI Shadow
public struct AIShadowItem: Codable, Sendable {
    public var type: AIShadowType
    public var text: String
    public var confidence: Double
    public var evidence: [Int]
    public var provenance: String
    public var status: String
    /// The AI Shadow is advisory: this is always NONE. It cannot execute.
    public var authority: String
    public var nextStep: String?
    enum CodingKeys: String, CodingKey {
        case type, text, confidence, evidence, provenance, status, authority
        case nextStep = "next_step"
    }
}

public struct AIShadow: Codable, Sendable {
    public var types: [String]
    public var items: [AIShadowItem]
    public var authorityBoundary: AuthorityBoundary
    enum CodingKeys: String, CodingKey {
        case types, items
        case authorityBoundary = "authority_boundary"
    }
}

public struct AuthorityBoundary: Codable, Sendable {
    public var shadowAuthority: String
    public var shadowCanExecute: Bool
    public var shadowCanRatify: Bool
    /// Ordered list of prerequisites (e.g. ["COUNCIL_CONSENSUS","HUMAN_RATIFICATION"]).
    public var executionRequires: [String]
    enum CodingKeys: String, CodingKey {
        case shadowAuthority = "shadow_authority"
        case shadowCanExecute = "shadow_can_execute"
        case shadowCanRatify = "shadow_can_ratify"
        case executionRequires = "execution_requires"
    }
}

// MARK: - Decision
public struct Decision: Codable, Sendable {
    public var decisionID: String
    public var title: String
    public var proposalSeq: Int?
    public var status: DecisionStatus
    public var stage: String
    public var lifecycle: [String]
    public var humanRatified: Bool
    public var rejected: Bool
    public var reasonHash: String?
    public var councilApproved: Bool
    public var risk: String?
    public var reversible: Bool?
    public var executedSeq: Int?
    public var canExecute: Bool
    public var evidenceStage: String?
    enum CodingKeys: String, CodingKey {
        case decisionID = "decision_id", title
        case proposalSeq = "proposal_seq", status, stage, lifecycle
        case humanRatified = "human_ratified", rejected
        case reasonHash = "reason_hash", councilApproved = "council_approved"
        case risk, reversible, executedSeq = "executed_seq"
        case canExecute = "can_execute", evidenceStage = "evidence_stage"
    }
}

public struct DecisionsList: Codable, Sendable {
    public var requestID: String
    public var apiVersion: String
    public var schemaVersion: String
    public var items: [Decision]
    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", apiVersion = "api_version", schemaVersion = "schema_version"
        case items
    }
}

public struct DecisionAction: Codable, Sendable {
    public var requestID: String
    public var apiVersion: String
    public var schemaVersion: String
    public var ok: Bool
    public var decision: Decision
    enum CodingKeys: String, CodingKey {
        case requestID = "request_id", apiVersion = "api_version", schemaVersion = "schema_version"
        case ok, decision
    }
}
