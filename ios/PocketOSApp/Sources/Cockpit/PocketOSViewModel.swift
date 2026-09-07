// PocketOSViewModel.swift
// ViewModel layer. Coordinates presentation of canonical projections; holds no
// Pocket OS business logic and grants no authority. Transport is PocketOSClient.

import Foundation
import SwiftUI
import PocketOSKit

@MainActor
public final class PocketOSViewModel: ObservableObject {
    @Published public var twin: CognitiveTwinProjection?
    @Published public var shadow: ShadowProjection?
    @Published public var decisions: [PocketDecision] = []
    @Published public var state: PocketStateProjection?
    @Published public var session: PocketSession?
    @Published public var streamStatus: String = "off"
    @Published public var loadError: String?

    public let client: PocketOSClient
    private var streamTask: Task<Void, Never>?

    public init(baseURL: URL, client: PocketOSClient? = nil) {
        self.client = client ?? PocketOSClient(baseURL: baseURL)
    }

    /// Load the canonical projections the cockpit shows.
    public func loadAll() async {
        do {
            // Reading the Twin/Shadow/decisions requires no session for the
            // read endpoints in this build; load what is reachable.
            async let t = try? client.fetchTwin()
            async let s = try? client.fetchShadow()
            async let d = try? client.fetchDecisions()
            async let st = try? client.fetchState()
            let results = await (t, s, d, st)
            if let twin = results.0 { self.twin = twin }
            if let shadow = results.1 { self.shadow = shadow }
            if let decisions = results.2 { self.decisions = decisions }
            if let state = results.3 { self.state = state }
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    public func signIn(username: String, password: String) async {
        do {
            session = try await client.login(username: username, password: password)
            loadError = nil
        } catch {
            loadError = "Sign-in failed."
        }
    }

    public func signOut() async {
        await client.logout()
        session = nil
        twin = nil; shadow = nil; decisions = []; state = nil
    }

    /// Begin consuming the live event stream. A received event is an
    /// OBSERVATION that triggers a canonical refetch — never treated as proof
    /// this client caused the mutation.
    public func startStream() {
        stopStream()
        streamStatus = "connecting"
        streamTask = Task { [weak self] in
            guard let self else { return }
            await self.runStream()
        }
    }

    private func runStream() async {
        // The Linux build has no native SSE parser; production iOS uses the
        // Apple-gated PocketEventStream (PocketOSApp target). Here we drive the
        // same observable contract: reconnect → resync → resume. We keep a
        // lightweight periodic reconciliation for preview correctness and note
        // the full SSE client in the Apple app target.
        streamStatus = "live"
        while !Task.isCancelled {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            await loadAll()
        }
    }

    public func stopStream() {
        streamTask?.cancel()
        streamTask = nil
        streamStatus = "off"
    }
}
