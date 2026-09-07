// Screens.swift
// Primary cockpit screens: Home (Cognitive Cockpit), Memory, Projects, Twin,
// Shadow, Decisions, Governance, Evidence, Graph, Settings. Each renders the
// canonical projection; none grants or implies authority.

import SwiftUI
import PocketOSKit

/// HOME — the glanceable cognitive cockpit.
public struct HomeView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    header
                    if let twin = vm.twin { cockpitSummary(twin) }
                    if let shadow = vm.shadow { shadowStrip(shadow) }
                    if let state = vm.state { recentEvents(state) }
                }
                .padding(16)
            }
            .background(PocketTheme.bg.ignoresSafeArea())
            .navigationTitle("Pocket OS")
            .task { await vm.loadAll() }
        }
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("COGNITIVE COCKPIT")
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .tracking(2)
                .foregroundColor(PocketTheme.accent)
            HStack(spacing: 8) {
                StatusPill("LEDGER \(vm.state?.integrity ?? "…")",
                           color: vm.state?.integrity == "INTACT" ? PocketTheme.good : PocketTheme.bad)
                StatusPill("STREAM \(vm.streamStatus.uppercased())",
                           color: vm.streamStatus == "live" ? PocketTheme.good : PocketTheme.warn)
                if let s = vm.session { Text(s.subject).font(.caption).foregroundColor(PocketTheme.muted) }
                else { Text("signed out").font(.caption).foregroundColor(PocketTheme.muted) }
            }
        }
    }

    private func cockpitSummary(_ twin: CognitiveTwinProjection) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            // Current focus is INFERRED — label it as such.
            if let focus = twin.state.currentFocus {
                VStack(alignment: .leading, spacing: 6) {
                    Text("CURRENT FOCUS").font(.system(size: 10, weight: .semibold))
                        .tracking(1).foregroundColor(PocketTheme.muted)
                    TwinItemRow(item: focus)
                    if focus.epistemic == .inferred {
                        Text("Inferred — appears to be the current focus, not confirmed.")
                            .font(.system(size: 10)).italic()
                            .foregroundColor(PocketTheme.warn)
                    }
                }
                .padding(12).background(PocketTheme.panel)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line))
            }

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                TwinCard(title: "Active Projects", items: twin.state.activeProjects)
                TwinCard(title: "Open Loops", items: twin.state.openLoops)
            }
            TwinCard(title: "Relevant Memories", items: twin.relevantMemories)
        }
    }

    private func shadowStrip(_ shadow: ShadowProjection) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("AI SHADOW").font(.system(size: 10, weight: .semibold)).tracking(1)
                    .foregroundColor(PocketTheme.muted)
                Spacer()
                AuthorityBadge(label: shadow.authorityLabel,
                               canExecute: shadow.authorityBoundary.canExecute,
                               canRatify: shadow.authorityBoundary.canRatify)
            }
            if let top = shadow.items.first {
                Text(top.text).font(.system(size: 14)).foregroundColor(PocketTheme.ink)
            }
        }
        .padding(12).background(PocketTheme.panel)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line))
    }

    private func recentEvents(_ state: PocketStateProjection) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("RECENT EVENTS").font(.system(size: 10, weight: .semibold)).tracking(1)
                .foregroundColor(PocketTheme.muted)
            let recent = Array(state.records.suffix(6).reversed())
            ForEach(recent, id: \.sequence) { r in
                HStack {
                    Text("#\(r.sequence)").font(.system(size: 11, design: .monospaced))
                        .foregroundColor(PocketTheme.accent)
                    Text(r.event).font(.system(size: 11, design: .monospaced))
                        .foregroundColor(PocketTheme.muted)
                    Spacer()
                }
            }
        }
        .padding(12).background(PocketTheme.panel)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line))
    }
}

/// MEMORY
public struct MemoryView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        List {
            if let state = vm.state {
                ForEach(state.records.reversed().filter { isMemory($0.event) }, id: \.sequence) { r in
                    HStack(alignment: .top, spacing: 8) {
                        Text("#\(r.sequence)").font(.system(size: 11, design: .monospaced))
                            .foregroundColor(PocketTheme.muted)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title(of: r)).font(.system(size: 14)).foregroundColor(PocketTheme.ink)
                            Text("\(r.event) · src \(r.source ?? "-") · \(r.hash.prefix(8))")
                                .font(.system(size: 10, design: .monospaced)).foregroundColor(PocketTheme.muted)
                        }
                    }
                }
            } else {
                Text("Loading memory…").font(.system(size: 13)).foregroundColor(PocketTheme.muted)
            }
        }
        .listStyle(.plain)
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Memory")
        .preferredColorScheme(.dark)
    }

    private func isMemory(_ e: String) -> Bool { e == "memory.created" || e == "knowledge.document" }
    private func title(of r: LedgerRecord) -> String {
        (r.payload?.objectValue?["title"])?.displayText ?? r.event
    }
}

