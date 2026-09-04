import XCTest
@testable import PocketOSClient

/// AI Shadow cross-client equivalence tests.
///
/// The same canonical AI Shadow state (tests_pocketos/fixtures/ai_shadow_positive.json)
/// must mean the same thing in the Swift client that it does on the web (JS)
/// client: each item carries type + text + confidence + evidence + provenance +
/// authority, the AI Shadow is advisory (authority NONE, cannot execute/ratify),
/// and observations are never treated as authority.
final class CrossShadowContractTests: XCTestCase {

    /// The canonical envelope nests the shadow under `ai_shadow`.
    private struct ShadowResponse: Decodable {
        let aiShadow: AIShadow
        enum CodingKeys: String, CodingKey { case aiShadow = "ai_shadow" }
    }

    private func sharedFixtureURL() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: "../tests_pocketos/fixtures/ai_shadow_positive.json"),
            URL(fileURLWithPath: "Tests/fixtures/ai_shadow_positive.json"),
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c.path) {
            return c
        }
        throw XCTSkip("shared AI Shadow fixture not found on this toolchain")
    }

    func testSharedShadowFixtureDecodesToCanonicalSemantics() throws {
        let data = try Data(contentsOf: sharedFixtureURL())
        let resp = try JSONDecoder().decode(ShadowResponse.self, from: data)
        let shadow = resp.aiShadow
        XCTAssertFalse(shadow.items.isEmpty)
        XCTAssertEqual(shadow.types.count, 7)
        for it in shadow.items {
            XCTAssertFalse(it.text.isEmpty)
            XCTAssertGreaterThanOrEqual(it.confidence, 0)
            XCTAssertLessThanOrEqual(it.confidence, 1)
            XCTAssertFalse(it.provenance.isEmpty, "provenance must not be empty")
            XCTAssertFalse(it.evidence.isEmpty, "evidence must not be empty")
            XCTAssertEqual(it.authority, "NONE", "AI Shadow must be advisory")
        }
    }

    func testShadowCannotExecuteOrRatify() throws {
        let data = try Data(contentsOf: sharedFixtureURL())
        let resp = try JSONDecoder().decode(ShadowResponse.self, from: data)
        let b = resp.aiShadow.authorityBoundary
        XCTAssertEqual(b.shadowAuthority, "NONE")
        XCTAssertFalse(b.shadowCanExecute)
        XCTAssertFalse(b.shadowCanRatify)
        XCTAssertTrue(b.executionRequires.contains("COUNCIL_CONSENSUS"))
        XCTAssertTrue(b.executionRequires.contains("HUMAN_RATIFICATION"))
    }

    func testShadowObservationNeverCollapsedToAuthority() throws {
        let data = try Data(contentsOf: sharedFixtureURL())
        let resp = try JSONDecoder().decode(ShadowResponse.self, from: data)
        for it in resp.aiShadow.items {
            // Advisory only: an item carries authority == NONE by model
            // contract; there is no field granting execution.
            XCTAssertEqual(it.authority, "NONE")
        }
    }
}
