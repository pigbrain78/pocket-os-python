import XCTest
@testable import PocketOSClient

final class StatusActionFlowTests: XCTestCase {
    func testFetchStatusReturnsCanonicalStatus() async throws {
        let expected = SystemStatus(
            requestID: "r-1",
            apiVersion: "1",
            schemaVersion: "v2",
            status: "healthy",
            ledger: LedgerStatus(integrity: .intact, valid: true, brokenSeq: nil),
            records: 12,
            revision: 4,
            serverTime: 1234
        )
        let flow = StatusActionFlow(
            loadStatus: { expected },
            sendProposal: { _, _ in
                XCTFail("submit should not be called")
                throw CancellationError()
            }
        )

        let actual = try await flow.fetchStatus()
        XCTAssertEqual(actual.status, "healthy")
        XCTAssertEqual(actual.ledger.integrity, .intact)
        XCTAssertEqual(actual.records, 12)
    }

    func testSubmitActionUsesProvidedTitleAndReturnsDecision() async throws {
        var capturedTitle = ""
        var capturedCouncil = false
        let flow = StatusActionFlow(
            loadStatus: {
                throw CancellationError()
            },
            sendProposal: { title, sendToCouncil in
                capturedTitle = title
                capturedCouncil = sendToCouncil
                return try JSONDecoder().decode(
                    Decision.self,
                    from: """
                    {"decision_id":"D-1","title":"Ship mobile status","proposal_seq":10,
                     "status":"PENDING","stage":"pending","lifecycle":["proposed"],
                     "human_ratified":false,"rejected":false,"reason_hash":null,
                     "council_approved":false,"risk":"MEDIUM","reversible":true,
                     "executed_seq":null,"can_execute":false,"evidence_stage":"proposed"}
                    """.data(using: .utf8)!
                )
            }
        )

        let decision = try await flow.submitAction(title: "Ship mobile status", sendToCouncil: true)
        XCTAssertEqual(capturedTitle, "Ship mobile status")
        XCTAssertTrue(capturedCouncil)
        XCTAssertEqual(decision.decisionID, "D-1")
    }
}
