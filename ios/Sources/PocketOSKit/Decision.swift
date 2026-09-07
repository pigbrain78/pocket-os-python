// Decision.swift
// Decision lifecycle + constitutional state. PROPOSAL / AUTHORIZATION /
// EXECUTION / EVIDENCE are four distinct stages and are never conflated.

import Foundation

public enum DecisionStatus: String, Codable, Sendable {
    case pending = "PENDING"
    case council = "COUNCIL"
    case awaitingRatification = "AWAITING_RATIFICATION"
    case ratified = "RATIFIED"
    case rejected = "REJECTED"
    case executed = "EXECUTED"

    public init?(rawValue: String) {
        switch rawValue.uppercased() {
        case "PENDING": self = .pending
        case "COUNCIL": self = .council
        case "AWAITING_RATIFICATION": self = .awaitingRatification
        case "RATIFIED": self = .ratified
        case "REJECTED": self = .rejected
        case "EXECUTED": self = .executed
        default: return nil
        }
    }
}

/// A decision in the registry. The client READS this; it never mutates
/// lifecycle directly — mutation only happens through the server's explicit
/// propose / ratify / reject operations.
public struct PocketDecision: Codable, Equatable, Sendable {
    public var decisionId: String
    public var title: String
    public var proposalSeq: Int?
    public var status: DecisionStatus?
    public var stage: String?
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

    public enum CodingKeys: String, CodingKey {
        case decisionId = "decision_id"
        case title
        case proposalSeq = "proposal_seq"
        case status, stage, lifecycle
        case humanRatified = "human_ratified"
        case rejected
        case reasonHash = "reason_hash"
        case councilApproved = "council_approved"
        case risk, reversible
        case executedSeq = "executed_seq"
        case canExecute = "can_execute"
        case evidenceStage = "evidence_stage"
    }
}

/// A single ledger record (as returned by /api/state).
public struct LedgerRecord: Codable, Equatable, Sendable {
    public var sequence: Int
    public var event: String
    public var timestamp: Int?
    public var source: String?
    public var schemaVersion: String?
    public var kind: String?
    public var payload: JSONValue?
    public var previousHash: String?
    public var hash: String

    public enum CodingKeys: String, CodingKey {
        case sequence, event, timestamp, source, kind, payload
        case schemaVersion = "schema_version"
        case previousHash = "previous_hash"
        case hash
    }
}

/// A genome trait.
public struct GenomeTrait: Codable, Equatable, Sendable {
    public var name: String
    public var score: Double
}

/// Full /api/state projection.
public struct PocketStateProjection: Codable, Equatable, Sendable {
    public var integrity: String
    public var valid: Bool
    public var brokenSeq: Int?
    public var recordCount: Int
    public var records: [LedgerRecord]
    public var counters: String
    public var traits: [GenomeTrait]
    public var contradictions: Int
    public var revision: Int

    public enum CodingKeys: String, CodingKey {
        case integrity, valid
        case brokenSeq = "broken_seq"
        case recordCount = "record_count"
        case records, counters, traits, contradictions, revision
    }
}
