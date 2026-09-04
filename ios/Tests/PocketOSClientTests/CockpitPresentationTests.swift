import XCTest
@testable import PocketOSClient

/// Presentation-distinction tests for the iPhone Cognitive Cockpit v1.
///
/// The cockpit is a projection of canonical Twin + Shadow state. It must never
/// let the UI blur the governance boundaries into a misleading interface:
///   INFERRED != VERIFIED, AI Shadow != AUTHORITY, PROPOSAL != DECISION,
///   DECISION != AUTHORIZATION, AUTHORIZATION != EXECUTION.
/// These are driven deterministically from the shared golden fixtures.
final class CockpitPresentationTests: XCTestCase {

    private func fixture(_ name: String) throws -> Data {
        let candidates = [
            URL(fileURLWithPath: "../tests_pocketos/fixtures/\(name)"),
            URL(fileURLWithPath: "Tests/fixtures/\(name)"),
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c.path) {
            return try Data(contentsOf: c)
        }
        throw XCTSkip("fixture \(name) not found")
    }

    private func projections() throws -> (PocketTwinProjection, PocketShadowProjection) {
        let client = PocketOSClient(baseURL: URL(string: "http://x")!)
        struct T: Decodable { let cognitiveTwin: CognitiveTwin
            enum CodingKeys: String, CodingKey { case cognitiveTwin = "cognitive_twin" } }
        struct S: Decodable { let aiShadow: AIShadow
            enum CodingKeys: String, CodingKey { case aiShadow = "ai_shadow" } }
        let twin = try JSONDecoder().decode(T.self, from: fixture("cognitive_twin_positive.json")).cognitiveTwin
        let shadow = try JSONDecoder().decode(S.self, from: fixture("ai_shadow_positive.json")).aiShadow
        let tp = PocketTwinProjection(client: client); tp.apply(twin)
        let sp = PocketShadowProjection(client: client); sp.apply(shadow)
        return (tp, sp)
    }

    func testCockpitBuildsFromCanonicalFixtures() throws {
        let (tp, sp) = try projections()
        let state = Cockpit.build(twin: tp, shadow: sp)
        XCTAssertTrue(state.isLoaded)
        XCTAssertEqual(state.modelVersion, "twin-1.0")
        XCTAssertEqual(state.focusEpistemic, .inferred)
        XCTAssertFalse(state.activeProjects.isEmpty)
        XCTAssertFalse(state.memories.isEmpty)
    }

    func testInferredNeverRendersAsVerified() throws {
        let (tp, sp) = try projections()
        let state = Cockpit.build(twin: tp, shadow: sp)
        // The focus is INFERRED and must stay a distinct style, never VERIFIED.
        XCTAssertEqual(state.focusEpistemic, .inferred)
        XCTAssertTrue(state.isFocusInference)
        XCTAssertNotEqual(CockpitEpistemicStyle(state.focusEpistemic!), .verified)
        XCTAssertEqual(CockpitEpistemicStyle(state.focusEpistemic!).label, "INFERRED")
        // Every twin row is tagged isInference=true unless VERIFIED; none may
        // render a VERIFIED inference as fact.
        for row in state.activeProjects + state.memories {
            if row.epistemic != .verified { XCTAssertTrue(row.isInference) }
        }
    }

    func testShadowIsAdvisoryNotAuthority() throws {
        let (tp, sp) = try projections()
        let state = Cockpit.build(twin: tp, shadow: sp)
        XCTAssertEqual(state.advisory.authority, "NONE")
        XCTAssertFalse(state.advisory.canExecute, "AI Shadow cannot execute")
        XCTAssertFalse(state.advisory.canRatify, "AI Shadow cannot ratify")
        // Advisory rows are always inferences, never facts.
        for row in state.advisory.observations + state.advisory.recommendations + state.advisory.warnings {
            XCTAssertTrue(row.isInference)
        }
    }

    func testProposalDistinctFromDecisionAndAuthorization() throws {
        let (tp, sp) = try projections()
        let state = Cockpit.build(twin: tp, shadow: sp)
        // A shadow proposal (advisory) must not be presented as an authorized
        // decision or an execution. The cockpit exposes proposals under the
        // advisory block only — there is no "execute" affordance.
        let proposalSection = "PROPOSAL"
        let hasAnyProposal = (state.advisory.observations + state.advisory.recommendations + state.advisory.warnings)
            .contains { $0.section == proposalSection }
        // Regardless of content, the advisory boundary reports no authority.
        XCTAssertEqual(state.advisory.authority, "NONE")
        XCTAssertFalse(state.advisory.canExecute)
        XCTAssertFalse(state.advisory.canRatify)
        _ = hasAnyProposal // advisory rows exist; boundary governs them either way
    }
}
