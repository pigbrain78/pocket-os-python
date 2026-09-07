# Pocket OS — iPhone Build & Cockpit Runbook

The iPhone client is two parts that share the **same canonical Pocket OS contract**:

1. **`PocketOSKit`** — a SwiftPM library (models, projections, `PocketOSClient`
   transport, session). Platform-independent Swift: it **compiles and tests on
   Linux** (Swift 6.0.3) and decodes the real `/api/*` contract from captured
   fixtures.
2. **`PocketOSApp/` (SwiftUI cockpit)** — the native iPhone interface. This is
   **Apple-gated**: it requires Xcode and a real device/simulator and is **not**
   compiled in this cloud workspace. It consumes the same projections through the
   same client.

## What is verified in the cloud workspace

```
ios/Package.swift                       SwiftPM manifest (iOS 17 / macOS 14)
ios/Sources/PocketOSKit/                models + projections + client (Linux-clean)
ios/Tests/PocketOSKitTests/             decode tests against REAL captured API fixtures
ios/Tests/PocketOSKitTests/Fixtures/    twin/shadow/decisions/state/health JSON
```

Run from the `ios/` directory:

```bash
export PATH=/opt/swift/usr/bin:$PATH   # in this sandbox
swift build
swift test                              # 5 tests, all decode the live contract
```

The Swift tests assert the constitutional boundaries structurally:
- the Cognitive Twin's `current_focus` is **INFERRED** (never authoritative);
- the AI Shadow carries `AUTHORITY NONE`, `can_execute=false`, `can_ratify=false`;
- a RATIFIED decision is never conflated with an EXECUTED one;
- the ledger decodes with an intact `previous_hash → hash` chain (25 records).

## What is authored for Xcode (not compiled here)

`ios/PocketOSApp/Sources/Cockpit/` — the SwiftUI cockpit:

| File | Contents |
| --- | --- |
| `PocketOSApp.swift` | app + `RootTabView` with the 10 tabs |
| `Theme.swift` | shared dark visual language + epistemic tone mapping |
| `Components.swift` | `EpistemicBadge`, `AuthorityBadge`, `TwinItemRow`, `ShadowItemCard` |
| `PocketOSViewModel.swift` | `ObservableObject` coordinating canonical projections + stream |
| `Screens.swift` | HOME/MEMORY/PROJECTS/TWIN/SHADOW/DECISIONS/GOVERNANCE/EVIDENCE/GRAPH/SETTINGS |

The architecture is exactly: **SwiftUI View → ViewModel → PocketTwinProjection /
PocketShadowProjection → PocketOSClient → Pocket OS API**. No Pocket OS business
logic lives in SwiftUI.

### To build the iPhone app in Xcode (Local conversation / your Mac)

1. Create a new iOS app target (SwiftUI, iOS 17+) and add this folder as a local
   Swift package dependency, or copy the two source folders into the target.
2. Link `PocketOSKit`; add `PocketOSApp/Sources/Cockpit/*.swift` to the app target.
3. Set the API base URL in `PocketOSApp.swift` to your running backend
   (`http://127.0.0.1:8787` for a local simulator; use a reachable host for a real
   device, and note App Transport Security will need an exception for plain HTTP).
4. Build and run. Sign in as `operator` / `demo` (PROPOSE/COUNCIL/RATIFY/EXECUTE)
   to exercise the constitutional actions; `observer` / `demo` for read-only.

### Live event stream

The production SSE consumer (`/api/stream`) belongs in the Apple target via a
`URLSession` data-delegate for incremental parsing; the Linux-clean `PocketOSKit`
keeps transport generic so it compiles everywhere. The **SSE contract is the same**:
a received event is an **observation** that triggers a canonical refetch — never
proof the client caused a mutation. Reconnect → resync → rebuild projections → resume.

## No competing source of truth

The iPhone is a client. It never writes the ledger, never sets hashes/sequences/
governance, and never promotes INFERRED→VERIFIED or PROPOSED→ACCEPTED. All state
comes from Pocket OS; the ledger JSON is authoritative and unchanged by the clients.
