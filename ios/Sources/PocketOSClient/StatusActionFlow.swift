import Foundation

/// One-screen mobile slice: read canonical status, then submit one proposal.
public final class StatusActionFlow: @unchecked Sendable {
    private let loadStatus: () async throws -> SystemStatus
    private let sendProposal: (_ title: String, _ sendToCouncil: Bool) async throws -> Decision

    public init(client: PocketOSClient) {
        self.loadStatus = { try await client.getStatus() }
        self.sendProposal = { title, sendToCouncil in
            try await client.createProposal(title: title, sendToCouncil: sendToCouncil)
        }
    }

    init(
        loadStatus: @escaping () async throws -> SystemStatus,
        sendProposal: @escaping (_ title: String, _ sendToCouncil: Bool) async throws -> Decision
    ) {
        self.loadStatus = loadStatus
        self.sendProposal = sendProposal
    }

    public func fetchStatus() async throws -> SystemStatus {
        try await loadStatus()
    }

    public func submitAction(title: String, sendToCouncil: Bool = true) async throws -> Decision {
        try await sendProposal(title, sendToCouncil)
    }
}
