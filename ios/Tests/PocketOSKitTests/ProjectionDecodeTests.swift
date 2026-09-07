import XCTest
@testable import PocketOSKit

/// Tests that decode the REAL canonical API fixtures captured from the running
/// Pocket OS backend, proving the iPhone models mirror the wire contract.
final class ProjectionDecodeTests: XCTestCase {

    private func load(_ name: String) throws -> Data {
        let url = try XCTUnwrap(
            Bundle.module.url(forResource: name, withExtension: "json"),
            "missing fixture \(name).json"
        )
        return try Data(contentsOf: url)
    }

    func testTwinProjectionDecodesAndCarriesEpistemicStates() throws {
        let data = try load("twin")
        let resp = try JSONDecoder().decode(TwinResponse.self, from: data)
        XCTAssertEqual(resp.integrity, "INTACT")
        let twin = try XCTUnwrap(resp.cognitiveTwin)
        XCTAssertEqual(twin.modelVersion, "twin-1.0")
        XCTAssertEqual(twin.lastUpdateSeq, 25)
        // Canonical epistemic legend is present and matches the backend.
        XCTAssertEqual(twin.epistemicLegend, [.observed, .verified, .inferred,
                                              .uncertain, .rejected, .stale])
        // Current focus is an INFERENCE, never presented as authoritative.
        let focus = try XCTUnwrap(twin.state.currentFocus)
        XCTAssertEqual(focus.epistemic, .inferred)
        XCTAssertFalse(focus.epistemic?.isAuthoritative ?? true)
        XCTAssertGreaterThan(focus.confidence ?? 0, 0)
        XCTAssertFalse(focus.evidence.isEmpty)
        XCTAssertTrue(focus.provenance.hasPrefix("ledger#"))
        // Open loops are OBSERVED facts carrying provenance.
        XCTAssertFalse(twin.state.openLoops.isEmpty)
        XCTAssertEqual(twin.state.openLoops.first?.epistemic, .observed)
    }

    func testShadowProjectionDecodesAndCarriesExplicitAuthorityBoundary() throws {
        let data = try load("shadow")
        let resp = try JSONDecoder().decode(ShadowResponse.self, from: data)
        XCTAssertEqual(resp.integrity, "INTACT")
        let shadow = try XCTUnwrap(resp.aiShadow)
        XCTAssertFalse(shadow.items.isEmpty)
        // Authority boundary: the Shadow is advisory with NO authority.
        XCTAssertFalse(shadow.authorityBoundary.canExecute)
        XCTAssertFalse(shadow.authorityBoundary.canRatify)
        XCTAssertEqual(shadow.authorityBoundary.authority, "NONE")
        XCTAssertEqual(shadow.authorityLabel, "AUTHORITY NONE")
        // Every item is advisory.
        for item in shadow.items {
            XCTAssertEqual(item.authority ?? "NONE", "NONE", "item must carry authority NONE")
        }
        // Execution requires the constitutional path, never the Shadow alone.
        XCTAssertFalse(shadow.authorityBoundary.executionRequires.isEmpty)
    }

    func testDecisionsProjectionDecodesGovernanceStatuses() throws {
        let data = try load("decisions")
        let resp = try JSONDecoder().decode(DecisionsResponse.self, from: data)
        XCTAssertEqual(resp.integrity, "INTACT")
        XCTAssertEqual(resp.decisions.count, 3)
        let byID = Dictionary(uniqueKeysWithValues: resp.decisions.map { ($0.decisionId, $0) })

        let corpus = try XCTUnwrap(byID["D-CORPUS-1001"])
        XCTAssertEqual(corpus.status, .ratified)
        XCTAssertTrue(corpus.humanRatified)
        XCTAssertTrue(corpus.canExecute)
        // A ratified decision still must not be conflated with an executed one.
        XCTAssertNotEqual(corpus.status, .executed)

        let metrics = try XCTUnwrap(byID["D-METRICS-1002"])
        XCTAssertEqual(metrics.status, .rejected)
        XCTAssertTrue(metrics.rejected)
        XCTAssertFalse(metrics.canExecute)

        let workspace = try XCTUnwrap(byID["D-WORKSPACE-1003"])
        XCTAssertEqual(workspace.status, .pending)
        XCTAssertFalse(workspace.humanRatified)
        XCTAssertFalse(workspace.canExecute)
    }

    func testStateProjectionDecodesLedgerWithHashChain() throws {
        let data = try load("state")
        let state = try JSONDecoder().decode(PocketStateProjection.self, from: data)
        XCTAssertEqual(state.integrity, "INTACT")
        XCTAssertTrue(state.valid)
        XCTAssertEqual(state.recordCount, state.records.count)
        XCTAssertEqual(state.records.count, 25)
        XCTAssertGreaterThan(state.revision, 0)
        // Ledger records carry sequence + previous_hash chain.
        XCTAssertEqual(state.records.first?.sequence, 1)
        XCTAssertNil(state.records.first?.previousHash) // genesis
        for i in 1..<state.records.count {
            let prev = state.records[i - 1]
            let cur = state.records[i]
            XCTAssertEqual(cur.previousHash, prev.hash, "record #\(cur.sequence) chain broken")
        }
        XCTAssertFalse(state.records[0].hash.isEmpty)
    }

    func testHealthProjection() throws {
        let data = try load("health")
        // /api/health is a small payload (status + integrity + record count),
        // not the full state projection — assert its JSON-level contract only.
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(obj["status"] as? String, "healthy")
        XCTAssertEqual(obj["integrity"] as? String, "INTACT")
        XCTAssertEqual(obj["records"] as? Int, 25)
    }
}
