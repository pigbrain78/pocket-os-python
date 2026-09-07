// JSONValue.swift
// A lossless, order-preserving JSON value used for heterogeneous ledger payloads.

import Foundation

/// A JSON value that preserves any mixture of string / number / bool / null /
/// array / object without losing data. Ledger payloads are heterogeneous, so a
/// typed dictionary would fail to decode.
public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) { self = .string(s) }
        else if let b = try? c.decode(Bool.self) { self = .bool(b) }
        else if let n = try? c.decode(Double.self) { self = .number(n) }
        else if c.decodeNil() { self = .null }
        else if let a = try? c.decode([JSONValue].self) { self = .array(a) }
        else if let o = try? c.decode([String: JSONValue].self) { self = .object(o) }
        else { throw DecodingError.dataCorruptedError(in: c, debugDescription: "unrepresentable JSON") }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let s): try c.encode(s)
        case .number(let n): try c.encode(n)
        case .bool(let b): try c.encode(b)
        case .null: try c.encodeNil()
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }

    /// Human-usable accessors.
    public var stringValue: String? { if case .string(let s) = self { return s } else { return nil } }
    public var objectValue: [String: JSONValue]? { if case .object(let o) = self { return o } else { return nil } }

    /// Best-effort single-line description for UI display.
    public var displayText: String {
        switch self {
        case .string(let s): return s
        case .number(let n): return n == n.rounded() ? String(Int(n)) : String(n)
        case .bool(let b): return b ? "true" : "false"
        case .null: return ""
        case .array: return "[…]"
        case .object: return "{…}"
        }
    }
}
