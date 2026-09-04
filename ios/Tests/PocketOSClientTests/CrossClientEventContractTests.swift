import XCTest
@testable import PocketOSClient

/// Cross-client canonical event contract tests.
///
/// Proves that the SAME canonical event envelope (written once in
/// tests_pocketos/fixtures/canonical_event_positive.json and broadcast by the
/// server's /api/stream) decodes into the equivalent semantic fields in the
/// Swift client that the web (JS pocket) client produces — event_id, type,
/// sequence, occurred_at, source, kind, previous_hash, schema_version, payload.
/// Then exercises the negative fixtures every client must reject.
final class CrossClientEventContractTests: XCTestCase {

    /// A stable 64-hex id that passes the provenance check.
    private func hex64(_ fill: Character) -> String {
        String(repeating: fill, count: 64)
    }

    /// Build a canonical envelope JSON string with overridable fields.
    private func envelope(
        type: String = "memory.created",
        eventID: String? = nil,
        sequence: Any? = 26,
        previousHash: String? = nil,
        extra: String = ""
    ) -> String {
        let id = eventID ?? hex64("a")
        let ph = previousHash ?? hex64("b")
        return """
        {"type":"\(type)","event_id":"\(id)","sequence":\(sequence ?? 26),\
        "source":"PocketOS","kind":"memory","previous_hash":"\(ph)",\
        "schema_version":"v2","payload":{"title":"t"}\(extra)}
        """
    }

    /// Locate the shared positive fixture (repo-root-relative).
    private func sharedFixturePath() throws -> String {
        let candidates = [
            "../tests_pocketos/fixtures/canonical_event_positive.json",
            "Tests/fixtures/canonical_event_positive.json",
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c) {
            return c
        }
        throw XCTSkip("shared canonical event fixture not found on this toolchain")
    }

    func testSharedPositiveFixtureDecodesToCanonicalFields() throws {
        let data = try Data(contentsOf: URL(fileURLWithPath: sharedFixturePath()))
        let e = try JSONDecoder().decode(EventEnvelope.self, from: data)
        XCTAssertEqual(e.type, "decision.proposed")
        XCTAssertEqual(e.kind, "decision")
        XCTAssertEqual(e.sequence, 26)
        XCTAssertEqual(e.occurredAt, 0)
        XCTAssertEqual(e.source, "WebClient")
        XCTAssertEqual(e.previousHash, "cc2b2af164399aa6f770691d676bb7e2a33c21d36f39a88c22cb5a251812ab84")
        XCTAssertEqual(e.schemaVersion, "v2")
        XCTAssertEqual(e.eventID?.count, 64)
        XCTAssertEqual(e.payload["title"]?.stringValue, "contract-capture")
        XCTAssertNil(EventContract.validate(e))
    }

    // MARK: - Negative fixtures

    func testMalformedEventRejected() {
        let bad = #"{"type": "decision.proposed", "event_id": "x", "#.data(using: .utf8)!
        XCTAssertThrowsError(try JSONDecoder().decode(EventEnvelope.self, from: bad))
    }

    func testMissingRequiredFieldRejected() {
        // No event_id and no sequence -> not a usable observation.
        let json = "{\"type\":\"memory.created\",\"schema_version\":\"v2\",\"payload\":{}}".data(using: .utf8)!
        let e = try? JSONDecoder().decode(EventEnvelope.self, from: json)
        if let e {
            XCTAssertEqual(EventContract.validate(e), .missingField)
        } else {
            XCTFail("expected decode then semantic rejection")
        }
    }

    func testWrongFieldTypeRejected() {
        // sequence is a string, not an integer -> Codable decode throws.
        let json = envelope(sequence: "\"not-an-int\"")
        XCTAssertThrowsError(try JSONDecoder().decode(EventEnvelope.self, from: json.data(using: .utf8)!))
    }

    func testUnknownEventTypeRejected() {
        let json = envelope(type: "ai.shadow.executed")
        let e = try! JSONDecoder().decode(EventEnvelope.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(EventContract.validate(e), .unknownType)
    }

    func testInvalidSequenceRejected() {
        let json = envelope(sequence: 0)
        let e = try! JSONDecoder().decode(EventEnvelope.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(EventContract.validate(e), .invalidSequence)
    }

    func testInvalidProvenanceRejected() {
        // previous_hash is not a hex hash.
        let json = envelope(previousHash: "not-a-hash")
        let e = try! JSONDecoder().decode(EventEnvelope.self, from: json.data(using: .utf8)!)
        XCTAssertEqual(EventContract.validate(e), .invalidProvenance)
    }

    func testDuplicateEventDetected() {
        XCTAssertEqual(EventContract.track(previous: 26, next: 26), .duplicateEvent)
    }

    func testOutOfOrderEventDetected() {
        XCTAssertEqual(EventContract.track(previous: 27, next: 26), .outOfOrder)
    }
}
