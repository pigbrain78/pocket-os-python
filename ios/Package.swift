// swift-tools-version:5.9
// Pocket OS iOS client — consumes the canonical /api/v1 contract.
// Configurable base URL, SSE reconnection, exponential backoff, server-authoritative state.
import PackageDescription

let package = Package(
    name: "PocketOSClient",
    platforms: [
        .iOS(.v15),
        .macOS(.v12)
    ],
    products: [
        .library(name: "PocketOSClient", targets: ["PocketOSClient"])
    ],
    targets: [
        .target(
            name: "PocketOSClient",
            dependencies: [],
            path: "Sources/PocketOSClient"
        ),
        .testTarget(
            name: "PocketOSClientTests",
            dependencies: ["PocketOSClient"],
            path: "Tests/PocketOSClientTests"
        )
    ]
)
