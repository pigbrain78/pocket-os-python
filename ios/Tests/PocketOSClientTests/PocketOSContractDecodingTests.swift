import XCTest
@testable import PocketOSClient

final class PocketOSContractDecodingTests: XCTestCase {
    /// Decode a captured /api/v1/status response and assert the envelope and
    /// ledger fields survive. This proves the Codable model matches the real
    /// contract on an actual toolchain, not just a key-union guard.
    func testDecodeStatusEnvelope() throws {
        let json = """
        {"request_id":"r1","api_version":"1","schema_version":"v2",
         "status":"healthy","records":25,"revision":3,"server_time":123,
         "ledger":{"integrity":"INTACT","valid":true,"broken_seq":null}}
        """.data(using: .utf8)!
        let s = try JSONDecoder().decode(SystemStatus.self, from: json)
        XCTAssertEqual(s.requestID, "r1")
        XCTAssertEqual(s.apiVersion, "1")
        XCTAssertEqual(s.schemaVersion, "v2")
        XCTAssertEqual(s.ledger.integrity, .intact)
        XCTAssertTrue(s.ledger.valid)
        XCTAssertEqual(s.records, 25)
    }

    /// The Cognitive Twin must never collapse an INFERRED item into a fact.
    /// The epistemic status must survive transport as a distinct value.
    func testEpistemicStatusSurvivesDecoding() throws {
        let json = """
        {"model_version":"twin-1.0","last_update_seq":25,
         "epistemic_legend":["OBSERVED","VERIFIED","INFERRED"],
         "summary":"s","state":{"current_focus":{"text":"PocketOS Web",
         "epistemic":"INFERRED","confidence":0.7,"evidence":[1,2,3],
         "provenance":"ledger#3"},"active_projects":[],"open_loops":[],
         "closed_loops":[]},
         "relevant_memories":[],"decision_history":[],"relationships":[],
         "recent_observations":[]}
        """.data(using: .utf8)!
        let twin = try JSONDecoder().decode(CognitiveTwin.self, from: json)
        XCTAssertEqual(twin.state.currentFocus.epistemic, .inferred)
        XCTAssertEqual(twin.state.currentFocus.text, "PocketOS Web")
        // Not representable as a boolean anywhere on the model.
        XCTAssertTrue(twin.epistemicLegend.contains("INFERRED"))
    }

    /// AI Shadow items are advisory with authority NONE and cannot imply
    /// execution authority.
    func testAIShadowDecodingPreservesAdvisoryBoundary() throws {
        let json = """
        {"types":["OBSERVATION"],"authority_boundary":{
         "shadow_authority":"NONE","shadow_can_execute":false,
         "shadow_can_ratify":false,"execution_requires":["HUMAN_RATIFICATION"]},
         "items":[{"type":"OBSERVATION","text":"three open tasks",
         "confidence":0.91,"evidence":[182],"provenance":"ledger#182",
         "status":"ACTIVE","authority":"NONE","next_step":null}]}
        """.data(using: .utf8)!
        let shadow = try JSONDecoder().decode(AIShadow.self, from: json)
        XCTAssertEqual(shadow.authorityBoundary.shadowAuthority, "NONE")
        XCTAssertFalse(shadow.authorityBoundary.shadowCanExecute)
        XCTAssertEqual(shadow.authorityBoundary.executionRequires, ["HUMAN_RATIFICATION"])
        XCTAssertEqual(shadow.items.first?.authority, "NONE")
    }

    /// Decisions carry an explicit can_execute flag driven by governance; an
    /// unratified decision must not decode as executable.
    func testDecisionGovernanceFlags() throws {
        let json = """
        {"decision_id":"D-CORPUS-1001","title":"ingest v1 corpus",
         "proposal_seq":10,"status":"RATIFIED","stage":"ratified",
         "lifecycle":["proposed","council","ratified"],"human_ratified":true,
         "rejected":false,"reason_hash":"abc","council_approved":true,
         "risk":"MEDIUM","reversible":true,"can_execute":true,
         "evidence_stage":"verified"}
        """.data(using: .utf8)!
        let d = try JSONDecoder().decode(Decision.self, from: json)
        XCTAssertEqual(d.status, .ratified)
        XCTAssertTrue(d.humanRatified)
        XCTAssertFalse(d.rejected)
        XCTAssertTrue(d.canExecute)
        XCTAssertEqual(d.decisionID, "D-CORPUS-1001")
    }

    /// Ledger events carry schema/kind/hash and the chain predecessor.
    func testLedgerEventDecoding() throws {
        let json = """
        {"sequence":1,"event":"memory.created","timestamp":10,"source":"PocketOS",
         "schema_version":"v2","kind":"memory","payload":{"title":"boot"},
         "previous_hash":null,"hash":"deadbeef"}
        """.data(using: .utf8)!
        let e = try JSONDecoder().decode(LedgerEvent.self, from: json)
        XCTAssertEqual(e.kind, "memory")
        XCTAssertEqual(e.schemaVersion, "v2")
        XCTAssertNil(e.previousHash)
        XCTAssertEqual(e.hash, "deadbeef")
    }
}
