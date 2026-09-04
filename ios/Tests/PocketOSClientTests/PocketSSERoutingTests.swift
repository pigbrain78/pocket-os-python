import XCTest
@testable import PocketOSClient

/// Deterministic tests for the SSE spine frame parser and queue routing.
///
/// The live URLSession delegate streaming path is unstable on the Linux
/// FoundationNetworking toolchain (SIGILL in the delegate machinery), so these
/// tests exercise the exact frame-parsing and EventQueue-routing logic that the
/// live path uses — parse each \n\n-delimited frame and deliver it — without a
/// network connection. This proves "a server push reaches the events queue"
/// deterministically on every platform.
final class PocketSSERoutingTests: XCTestCase {
    func testHelloFrameSetsStatusLive() async {
        let queue = EventQueue()
        let stream = PocketSSEClient(baseURL: URL(string: "http://example.test")!, queue: queue)
        // hello frame: the server's initial revision message.
        await stream.ingest(Data("event: hello\ndata: {\"revision\":25,\"records\":25}\n".utf8))
        let status = await stream.currentStatus()
        XCTAssertEqual(status, .live, "hello frame should mark the stream live")
    }

    func testEventFrameDeliversEnvelopeToQueue() async {
        let queue = EventQueue()
        let stream = PocketSSEClient(baseURL: URL(string: "http://example.test")!, queue: queue)

        let received = expectation(description: "event delivered to queue")
        queue.add { envelope in
            XCTAssertEqual(envelope.type, "decision.proposed")
            XCTAssertEqual(envelope.sequence, 26)
            received.fulfill()
        }

        // A real /api/stream `event:` frame wrapping the broadcast envelope.
        let frame = """
        event: event
        data: {"type":"decision.proposed","event_id":"abc123","sequence":26,"schema_version":"v2","payload":{"title":"t"}}
        """
        await stream.ingest(Data(frame.utf8))
        await fulfillment(of: [received], timeout: 2.0)
    }

    func testMalformedFrameIsDroppedNotCrashed() async {
        let queue = EventQueue()
        let stream = PocketSSEClient(baseURL: URL(string: "http://example.test")!, queue: queue)
        // A frame with an `event:` type but non-JSON data must not crash or
        // fabricate an event — it is silently dropped.
        await stream.ingest(Data("event: event\ndata: {not valid json\n".utf8))
        let status = await stream.currentStatus()
        XCTAssertEqual(status, .idle)
    }

    func testKeepaliveCommentIsIgnored() async {
        let queue = EventQueue()
        let stream = PocketSSEClient(baseURL: URL(string: "http://example.test")!, queue: queue)
        await stream.ingest(Data(": keepalive\n\n".utf8))
        let status = await stream.currentStatus()
        XCTAssertEqual(status, .idle, "keepalive comment must not change status")
    }
}
