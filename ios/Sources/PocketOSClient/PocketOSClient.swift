// PocketOSClient — domain facade mirroring the web pocket client's contract.
//
// The iOS client consumes the SAME /api/v1 canonical contract as the web
// PocketClient: one canonical system, two clients. No web-specific concepts,
// no localStorage, no DOM — only stable JSON types, IDs, and timestamps.

import Foundation

public final class PocketOSClient: @unchecked Sendable {
    public let transport: PocketTransport
    /// Live event spine subscription. Mirror of pocket.events.subscribe.
    public let events = EventQueue()

    public init(baseURL: URL) {
        self.transport = PocketTransport(baseURL: baseURL)
    }

    // MARK: - Session
    public func login(username: String, password: String) async throws {
        try await transport.login(username: username, password: password)
    }
    public func logout() async throws {
        try await transport.logout()
    }

    // MARK: - Queries (read canonical state)
    public func getStatus() async throws -> SystemStatus {
        try await transport.status()
    }
    public func listMemory() async throws -> [MemoryRecord] {
        try await transport.memory()
    }
    public func getMemory(id: String) async throws -> MemoryRecord {
        try await transport.memory(id: id)
    }
    public func getCognitiveTwin() async throws -> CognitiveTwin {
        try await transport.cognitiveTwin()
    }
    public func getAIShadow() async throws -> AIShadow {
        try await transport.aiShadow()
    }
    public func listDecisions() async throws -> DecisionsList {
        try await transport.decisions()
    }
    public func getDecision(id: String) async throws -> Decision {
        try await transport.decision(id: id)
    }
    public func getLedgerEvent(sequence: Int) async throws -> LedgerEvent {
        try await transport.ledgerEvent(sequence: sequence)
    }

    // MARK: - Commands (governance-bound; never direct execution)
    public func createProposal(title: String, sendToCouncil: Bool = true) async throws -> Decision {
        try await transport.propose(title: title, sendToCouncil: sendToCouncil)
    }
    public func ratify(decisionID: String) async throws -> Decision {
        try await transport.ratify(decisionID: decisionID)
    }
    public func reject(decisionID: String) async throws -> Decision {
        try await transport.reject(decisionID: decisionID)
    }

    // MARK: - Live events
    /// Subscribe to normalized observation envelopes from the /api/stream spine.
    @discardableResult
    public func subscribe(_ handler: @escaping (EventEnvelope) -> Void) -> UUID {
        events.add(handler)
    }
    public func unsubscribe(_ id: UUID) {
        events.remove(id)
    }
}
