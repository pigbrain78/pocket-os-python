// PocketOSApp.swift
// Pocket OS iPhone entry point. HOME, MEMORY, PROJECTS, TWIN, SHADOW,
// DECISIONS, GOVERNANCE, EVIDENCE, GRAPH, SETTINGS.

import SwiftUI

@main
public struct PocketOSApp: App {
    @StateObject private var vm = PocketOSViewModel(
        baseURL: URL(string: "http://127.0.0.1:8787")!
    )

    public init() {}

    public var body: some Scene {
        WindowGroup {
            RootTabView(vm: vm)
                .preferredColorScheme(.dark)
                .task {
                    await vm.loadAll()
                    vm.startStream()
                }
        }
    }
}

public struct RootTabView: View {
    @ObservedObject public var vm: PocketOSViewModel
    public init(vm: PocketOSViewModel) { self.vm = vm }

    public var body: some View {
        TabView {
            HomeView(vm: vm).tabItem { Label("Home", systemImage: "house.fill") }
            MemoryView(vm: vm).tabItem { Label("Memory", systemImage: "brain.head.profile") }
            ProjectsView(vm: vm).tabItem { Label("Projects", systemImage: "folder.fill") }
            TwinView(vm: vm).tabItem { Label("Twin", systemImage: "person.crop.circle.fill") }
            ShadowView(vm: vm).tabItem { Label("Shadow", systemImage: "eye.fill") }
            DecisionsView(vm: vm).tabItem { Label("Decisions", systemImage: "checkmark.seal.fill") }
            GovernanceView(vm: vm).tabItem { Label("Governance", systemImage: "scale.3d") }
            EvidenceView(vm: vm).tabItem { Label("Evidence", systemImage: "doc.text.magnifyingglass") }
            GraphView(vm: vm).tabItem { Label("Graph", systemImage: "point.3.connected.trianglepath.dotted") }
            SettingsView(vm: vm).tabItem { Label("Settings", systemImage: "gearshape.fill") }
        }
        .tint(PocketTheme.accent)
    }
}
