// PocketOSClient CockpitView.swift
//
// iPhone Cognitive Cockpit v1 — SwiftUI projection of the canonical Cognitive
// Twin + AI Shadow. Apple-gated: this file only compiles where SwiftUI exists
// (iOS 17+ / macOS 14+). It is kept OUT of the Linux-compiled library target
// via Package.swift so the platform-neutral core remains Linux-testable.
//
// The view is a thin projection: "here is what Pocket OS currently says." It
// holds no authority, does no reasoning, and cannot mutate canonical state.
import Foundation
#if canImport(SwiftUI)
import SwiftUI

/// Observable ViewModel binding the Cockpit SwiftUI view to the tested
/// projections. Thin: it assembles CockpitViewState and refreshes on demand /
/// on live events; all reasoning stays server-side.
@MainActor
public final class CockpitViewModel: ObservableObject {
    @Published public private(set) var state: CockpitViewState?
    @Published public private(set) var isLoading = false
    @Published public private(set) var errorMessage: String?

    private let twin: PocketTwinProjection
    private let shadow: PocketShadowProjection

    public init(twin: PocketTwinProjection, shadow: PocketShadowProjection) {
        self.twin = twin
        self.shadow = shadow
    }

    public func load() async {
        isLoading = true
        defer { isLoading = false }
        async let a: Void = refresh()
        _ = await a
    }

    public func refresh() async {
        errorMessage = nil
        do {
            try await twin.refresh()
            try await shadow.refresh()
            state = Cockpit.build(twin: twin, shadow: shadow)
        } catch {
            errorMessage = (error as? PocketProjectionError).map { String(describing: $0) } ?? error.localizedDescription
        }
    }

    /// Reconcile from the live event spine (server-authoritative refetch).
    public func reconcileOnLive() async {
        reconcileToken = await twin.reconcileOnLive()
        _ = await shadow.reconcileOnLive()
        await refresh()
    }

    /// Stop reconciling from the live spine.
    public func stopReconcile() async {
        guard let token = reconcileToken else { return }
        await twin.stopReconciling(token)
        reconcileToken = nil
    }
    /// Subscription token for the live spine; call stop() on deinit path.
    public private(set) var reconcileToken: UUID?
}

/// The Cognitive Cockpit: current focus + projects + loops + advisory Shadow.
public struct CognitiveCockpitView: View {
    @StateObject var model: CockpitViewModel

    public init(model: CockpitViewModel) { _model = StateObject(wrappedValue: model) }

    public var body: some View {
        Group {
            if let state = model.state {
                content(state)
            } else if model.isLoading {
                ProgressView("Loading cognitive state…")
            } else {
                VStack(spacing: 12) {
                    Text("Connect to Pocket OS").font(.headline)
                    if let msg = model.errorMessage { Text(msg).font(.caption).foregroundColor(.secondary) }
                }
            }
        }
        .task { await model.load(); await model.reconcileOnLive() }
    }

    @ViewBuilder private func content(_ s: CockpitViewState) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                cockpitHeader(s)
                focusCard(s)
                sectionCard("ACTIVE PROJECTS", rows: s.activeProjects)
                sectionCard("OPEN LOOPS", rows: s.openLoops)
                advisoryCard(s.advisory)
                if !s.memories.isEmpty { sectionCard("MEMORY", rows: s.memories) }
            }
            .padding()
        }
        .background(Color(.systemBackground))
    }

    private func cockpitHeader(_ s: CockpitViewState) -> some View {
        HStack {
            Text("Pocket OS").font(.title2.bold())
            Spacer()
            Text("twin \(s.modelVersion)").font(.caption.monospaced()).foregroundColor(.secondary)
        }
    }

    /// Current focus card — the epistemic badge is the visual anchor.
    private func focusCard(_ s: CockpitViewState) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("CURRENT FOCUS").font(.caption.weight(.semibold)).foregroundColor(.secondary)
            if let epi = s.focusEpistemic {
                HStack {
                    EpistemicBadge(style: CockpitEpistemicStyle(epi))
                    Text(s.focusText).font(.headline)
                }
            } else {
                Text("No active focus").font(.headline).foregroundColor(.secondary)
            }
            Text("Confidence \(Int((s.focusConfidence * 100).rounded()))%").font(.caption).foregroundColor(.secondary)
        }
        .padding().frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private func sectionCard(_ title: String, rows: [CockpitRow]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.caption.weight(.semibold)).foregroundColor(.secondary)
            if rows.isEmpty {
                Text("None").font(.subheadline).foregroundColor(.secondary)
            } else {
                ForEach(rows.prefix(6)) { row in rowLine(row) }
            }
        }
        .padding().frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private func rowLine(_ row: CockpitRow) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            EpistemicBadge(style: CockpitEpistemicStyle(row.epistemic)).scaleEffect(0.85)
            Text(row.text).font(.subheadline)
        }
    }

    /// AI Shadow advisory block — visibly authority NONE.
    private func advisoryCard(_ a: CockpitAdvisory) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("AI SHADOW").font(.caption.weight(.semibold)).foregroundColor(.secondary)
                Spacer()
                Text("ADVISORY").font(.caption2.bold()).foregroundColor(.blue)
            }
            Text("AUTHORITY: \(a.authority)").font(.caption.monospaced())
            Text("CAN EXECUTE: \(a.canExecute ? "YES" : "NO")").font(.caption.monospaced())
            Text("CAN RATIFY: \(a.canRatify ? "YES" : "NO")").font(.caption.monospaced())
            if !a.observations.isEmpty { advisoryGroup("Observation", a.observations) }
            if !a.recommendations.isEmpty { advisoryGroup("Recommendation", a.recommendations) }
            if !a.warnings.isEmpty { advisoryGroup("Warning", a.warnings) }
        }
        .padding().frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.secondarySystemBackground)))
    }

    private func advisoryGroup(_ label: String, _ rows: [CockpitRow]) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(rows.prefix(4)) { row in
                Text("\(label): \(row.text)").font(.footnote).foregroundColor(.primary)
            }
        }
    }
}

/// Distinct visual token per epistemic status — never interchangeable.
public struct EpistemicBadge: View {
    let style: CockpitEpistemicStyle
    public init(style: CockpitEpistemicStyle) { self.style = style }
    public var body: some View {
        Text(style.label)
            .font(.caption2.bold().monospaced())
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(color.opacity(0.18), in: RoundedRectangle(cornerRadius: 4))
            .foregroundColor(color)
    }
    var color: Color {
        switch style {
        case .verified: return .green
        case .observed: return .teal
        case .inferred: return .orange
        case .proposed: return .purple
        case .uncertain: return .yellow
        case .rejected: return .red
        case .stale: return .gray
        case .unknown: return .secondary
        }
    }
}
#endif
