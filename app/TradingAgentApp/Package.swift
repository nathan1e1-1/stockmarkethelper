// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "TradingAgentApp",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "TradingAgentApp", path: ".")
    ]
)
