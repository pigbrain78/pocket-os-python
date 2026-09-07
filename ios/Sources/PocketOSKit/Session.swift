// Session.swift
// Authentication against the real Pocket OS backend. One auth system only.
// The server is authoritative for expiry/revocation; the client never invents
// permissions or authority.

import Foundation

/// A validated session returned by `/api/login` and refreshed via `/api/session/me`.
public struct PocketSession: Codable, Equatable, Sendable {
    public var token: String?
    public var subject: String
    public var permissions: [String]
    public var expiresAt: Int?

    public enum CodingKeys: String, CodingKey {
        case token, subject, permissions
        case expiresAt = "expires_at"
    }

    public func hasPermission(_ p: String) -> Bool {
        permissions.contains(p)
    }
}

/// The canonical permission set. These mirror the backend constants and are
/// used to decide which UI actions to show — never to authorize anything.
public enum Permission: String, Sendable {
    case read = "READ"
    case propose = "PROPOSE"
    case council = "COUNCIL"
    case ratify = "RATIFY"
    case execute = "EXECUTE"
    case admin = "ADMIN"
}
