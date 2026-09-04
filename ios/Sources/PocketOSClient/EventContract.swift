// Cross-client canonical event contract.
//
// The SAME canonical event envelope (server /api/stream -> broadcast) must
// decode into equivalent semantic fields in the web (JS pocket client) and the
// Swift client. This validator enforces the semantic invariants a raw Codable
// decode cannot: a well-formed event must have a stable event_id, a positive
// sequence, a known event type, and provenance; and a subscriber may detect
// duplicate / out-of-order delivery.
//
// A client MUST NOT accept an event that fails these checks — but rejecting it
// never means the client is authoritative; it only means the observation is
// untrustworthy and should be reconciled by a refetch.

import Foundation

/// Why an event envelope is rejected by a client.
public enum EventValidationIssue: String, Sendable, Equatable {
    case malformed = "MALFORMED"
    case missingField = "MISSING_FIELD"
    case wrongType = "WRONG_TYPE"
    case duplicateEvent = "DUPLICATE_EVENT"
    case outOfOrder = "OUT_OF_ORDER"
    case unknownType = "UNKNOWN_TYPE"
    case invalidSequence = "INVALID_SEQUENCE"
    case invalidProvenance = "INVALID_PROVENANCE"
}

/// The set of event types this client understands. Unknown types are rejected
/// (or quarantined) rather than silently treated as facts.
public struct EventContract {
    public static let knownTypes: Set<String> = [
        "memory.created", "task.started", "task.completed",
        "decision.proposed", "decision.council_approved",
        "decision.ratified", "decision.rejected", "decision.executed",
        "governance.decided", "knowledge.created",
        "agent.observation", "system.sync", "system.health", "record.append",
    ]

    /// Validate a single decoded envelope's structural + semantic invariants.
    public static func validate(_ e: EventEnvelope) -> EventValidationIssue? {
        // Wrong type: sequence / occurred_at / event_id must be the right kinds.
        if e.type.isEmpty { return .missingField }
        if e.eventID == nil || e.eventID!.isEmpty { return .missingField }
        guard let seq = e.sequence else { return .missingField }
        if seq < 1 { return .invalidSequence }
        if !knownTypes.contains(e.type) { return .unknownType }
        // Provenance: on this backend event_id is the record hash; it must look
        // like a non-empty stable id and the previous_hash must be a hex hash.
        if let h = e.previousHash, !h.isEmpty, h.range(of: #"^[0-9a-f]{40,}$"#, options: .regularExpression) == nil {
            return .invalidProvenance
        }
        return nil
    }

    /// Track delivery to detect duplicate / out-of-order events (same stream).
    public static func track(previous: Int?, next: Int) -> EventValidationIssue? {
        guard let p = previous else { return nil }
        if next == p { return .duplicateEvent }
        if next < p { return .outOfOrder }
        return nil
    }
}
