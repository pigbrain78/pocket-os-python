// Pocket OS live event spine (SSE) client.
//
// Consumes the server's /api/stream Server-Sent Events stream (observational
// only) and routes normalized observation envelopes into an EventQueue — the
// Swift mirror of the web pocket client's pocket.events.subscribe. Receiving
// an event never implies this client caused it.
//
// Uses the URLSessionDataDelegate streaming path (not URLSession.bytes, which
// is unavailable on Linux FoundationNetworking) so it works on both Apple
// platforms and Linux.

import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum StreamStatus: String, Sendable {
    case idle
    case connecting
    case live
    case reconnecting
    case closed
    case unsupported
}

/// A thread-hopping NSObject that relays URLSession data/error callbacks onto
/// the actor as Swift concurrency tasks. Retained by URLSession for the life
/// of the task. Only accessed from the URLSession delegate queue, so
/// @unchecked Sendable is safe here.
private final class SSEBridge: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    var onChunk: ((Data) -> Void)?
    var onClosed: ((Error?) -> Void)?

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        onChunk?(data)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        onClosed?(error)
    }
}

/// Handles a raw SSE connection and parses `hello` / `event` / keepalive frames.
public actor PocketSSEClient {
    private let baseURL: URL
    private let queue: EventQueue
    private var session: URLSession?
    private var dataTask: URLSessionDataTask?
    private var buffer = Data()
    private var status: StreamStatus = .idle
    private var statusObservers: [(StreamStatus) -> Void] = []
    /// True once we've seen the hello frame (authoritative connected state).
    private var sawHello = false

    public init(baseURL: URL, queue: EventQueue) {
        self.baseURL = baseURL
        self.queue = queue
    }

    /// Raw `event:`/`data:` SSE frame parsed from the wire.
    struct Frame {
        var event: String = ""
        var data: String = ""
    }

    public func currentStatus() -> StreamStatus { status }
    public func onStatus(_ fn: @escaping (StreamStatus) -> Void) { statusObservers.append(fn) }

    private func setStatus(_ s: StreamStatus) {
        status = s
        for fn in statusObservers { fn(s) }
    }

    /// Open the stream and start parsing. Idempotent; already-live is a no-op.
    public func connect() {
        guard dataTask == nil else { return }
        setStatus(.connecting)
        sawHello = false
        buffer = Data()

        let url = baseURL.appendingPathComponent("api/stream")
        var req = URLRequest(url: url)
        req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        req.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        req.timeoutInterval = .infinity

        let bridge = SSEBridge()
        bridge.onChunk = { [weak self] data in
            Task { [weak self] in await self?.consume(data) }
        }
        bridge.onClosed = { [weak self] _ in
            Task { [weak self] in await self?.handleDisconnect() }
        }

        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = .infinity
        config.timeoutIntervalForResource = .infinity
        let session = URLSession(configuration: config, delegate: bridge, delegateQueue: nil)
        let task = session.dataTask(with: req)
        self.session = session
        dataTask = task
        task.resume()
    }

    public func disconnect() {
        dataTask?.cancel()
        dataTask = nil
        session?.invalidateAndCancel()
        session = nil
        setStatus(.closed)
    }

    /// Append a chunk and drain any complete SSE frames.
    private func consume(_ chunk: Data) {
        buffer.append(chunk)
        while let range = buffer.range(of: Data("\n\n".utf8)) {
            let frameData = buffer.subdata(in: buffer.startIndex..<range.lowerBound)
            buffer.removeSubrange(buffer.startIndex..<range.upperBound)
            handle(parse(frameData))
        }
    }

    private func handleDisconnect() {
        // Intentional close already handled; else reconnect after a backoff.
        guard status != .closed else { return }
        dataTask = nil
        session = nil
        setStatus(.reconnecting)
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            guard let self else { return }
            guard await self.status != .closed else { return }
            await self.connect()
        }
    }

    /// Parse one raw frame body into event/data lines.
    func parse(_ data: Data) -> Frame {
        guard let text = String(data: data, encoding: .utf8) else { return Frame() }
        var f = Frame()
        for line in text.components(separatedBy: "\n") {
            if line.hasPrefix(":") { continue } // comment / keepalive
            if line.hasPrefix("event:") {
                f.event = String(line.dropFirst("event:".count)).trimmingCharacters(in: .whitespaces)
            } else if line.hasPrefix("data:") {
                let d = String(line.dropFirst("data:".count)).trimmingCharacters(in: .whitespaces)
                f.data = f.data.isEmpty ? d : f.data + "\n" + d
            }
        }
        return f
    }

    /// Deliver a fully-formed raw frame body to the queue (test seam; the live
    /// path parses each buffered \n\n-delimited frame and calls this).
    func ingest(_ frameData: Data) {
        handle(parse(frameData))
    }

    private func handle(_ f: Frame) {
        if f.event == "hello" {
            sawHello = true
            setStatus(.live)  // server sent initial revision — we are connected
        } else if f.event == "event", !f.data.isEmpty, let data = f.data.data(using: .utf8) {
            do {
                let envelope = try JSONDecoder().decode(EventEnvelope.self, from: data)
                queue.deliver(envelope)
            } catch {
                // Malformed frame: drop silently — never fabricate an event.
            }
        }
    }
}
