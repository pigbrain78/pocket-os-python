// Components.swift
// Shared SwiftUI components. These render canonical projection state; none of
// them grants or implies authority. Epistemic/authority states are conveyed by
// label + icon + color so they are never color-only (accessibility).

import SwiftUI
import PocketOSKit

/// A badge showing an epistemic status with its icon + label.
public struct EpistemicBadge: View {
    public let status: EpistemicStatus?
    public init(status: EpistemicStatus?) { self.status = status }

    public var body: some View {
        let tone = PocketEpistemicStyle.tone(for: status)
        HStack(spacing: 4) {
            Image(systemName: tone.icon).font(.system(size: 9, weight: .bold))
            Text(status?.rawValue ?? "—")
                .font(.system(size: 9, weight: .bold, design: .monospaced))
        }
        .foregroundColor(tone.color)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .overlay(
            RoundedRectangle(cornerRadius: 4)
                .stroke(tone.color.opacity(0.6), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Epistemic status \(status?.rawValue ?? "unknown")")
    }
}

/// A visible authority boundary badge (used by the AI Shadow).
public struct AuthorityBadge: View {
    public let label: String
    public let canExecute: Bool
    public let canRatify: Bool
    public init(label: String, canExecute: Bool, canRatify: Bool) {
        self.label = label
        self.canExecute = canExecute
        self.canRatify = canRatify
    }

    public var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "lock.shield.fill")
            Text(label)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
            Text("EXEC \(canExecute ? "Y" : "NO") · RATIFY \(canRatify ? "Y" : "NO")")
                .font(.system(size: 8, weight: .regular, design: .monospaced))
        }
        .foregroundColor(canExecute ? PocketTheme.warn : PocketTheme.good)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(PocketTheme.panel2)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(PocketTheme.line, lineWidth: 1))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label). Can execute \(canExecute ? "yes" : "no"). Can ratify \(canRatify ? "yes" : "no").")
    }
}

/// A single line for a Twin item (text + epistemic + confidence + provenance).
public struct TwinItemRow: View {
    public let item: TwinItem
    public init(item: TwinItem) { self.item = item }

    public var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .top, spacing: 8) {
                EpistemicBadge(status: item.epistemic)
                Text(item.text)
                    .font(.system(size: 14))
                    .foregroundColor(PocketTheme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(metaLine)
                .font(.system(size: 10, design: .monospaced))
                .foregroundColor(PocketTheme.muted)
        }
        .padding(.vertical, 5)
        .accessibilityElement(children: .contain)
    }

    private var metaLine: String {
        var parts: [String] = []
        if let c = item.confidence { parts.append("conf \(String(format: "%.2f", c))") }
        parts.append(item.provenance)
        if !item.evidence.isEmpty {
            parts.append("evidence " + item.evidence.map { "#\($0)" }.joined(separator: ","))
        }
        return parts.joined(separator: " · ")
    }
}

/// A titled card grouping a list of Twin items.
public struct TwinCard: View {
    public let title: String
    public let items: [TwinItem]
    public init(title: String, items: [TwinItem]) {
        self.title = title
        self.items = items
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .semibold))
                .tracking(1)
                .foregroundColor(PocketTheme.muted)
            if items.isEmpty {
                Text("none").font(.system(size: 12)).foregroundColor(PocketTheme.muted)
            } else {
                ForEach(items, id: \.provenance) { item in
                    Divider().background(PocketTheme.line)
                    TwinItemRow(item: item)
                }
            }
        }
        .padding(12)
        .background(PocketTheme.panel)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line, lineWidth: 1))
    }
}

/// A shadow item card with explicit authority boundary.
public struct ShadowItemCard: View {
    public let item: ShadowItem
    public init(item: ShadowItem) { self.item = item }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(item.type)
                    .font(.system(size: 9, weight: .bold, design: .monospaced))
                    .foregroundColor(PocketTheme.accent)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 1)
                    .overlay(RoundedRectangle(cornerRadius: 3).stroke(PocketTheme.accent.opacity(0.5)))
                Spacer()
                AuthorityBadge(label: item.authority ?? "NONE",
                               canExecute: false, canRatify: false)
            }
            Text(item.text).font(.system(size: 14)).foregroundColor(PocketTheme.ink)
            if let step = item.nextStep {
                Text("next: \(step)").font(.system(size: 11)).foregroundColor(PocketTheme.muted)
            }
            Text(metaLine).font(.system(size: 10, design: .monospaced)).foregroundColor(PocketTheme.muted)
        }
        .padding(12)
        .background(PocketTheme.panel2)
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(PocketTheme.line, lineWidth: 1))
    }

    private var metaLine: String {
        var parts: [String] = []
        if let c = item.confidence { parts.append("conf \(String(format: "%.2f", c))") }
        parts.append(item.provenance)
        return parts.joined(separator: " · ")
    }
}

/// A colored status pill.
public struct StatusPill: View {
    public let text: String
    public let color: Color
    public init(_ text: String, color: Color) {
        self.text = text
        self.color = color
    }

    public var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .bold, design: .monospaced))
            .foregroundColor(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .overlay(RoundedRectangle(cornerRadius: 20).stroke(color.opacity(0.6), lineWidth: 1))
            .accessibilityLabel(text)
    }
}
