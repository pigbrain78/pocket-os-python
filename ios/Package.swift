// swift-tools-version:5.9
// Pocket OS iOS client skeleton — consumes the canonical /api/v1 contract.
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
        .target(name: "PocketOSClient"),
        .testTarget(name: "PocketOSClientTests", dependencies: ["PocketOSClient"])
    ]
)
