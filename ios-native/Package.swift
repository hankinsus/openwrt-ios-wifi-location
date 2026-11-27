// swift-tools-version: 5.9
// 逻辑库不含界面和 idevice。Linux 上只能测试这一层。
import PackageDescription

let package = Package(
    name: "LanLocationCore",
    products: [
        .library(name: "LanLocationCore", targets: ["LanLocationCore"])
    ],
    targets: [
        .target(name: "LanLocationCore"),
        .testTarget(name: "LanLocationCoreTests", dependencies: ["LanLocationCore"])
    ]
)
