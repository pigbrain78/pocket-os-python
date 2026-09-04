import XCTest
@testable import PocketOSClient

/// Deterministic tests for the first iPhone Cognitive Twin + AI Shadow
/// projection UI layer. Each projection is driven from the shared golden
/// fixtures (server-authoritative) and asserted to expose UI-ready rows that
/// preserve epistemic status and the advisory boundary — no network required.
final class ProjectionUITests: XCTestCase {

    /// Locate a shared fixture (cwd is ios/ when running swift test, matching
    /// the pattern the other CrossClient test suites use successfully).
    private func fixture(_ name: String) throws -> Data {
        let candidates = [
            URL(fileURLWithPath: "../tests_pocketos/fixtures/\(name)"),
            URL(fileURLWithPath: "Tests/fixtures/\(name)"),
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c.path) {
            return try Data(contentsOf: c)
        }
        throw XCTSkip("fixture \(name) not found on this toolchain")
    }

    private func twin() throws -> CognitiveTwin {
        struct R: Decodable { let cognitiveTwin: CognitiveTwin
            enum CodingKeys: String, CodingKey { case cognitiveTwin = "cognitive_twin" } }
        return try JSONDecoder().decode(R.self, from: fixture("cognitive_twin_positive.json")).cognitiveTwin
    }

    private func shadow() throws -> AIShadow {
        struct R: Decodable { let aiShadow: AIShadow
            enum CodingKeys: String, CodingKey { case aiShadow = "ai_shadow" } }
        return try JSONDecoder().decode(R.self, from: fixture("ai_shadow_positive.json")).aiShadow
    }

    func testTwinProjectionProducesUIRows() throws {
        let proj = PocketTwinProjection(client: PocketOSClient(baseURL: URL(string: "http://127.0.0.1:8787")!))
        proj.apply(try twin())
        XCTAssertTrue(proj.isLoaded)
        XCTAssertFalse(proj.summary.isEmpty)
        XCTAssertEqual(proj.modelVersion, "twin-1.0")
        XCTAssertNotNil(proj.focus)
        XCTAssertEqual(proj.focus?.epistemic, .inferred)
        XCTAssertFalse(proj.allRows().isEmpty)
    }

    func testTwinEpistemicStatusNeverCollapsedToFact() throws {
        let proj = PocketTwinProjection(client: PocketOSClient(baseURL: URL(string: "http://x")!))
        proj.apply(try twin())
        for row in proj.allRows() {
            XCTAssertFalse(row.provenance.isEmpty)
            XCTAssertFalse(row.evidence.isEmpty)
        }
        // A generic boolean "trusted" must not exist on any UI row.
        XCTAssertFalse(Mirror(reflecting: proj.focus!).children.contains { $0.label == "trusted" })
    }

    func testShadowProjectionProducesUIRows() throws {
        let proj = PocketShadowProjection(client: PocketOSClient(baseURL: URL(string: "http://x")!))
        proj.apply(try shadow())
        XCTAssertTrue(proj.isLoaded)
        XCTAssertFalse(proj.items.isEmpty)
        XCTAssertEqual(proj.boundaryAuthority, "NONE")
        XCTAssertFalse(proj.canExecute)
        XCTAssertFalse(proj.canRatify)
        for row in proj.items {
            XCTAssertEqual(row.authority, "NONE", "AI Shadow must be advisory")
            XCTAssertFalse(row.provenance.isEmpty)
        }
    }

    func testShadowRowsGroupByType() throws {
        let proj = PocketShadowProjection(client: PocketOSClient(baseURL: URL(string: "http://x")!))
        proj.apply(try shadow())
        let types = Set(proj.items.map(\.type))
        for t in types {
            XCTAssertFalse(proj.rows(of: t).isEmpty)
        }
    }
}
