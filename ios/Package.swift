// swift-tools-version:6.0
// PocketOSKit — the canonical Pocket OS client + projection layer for the iPhone.
//
// Transport/projection logic is platform-independent Swift (compilable and testable
// on Linux). The SwiftUI cockpit lives in PocketOSCockpit, gated to Apple platforms.
import PackageDescription

let package = Package(
    name: "PocketOSKit",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(name: "PocketOSKit", targets: ["PocketOSKit"])
    ],
    targets: [
        .target(name: "PocketOSKit"),
        .testTarget(name: "PocketOSKitTests",
                    dependencies: ["PocketOSKit"],
                    resources: [.process("Fixtures")])
    ]
)
