// Theme.swift
// Pocket OS shared visual language. Dark-first, restrained accent, high
// information density. Epistemic + authority states are shown with labels and
// icons, not color alone (accessibility).

import SwiftUI

/// Canonical Pocket OS colors.
public enum PocketTheme {
    public static let bg = Color(red: 0.043, green: 0.071, blue: 0.125)      // #0b1220
    public static let panel = Color(red: 0.063, green: 0.102, blue: 0.180)    // #101a2e
    public static let panel2 = Color(red: 0.051, green: 0.086, blue: 0.149)   // #0d1626
    public static let line = Color(red: 0.118, green: 0.173, blue: 0.267)     // #1e2c44
    public static let ink = Color(red: 0.859, green: 0.902, blue: 0.961)      // #dbe6f5
    public static let muted = Color(red: 0.510, green: 0.588, blue: 0.702)    // #8296b3
    public static let accent = Color(red: 0.345, green: 0.651, blue: 1.0)     // #58a6ff
    public static let good = Color(red: 0.247, green: 0.714, blue: 0.545)
    public static let bad = Color(red: 0.937, green: 0.325, blue: 0.314)
    public static let warn = Color(red: 0.886, green: 0.725, blue: 0.239)
}

/// Visual treatment for an epistemic status. Carries a label + icon + color so
/// states are distinguishable without relying on color alone.
public struct EpistemicTone {
    public let color: Color
    public let icon: String

    public init(color: Color, icon: String) {
        self.color = color
        self.icon = icon
    }
}

public enum PocketEpistemicStyle {
    public static func tone(for status: EpistemicStatus?) -> EpistemicTone {
        switch status {
        case .verified: return EpistemicTone(color: PocketTheme.good, icon: "checkmark.shield.fill")
        case .observed: return EpistemicTone(color: PocketTheme.accent, icon: "eye.fill")
        case .inferred: return EpistemicTone(color: PocketTheme.warn, icon: "sparkles")
        case .uncertain: return EpistemicTone(color: .purple, icon: "questionmark.circle.fill")
        case .rejected: return EpistemicTone(color: PocketTheme.bad, icon: "xmark.circle.fill")
        case .stale: return EpistemicTone(color: .gray, icon: "clock.fill")
        case nil: return EpistemicTone(color: PocketTheme.muted, icon: "minus.circle")
        }
    }
}
