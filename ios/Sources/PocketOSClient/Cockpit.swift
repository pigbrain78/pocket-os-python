// PocketOSClient Cockpit.swift
//
// iPhone Cognitive Cockpit v1 — pure presentation helpers for the SwiftUI
// view. This file must stay free of SwiftUI and Apple imports so it compiles
// and is testable on the Linux toolchain. SwiftUI binding lives in
// CockpitView.swift (Apple-gated). The view is a projection of canonical
// Twin + Shadow state: no authority, reasoning, or persistence on-device.
import Foundation

/// A human-presentable row in the Cognitive Cockpit.
public struct CockpitRow: Identifiable, Sendable, Equatable {
    public let id: String
    public let section: String
    public let text: String
    /// Closed epistemic status, displayed distinctly from fact.
    public let epistemic: EpistemicStatus
    public let confidence: Double
    public let evidence: [Int]
    public let provenance: String
    public let isInference: Bool
}

/// The advisory AI Shadow boundary, surfaced so the human sees the
/// architecture: the Shadow advises, it cannot execute or ratify.
public struct CockpitAdvisory: Sendable, Equatable {
    public let authority: String   // "NONE"
    public let canExecute: Bool    // false
    public let canRatify: Bool     // false
    public let requirements: [String] // ["COUNCIL_CONSENSUS","HUMAN_RATIFICATION"]
    public let observations: [CockpitRow]
    public let recommendations: [CockpitRow]
    public let warnings: [CockpitRow]
}

/// UI-ready projection assembled from the canonical Twin + Shadow projections.
public struct CockpitViewState: Sendable, Equatable {
    public let focusText: String
    public let focusEpistemic: EpistemicStatus?  // nil when no focus is loaded
    public let focusConfidence: Double
    public let activeProjects: [CockpitRow]
    public let openLoops: [CockpitRow]
    public let memories: [CockpitRow]
    public let advisory: CockpitAdvisory
    public let modelVersion: String
    public let isLoaded: Bool

    public var isFocusInference: Bool { guard let e = focusEpistemic else { return false }; return e == .inferred || e == .uncertain || e == .proposed }
}

// MARK: - Epistemic display semantics
// VERIFIED/INFERRED/... must never look interchangeable. Each maps to a label
// and a distinct token a color palette can bind to (rawValue stays canonical).
public enum CockpitEpistemicStyle: String, Sendable, Equatable {
    case observed, verified, inferred, proposed, uncertain, rejected, stale
    case unknown

    public var label: String {
        switch self {
        case .observed: return "OBSERVED"
        case .verified: return "VERIFIED"
        case .inferred: return "INFERRED"
        case .proposed: return "PROPOSED"
        case .uncertain: return "UNCERTAIN"
        case .rejected: return "REJECTED"
        case .stale: return "STALE"
        case .unknown: return "UNKNOWN"
        }
    }

    public init(_ e: EpistemicStatus) {
        switch e {
        case .observed: self = .observed
        case .verified: self = .verified
        case .inferred: self = .inferred
        case .proposed: self = .proposed
        case .uncertain: self = .uncertain
        case .rejected: self = .rejected
        case .stale: self = .stale
        }
    }
}

public enum Cockpit {
    /// Assemble a UI-ready cockpit from the canonical projections.
    public static func build(twin: PocketTwinProjection, shadow: PocketShadowProjection) -> CockpitViewState {
        func rows(_ src: [TwinRow]) -> [CockpitRow] {
            src.map { CockpitRow(id: $0.id, section: $0.section, text: $0.text, epistemic: $0.epistemic,
                                 confidence: $0.confidence, evidence: $0.evidence, provenance: $0.provenance,
                                 isInference: $0.epistemic != .verified) }
        }
        let shadowRows = shadow.items.map { CockpitRow(id: $0.id, section: $0.type.rawValue, text: $0.text,
                                                       epistemic: .inferred, confidence: $0.confidence,
                                                       evidence: $0.evidence, provenance: $0.provenance,
                                                       isInference: true) }
        func by(_ t: AIShadowType) -> [CockpitRow] { shadowRows.filter { $0.section == t.rawValue } }
        return CockpitViewState(
            focusText: twin.focus?.text ?? "",
            focusEpistemic: twin.focus?.epistemic,
            focusConfidence: twin.focus?.confidence ?? 0,
            activeProjects: rows(twin.activeProjects),
            openLoops: rows(twin.openLoops),
            memories: rows(twin.memories),
            advisory: CockpitAdvisory(
                authority: shadow.boundaryAuthority,
                canExecute: shadow.canExecute,
                canRatify: shadow.canRatify,
                requirements: ["COUNCIL_CONSENSUS", "HUMAN_RATIFICATION"],
                observations: by(.observation),
                recommendations: by(.recommendation),
                warnings: by(.warning)),
            modelVersion: twin.modelVersion,
            isLoaded: twin.isLoaded && shadow.isLoaded)
    }
}