/// PROJECTS
public struct ProjectsView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let twin = vm.twin {
                    TwinCard(title: "Active Projects", items: twin.state.activeProjects)
                    TwinCard(title: "Open Loops", items: twin.state.openLoops)
                    TwinCard(title: "Decision History", items: twin.decisionHistory)
                } else {
                    Text("Loading projects…").foregroundColor(PocketTheme.muted)
                }
            }
            .padding(16)
        }
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Projects")
        .preferredColorScheme(.dark)
    }
}

/// TWIN
public struct TwinView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let twin = vm.twin {
                    Text(twin.summary).font(.system(size: 12)).foregroundColor(PocketTheme.muted)
                    if let focus = twin.state.currentFocus {
                        TwinCard(title: "Current Focus", items: [focus])
                    }
                    TwinCard(title: "Open Loops", items: twin.state.openLoops)
                    TwinCard(title: "Closed Loops", items: twin.state.closedLoops)
                    TwinCard(title: "Relevant Memories", items: twin.relevantMemories)
                    TwinCard(title: "Relationships", items: twin.relationships)
                    TwinCard(title: "Recent Observations", items: twin.recentObservations)
                    Text("Twin is advisory. INFERRED items are hypotheses, not facts.")
                        .font(.system(size: 10)).italic().foregroundColor(PocketTheme.warn)
                } else {
                    Text("Loading Twin…").foregroundColor(PocketTheme.muted)
                }
            }
            .padding(16)
        }
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Cognitive Twin")
        .preferredColorScheme(.dark)
    }
}

/// SHADOW
public struct ShadowView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if let shadow = vm.shadow {
                    HStack {
                        Text("ADVISORY LAYER").font(.system(size: 10, weight: .semibold)).tracking(1)
                            .foregroundColor(PocketTheme.muted)
                        Spacer()
                        AuthorityBadge(label: shadow.authorityLabel,
                                       canExecute: shadow.authorityBoundary.canExecute,
                                       canRatify: shadow.authorityBoundary.canRatify)
                    }
                    Text("The AI Shadow observes and proposes. It never executes, ratifies, or authorizes.")
                        .font(.system(size: 11)).italic().foregroundColor(PocketTheme.muted)
                    ForEach(shadow.items, id: \.provenance + \.text) { item in
                        ShadowItemCard(item: item)
                    }
                } else {
                    Text("Loading AI Shadow…").foregroundColor(PocketTheme.muted)
                }
            }
            .padding(16)
        }
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("AI Shadow")
        .preferredColorScheme(.dark)
    }
}

/// DECISIONS
public struct DecisionsView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        List(vm.decisions, id: \.decisionId) { d in
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(d.decisionId).font(.system(size: 10, design: .monospaced))
                        .foregroundColor(PocketTheme.muted)
                    Spacer()
                    StatusPill(d.status?.rawValue ?? "—",
                               color: statusColor(d.status))
                }
                Text(d.title).font(.system(size: 15, weight: .semibold)).foregroundColor(PocketTheme.ink)
                Text("risk \(d.risk ?? "-") · reversible \(d.reversible == true ? "yes" : "no") · reasoning \(d.reasonHash ?? "-")")
                    .font(.system(size: 10, design: .monospaced)).foregroundColor(PocketTheme.muted)
                if let stage = d.stage {
                    Text("stage \(stage)").font(.system(size: 10, weight: .bold, design: .monospaced))
                        .foregroundColor(PocketTheme.accent)
                }
            }
            .padding(.vertical, 4)
        }
        .listStyle(.plain)
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Decisions")
        .preferredColorScheme(.dark)
    }

    private func statusColor(_ s: DecisionStatus?) -> Color {
        switch s {
        case .ratified, .executed: return PocketTheme.good
        case .rejected: return PocketTheme.bad
        case .pending, .council, .awaitingRatification: return PocketTheme.warn
        case nil: return PocketTheme.muted
        }
    }
}

