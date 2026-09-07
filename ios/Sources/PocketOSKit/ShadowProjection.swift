// ShadowProjection.swift
// AI Shadow projection — advisory only. The Shadow never carries authority.

import Foundation

/// One AI Shadow item (observation, insight, warning, opportunity, question,
/// recommendation, proposal). Always advisory; never authoritative.
public struct ShadowItem: Codable, Equatable, Sendable {
    public var type: String
    public var text: String
    public var confidence: Double?
    public var evidence: [Int]
    public var provenance: String
    public var status: String?
    public var authority: String?
    public var nextStep: String?

    public enum CodingKeys: String, CodingKey {
        case type, text, confidence, evidence, provenance, status, authority
        case nextStep = "next_step"
    }
}

/// Explicit authority boundary for the AI Shadow. The UI must render this.
public struct ShadowBoundary: Codable, Equatable, Sendable {
    public var canExecute: Bool
    public var canRatify: Bool
    public var authority: String
    public var executionRequires: [String]

    public enum CodingKeys: String, CodingKey {
        case canExecute = "shadow_can_execute"
        case canRatify = "shadow_can_ratify"
        case authority = "shadow_authority"
        case executionRequires = "execution_requires"
    }
}

/// The full AI Shadow projection.
public struct ShadowProjection: Codable, Equatable, Sendable {
    public var types: [String]
    public var items: [ShadowItem]
    public var authorityBoundary: ShadowBoundary

    public enum CodingKeys: String, CodingKey {
        case types, items
        case authorityBoundary = "authority_boundary"
    }

    /// Human-facing summary of the authority boundary.
    public var authorityLabel: String {
        let a = authorityBoundary.authority.uppercased()
        return "AUTHORITY \(a.isEmpty ? "NONE" : a)"
    }
}
