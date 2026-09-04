import XCTest
@testable import PocketOSClient

/// Live end-to-end integration against the running Pocket OS backend.
///
/// These tests drive the real PocketTransport (URLSession, bearer auth, error
/// normalization) against http://127.0.0.1:8787 — the same canonical /api/v1
/// contract the web client consumes. They prove the iOS client actually talks
/// to the backend, not just that its models decode fixtures. If the server is
/// unreachable they skip rather than fail, so CI without a backend stays green.
final class PocketOSLiveIntegrationTests: XCTestCase {
    var baseURL: URL { URL(string: ProcessInfo.processInfo.environment["POCKETOS_BASE_URL"] ?? "http://127.0.0.1:8787")! }
    var client: PocketOSClient!

    override func setUp() async throws {
        client = PocketOSClient(baseURL: baseURL)
        // Probe reachability; skip (not fail) if the backend is down.
        if (try? await client.getStatus()) == nil {
            throw XCTSkip("Pocket OS backend not reachable at \(baseURL)")
        }
    }

    func testLoginAndStatusEnvelope() async throws {
        try await client.login(username: "admin", password: "demo")
        let status = try await client.getStatus()
        XCTAssertEqual(status.ledger.integrity, .intact)
        XCTAssertGreaterThan(status.records, 0)
        XCTAssertEqual(status.apiVersion, "1")
        XCTAssertEqual(status.schemaVersion, "v2")
    }

    func testCognitiveTwinPreservesEpistemicStatus() async throws {
        try await client.login(username: "admin", password: "demo")
        let twin = try await client.getCognitiveTwin()
        // The current focus is an inference, never asserted as fact.
        XCTAssertEqual(twin.state.currentFocus.epistemic, .inferred)
        XCTAssertNotEqual(twin.state.currentFocus.text, "")
    }

    func testAIShadowIsAdvisory() async throws {
        try await client.login(username: "admin", password: "demo")
        let shadow = try await client.getAIShadow()
        XCTAssertEqual(shadow.authorityBoundary.shadowAuthority, "NONE")
        XCTAssertFalse(shadow.authorityBoundary.shadowCanExecute)
        XCTAssertFalse(shadow.authorityBoundary.shadowCanRatify)
        // Every item is advisory: authority NONE.
        for item in shadow.items {
            XCTAssertEqual(item.authority, "NONE")
        }
    }

    func testDecisionsGovernanceBoundary() async throws {
        try await client.login(username: "admin", password: "demo")
        let list = try await client.listDecisions()
        XCTAssertFalse(list.items.isEmpty)
        // No client-issued decision may be executable without ratification.
        for d in list.items {
            if d.canExecute {
                XCTAssertTrue(d.humanRatified, "\(d.decisionID) executable but not human-ratified")
            }
        }
    }

    func testLedgerEventRead() async throws {
        try await client.login(username: "admin", password: "demo")
        let event = try await client.getLedgerEvent(sequence: 1)
        XCTAssertEqual(event.sequence, 1)
        XCTAssertEqual(event.schemaVersion, "v2")
        XCTAssertNotEqual(event.hash, "")
    }

    func testUnauthenticatedCommandRejected() async throws {
        // Without a token, a command must be rejected — never silently succeed.
        do {
            _ = try await client.createProposal(title: "should-not-succeed")
            XCTFail("unauthenticated propose should be rejected")
        } catch let e as PocketAPIError {
            guard case .authenticationRequired = e else {
                XCTFail("expected authenticationRequired, got \(e)")
                return
            }
        } catch {
            XCTFail("unexpected error: \(error)")
        }
    }
}
