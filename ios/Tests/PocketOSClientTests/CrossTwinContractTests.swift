import XCTest
@testable import PocketOSClient

/// Cognitive Twin cross-client equivalence tests.
///
/// The same canonical Cognitive Twin state (tests_pocketos/fixtures/cognitive_twin_positive.json)
/// must mean the same thing in the Swift client that it does on the web (JS)
/// client: every item carries text + epistemic + confidence + evidence +
/// provenance, and inferences are never collapsed into facts. This decodes the
/// shared fixture through the typed Swift model and asserts those semantics.
final class CrossTwinContractTests: XCTestCase {

    /// The canonical envelope nests the twin under `cognitive_twin` (plus
    /// schema_version/request_id). Unwrap it for direct model decode.
    private struct TwinResponse: Decodable {
        let cognitiveTwin: CognitiveTwin
        enum CodingKeys: String, CodingKey { case cognitiveTwin = "cognitive_twin" }
    }

    private func decodeTwin() throws -> CognitiveTwin {
        let data = try Data(contentsOf: sharedFixtureURL())
        return try JSONDecoder().decode(TwinResponse.self, from: data).cognitiveTwin
    }

    private func sharedFixtureURL() throws -> URL {
        let candidates = [
            URL(fileURLWithPath: "../tests_pocketos/fixtures/cognitive_twin_positive.json"),
            URL(fileURLWithPath: "Tests/fixtures/cognitive_twin_positive.json"),
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c.path) {
            return c
        }
        throw XCTSkip("shared cognitive twin fixture not found on this toolchain")
    }

    private func allItems(from t: CognitiveTwin) -> [CognitiveItem] {
        var out: [CognitiveItem] = []
        out.append(t.state.currentFocus)
        out.append(contentsOf: t.state.openLoops)
        out.append(contentsOf: t.state.closedLoops)
        out.append(contentsOf: t.state.activeProjects)
        out.append(contentsOf: t.relevantMemories)
        out.append(contentsOf: t.recentObservations)
        out.append(contentsOf: t.relationships)
        out.append(contentsOf: t.decisionHistory)
        return out
    }

    func testSharedTwinFixtureDecodesToCanonicalSemantics() throws {
        let t = try decodeTwin()
        XCTAssertFalse(t.summary.isEmpty)
        XCTAssertGreaterThanOrEqual(t.lastUpdateSeq, 0)
        let items = allItems(from: t)
        XCTAssertFalse(items.isEmpty, "twin must contain items")
        for it in items {
            XCTAssertFalse(it.text.isEmpty)
            XCTAssertGreaterThanOrEqual(it.confidence, 0)
            XCTAssertLessThanOrEqual(it.confidence, 1)
            XCTAssertFalse(it.provenance.isEmpty, "provenance must not be empty")
            XCTAssertFalse(it.evidence.isEmpty, "evidence must not be empty")
        }
    }

    func testInferenceNotCollapsedToFact() throws {
        let t = try decodeTwin()
        // The current focus is an inference; the typed model must preserve the
        // INFERRED epistemic status, never a boolean.
        XCTAssertEqual(t.state.currentFocus.epistemic, .inferred)
    }
}
