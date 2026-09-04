// PocketOSClient Projection.swift
//
// First iPhone Cognitive Twin + AI Shadow projection layer. The iPhone is a
// CLIENT of the canonical Pocket OS core — it never holds authoritative state.
// These projections expose UI-ready, observable views of the canonical Twin
// and AI Shadow, refreshed from the server and reconciled on live (SSE) events
// by refetching the authoritative projection (never trusting a push as the
// client's own action).
import Foundation

public enum PocketProjectionError: Error, Sendable {
    case notLoaded
    case network(underlying: Error)
}

/// A single UI-ready row in the Cognitive Twin projection. Epistemic status is
/// preserved verbatim — an inference is never rendered as a fact.
public struct TwinRow: Identifiable, Sendable, Equatable {
    public let id: String
    public let section: String
    public let text: String
    public let epistemic: EpistemicStatus
    public let confidence: Double
    public let evidence: [Int]
    public let provenance: String
}

/// A single UI-ready AI Shadow observation. Advisory: authority is always NONE.
public struct ShadowRow: Identifiable, Sendable, Equatable {
    public let id: String
    public let type: AIShadowType
    public let text: String
    public let confidence: Double
    public let evidence: [Int]
    public let provenance: String
    public let status: String
    public let nextStep: String?
    /// Always "NONE" by the constitutional boundary — the AI Shadow advises.
    public let authority: String
}

/// UI-ready Cognitive Twin projection.
public final class PocketTwinProjection: @unchecked Sendable {
    public private(set) var focus: TwinRow?
    public private(set) var openLoops: [TwinRow] = []
    public private(set) var activeProjects: [TwinRow] = []
    public private(set) var memories: [TwinRow] = []
    public private(set) var observations: [TwinRow] = []
    public private(set) var summary: String = ""
    public private(set) var modelVersion: String = ""
    public private(set) var lastUpdateSeq: Int = 0
    public private(set) var isLoaded = false

    private let client: PocketOSClient
    private var observer: (() -> Void)?

    public init(client: PocketOSClient) {
        self.client = client
    }

    /// Register a callback fired whenever the projection changes.
    @discardableResult
    public func onChange(_ handler: @escaping () -> Void) -> UUID {
        observer = handler
        return UUID()
    }

    /// Refresh the authoritative Twin from /api/v1/cognitive-twin.
    public func refresh() async throws {
        let t: CognitiveTwin
        do { t = try await client.getCognitiveTwin() }
        catch { throw PocketProjectionError.network(underlying: error) }
        apply(t)
    }

    func apply(_ t: CognitiveTwin) {  // internal: @testable fixture injection
        summary = t.summary
        modelVersion = t.modelVersion
        lastUpdateSeq = t.lastUpdateSeq
        focus = TwinRow(id: "focus", section: "Focus", text: t.state.currentFocus.text,
                        epistemic: t.state.currentFocus.epistemic, confidence: t.state.currentFocus.confidence,
                        evidence: t.state.currentFocus.evidence, provenance: t.state.currentFocus.provenance)
        openLoops = t.state.openLoops.map { TwinRow(id: "loop-\($0.provenance)", section: "Open loops", text: $0.text, epistemic: $0.epistemic, confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance) }
        activeProjects = t.state.activeProjects.map { TwinRow(id: "proj-\($0.provenance)", section: "Projects", text: $0.text, epistemic: $0.epistemic, confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance) }
        memories = t.relevantMemories.map { TwinRow(id: "mem-\($0.provenance)", section: "Memory", text: $0.text, epistemic: $0.epistemic, confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance) }
        observations = t.recentObservations.map { TwinRow(id: "obs-\($0.provenance)", section: "Observed", text: $0.text, epistemic: $0.epistemic, confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance) }
        isLoaded = true
        observer?()
    }

    /// All rows across sections, for a list UI.
    public func allRows() -> [TwinRow] {
        var out: [TwinRow] = []
        if let focus { out.append(focus) }
        out.append(contentsOf: openLoops)
        out.append(contentsOf: activeProjects)
        out.append(contentsOf: memories)
        out.append(contentsOf: observations)
        return out
    }
}

/// UI-ready AI Shadow projection.
public final class PocketShadowProjection: @unchecked Sendable {
    public private(set) var items: [ShadowRow] = []
    public private(set) var types: [String] = []
    public private(set) var boundaryAuthority: String = ""
    public private(set) var canExecute: Bool = false
    public private(set) var canRatify: Bool = false
    public private(set) var isLoaded = false

    private let client: PocketOSClient
    private var observer: (() -> Void)?

    public init(client: PocketOSClient) {
        self.client = client
    }

    @discardableResult
    public func onChange(_ handler: @escaping () -> Void) -> UUID {
        observer = handler
        return UUID()
    }

    /// Refresh the authoritative AI Shadow from /api/v1/ai-shadow.
    public func refresh() async throws {
        let s: AIShadow
        do { s = try await client.getAIShadow() }
        catch { throw PocketProjectionError.network(underlying: error) }
        apply(s)
    }

    func apply(_ s: AIShadow) {  // internal: @testable fixture injection
        types = s.types
        boundaryAuthority = s.authorityBoundary.shadowAuthority
        canExecute = s.authorityBoundary.shadowCanExecute
        canRatify = s.authorityBoundary.shadowCanRatify
        items = s.items.map {
            ShadowRow(id: "shadow-\($0.provenance)", type: $0.type, text: $0.text,
                      confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance,
                      status: $0.status, nextStep: $0.nextStep, authority: $0.authority)
        }
        isLoaded = true
        observer?()
    }

    /// Advisory rows grouped for display.
    public func rows(of type: AIShadowType) -> [ShadowRow] {
        items.filter { $0.type == type }
    }
}

// MARK: - Live (SSE) reconcile
//
// A received event is an OBSERVATION of canonical state, never a grant of
// authority and never proof the client initiated the mutation. On any live
// event the projection therefore RECONCILES BY REFETCHING the authoritative
// /api/v1 projection — the server is the source of truth, the client view is
// a projection. This mirrors the web client's pocket.events.subscribe behavior.

public extension PocketTwinProjection {
    /// Begin reconciling from the live event spine. Returns a subscription
    /// token; call `client.unsubscribe(token)` to stop.
    @discardableResult
    func reconcileOnLive() async -> UUID {
        let token = client.subscribe { [weak self] _ in
            Task { [weak self] in
                _ = try? await self?.refresh()
            }
        }
        _ = token
        return token
    }

    /// Stop reconciling from the live spine for the given subscription token.
    func stopReconciling(_ token: UUID) {
        client.unsubscribe(token)
    }
}

public extension PocketShadowProjection {
    /// Begin reconciling from the live event spine. Returns a subscription
    /// token; call `client.unsubscribe(token)` to stop.
    @discardableResult
    func reconcileOnLive() async -> UUID {
        let token = client.subscribe { [weak self] _ in
            Task { [weak self] in
                _ = try? await self?.refresh()
            }
        }
        _ = token
        return token
    }
}