/// GOVERNANCE
public struct GovernanceView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("MEMORY MAY INFORM. MEMORY MAY NOT AUTHORIZE.")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .foregroundColor(PocketTheme.warn)
                if let state = vm.state {
                    Text(state.counters)
                        .font(.system(size: 11, design: .monospaced)).foregroundColor(PocketTheme.muted)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("AUTHORITY CHAIN").font(.system(size: 10, weight: .semibold)).tracking(1)
                        .foregroundColor(PocketTheme.muted)
                    ForEach(["LLM proposes", "Council evaluates", "Governance authorizes",
                             "Human ratifies", "Kernel executes", "Ledger records"], id: \.self) { step in
                        HStack(spacing: 8) {
                            Image(systemName: "arrow.right").font(.system(size: 9))
                                .foregroundColor(PocketTheme.accent)
                            Text(step).font(.system(size: 13)).foregroundColor(PocketTheme.ink)
                        }
                    }
                }
                .padding(12).background(PocketTheme.panel)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line))
                ForEach(vm.decisions, id: \.decisionId) { d in
                    HStack {
                        Text(d.title).font(.system(size: 13)).foregroundColor(PocketTheme.ink)
                        Spacer()
                        Text(d.status?.rawValue ?? "—")
                            .font(.system(size: 9, design: .monospaced)).foregroundColor(statusColor(d.status))
                    }
                    .padding(10).background(PocketTheme.panel2)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(PocketTheme.line))
                }
            }
            .padding(16)
        }
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Governance")
        .preferredColorScheme(.dark)
    }

    private func statusColor(_ s: DecisionStatus?) -> Color {
        switch s {
        case .ratified, .executed: return PocketTheme.good
        case .rejected: return PocketTheme.bad
        default: return PocketTheme.warn
        }
    }
}

/// EVIDENCE
public struct EvidenceView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        List {
            if let state = vm.state {
                Text("Why does Pocket OS believe this? Every record is hash-chained to the previous (SHA-256 over canonical form). Integrity: \(state.integrity).")
                    .font(.system(size: 11)).foregroundColor(PocketTheme.muted)
                ForEach(state.records.reversed(), id: \.sequence) { r in
                    VStack(alignment: .leading, spacing: 2) {
                        Text("#\(r.sequence) \(r.event)")
                            .font(.system(size: 12, design: .monospaced)).foregroundColor(PocketTheme.ink)
                        Text("src \(r.source ?? "-") · hash \(r.hash.prefix(16))")
                            .font(.system(size: 9, design: .monospaced)).foregroundColor(PocketTheme.muted)
                    }
                }
            } else {
                Text("Loading evidence…").foregroundColor(PocketTheme.muted)
            }
        }
        .listStyle(.plain)
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Evidence")
        .preferredColorScheme(.dark)
    }
}

/// GRAPH — a projection of ledger sources (nodes) and event lineage (edges).
public struct GraphView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("READ-ONLY PROJECTION").font(.system(size: 10, weight: .semibold)).tracking(1)
                    .foregroundColor(PocketTheme.muted)
                if let state = vm.state {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 110))], spacing: 10) {
                        ForEach(nodeCounts(state), id: \.0) { node in
                            VStack(spacing: 2) {
                                Image(systemName: "circle.grid.2x2.fill").foregroundColor(PocketTheme.accent)
                                Text(node.0).font(.system(size: 12, weight: .semibold))
                                    .foregroundColor(PocketTheme.ink)
                                Text("\(node.1)").font(.system(size: 10, design: .monospaced))
                                    .foregroundColor(PocketTheme.muted)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .background(PocketTheme.panel)
                            .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line))
                        }
                    }
                    Text("Nodes = ledger sources; counts = events. Relationships come from canonical data, never decorative.")
                        .font(.system(size: 10)).italic().foregroundColor(PocketTheme.muted)
                }
            }
            .padding(16)
        }
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Graph")
        .preferredColorScheme(.dark)
    }

    private func nodeCounts(_ state: PocketStateProjection) -> [(String, Int)] {
        var counts: [String: Int] = [:]
        for r in state.records { counts[r.source ?? "unknown", default: 0] += 1 }
        return counts.sorted { $0.value > $1.value }
    }
}

/// SETTINGS
public struct SettingsView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    @State private var username = ""
    @State private var password = ""

    public var body: some View {
        Form {
            if vm.session == nil {
                Section("Sign in") {
                    TextField("username", text: $username)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("password", text: $password)
                    Button("Sign in") {
                        Task { await vm.signIn(username: username, password: password) }
                    }
                }
            } else {
                Section("Session") {
                    LabeledContent("User", value: vm.session?.subject ?? "-")
                    LabeledContent("Permissions", value: vm.session?.permissions.joined(separator: ", ") ?? "-")
                    Button("Sign out", role: .destructive) {
                        Task { await vm.signOut() }
                    }
                }
            }
            if let err = vm.loadError {
                Section { Text(err).foregroundColor(PocketTheme.bad) }
            }
        }
        .scrollContentBackground(.hidden)
        .background(PocketTheme.bg.ignoresSafeArea())
        .navigationTitle("Settings")
        .preferredColorScheme(.dark)
    }
}
