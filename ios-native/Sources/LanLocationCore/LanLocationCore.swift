// Copyright (C) 2026 the maintainers of this adaptation.
// Adapted from the location-control behavior observed in
// https://github.com/StikDebug/StikDebug at commit
// 63713ea2100660dc7066ee0e8d962858026f97aa
// That program is AGPL-3.0. This file is a modified, location-only subset.
// It is not the original program and does not use its name or logo.

import Foundation

public struct Coordinate: Equatable, Codable {
    public let latitude: Double
    public let longitude: Double

    public init?(latitude: Double, longitude: Double) {
        guard latitude.isFinite, longitude.isFinite else { return nil }
        guard latitude >= -90, latitude <= 90, longitude >= -180, longitude <= 180 else { return nil }
        self.latitude = latitude
        self.longitude = longitude
    }
}

public struct FavoritePlace: Equatable, Codable, Identifiable {
    public let id: String
    public var name: String
    public var coordinate: Coordinate

    public init?(id: String = UUID().uuidString, name: String, coordinate: Coordinate) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 40, !trimmed.contains(where: \.isNewline) else { return nil }
        self.id = id
        self.name = trimmed
        self.coordinate = coordinate
    }
}

public enum PhoneLocation: String, Equatable, Codable {
    /// No API used here returns the phone's real or simulated fix.
    case unconfirmed
}

public enum PairingRoute: Equatable {
    /// Source: StikDebug/Services/OnDevicePairingService.swift uses `#available(iOS 27.0, *)`.
    /// PAIRING.md states the same minimum. This repository has not run that path.
    case onDeviceWirelessDocumentedUntested(minimumMajor: Int)
    case externalComputerRequired
}

public enum UpstreamFacts {
    public static let commit = "63713ea2100660dc7066ee0e8d962858026f97aa"
    public static let repository = "https://github.com/StikDebug/StikDebug"
    public static let onDevicePairingMinimumMajor = 27
    /// DeviceConnectionContext.swift at the commit above.
    public static let documentedLoopbackAddress = "10.7.0.1"
    public static let locationStatusOK: Int32 = 0
    public static let notLinked: Int32 = -50
}

public func pairingRoute(systemMajor: Int) -> PairingRoute {
    if systemMajor >= UpstreamFacts.onDevicePairingMinimumMajor {
        return .onDeviceWirelessDocumentedUntested(minimumMajor: UpstreamFacts.onDevicePairingMinimumMajor)
    }
    return .externalComputerRequired
}

public protocol LocationCommandPort {
    func set(ip: String, latitude: Double, longitude: Double, pairingPath: String) -> Int32
    func clear() -> Int32
}

public struct ControlSnapshot: Equatable {
    public var commandAccepted: Bool
    public var sessionAlive: Bool
    public var phoneLocation: PhoneLocation
    public var cleanupUnconfirmed: Bool
    public var lastCode: Int32?
    public var summary: String
    public var favorites: [FavoritePlace]
    public var selected: Coordinate?

    public init(
        commandAccepted: Bool = false,
        sessionAlive: Bool = false,
        phoneLocation: PhoneLocation = .unconfirmed,
        cleanupUnconfirmed: Bool = false,
        lastCode: Int32? = nil,
        summary: String = "还没有发送定位命令。",
        favorites: [FavoritePlace] = [],
        selected: Coordinate? = nil
    ) {
        self.commandAccepted = commandAccepted
        self.sessionAlive = sessionAlive
        self.phoneLocation = phoneLocation
        self.cleanupUnconfirmed = cleanupUnconfirmed
        self.lastCode = lastCode
        self.summary = summary
        self.favorites = favorites
        self.selected = selected
    }
}

public final class LocationController {
    private let port: LocationCommandPort
    public private(set) var snapshot: ControlSnapshot

    public init(port: LocationCommandPort) {
        self.port = port
        self.snapshot = ControlSnapshot()
    }

    public func replaceFavorites(_ favorites: [FavoritePlace]) {
        snapshot.favorites = favorites
    }

    public func addFavorite(name: String, latitude: Double, longitude: Double) -> ControlSnapshot {
        guard let coordinate = Coordinate(latitude: latitude, longitude: longitude),
              let place = FavoritePlace(name: name, coordinate: coordinate) else {
            snapshot.summary = "收藏名称或坐标无效。"
            return snapshot
        }
        guard snapshot.favorites.count < 50 else {
            snapshot.summary = "收藏已达 50 条上限。"
            return snapshot
        }
        snapshot.favorites.append(place)
        snapshot.summary = "已保存收藏。尚未发送到手机。"
        return snapshot
    }

    public func start(
        latitude: Double,
        longitude: Double,
        ip: String,
        pairingPath: String,
        confirm: Bool
    ) -> ControlSnapshot {
        guard confirm else {
            snapshot.summary = "未确认，坐标没有发送。"
            return snapshot
        }
        guard let coordinate = Coordinate(latitude: latitude, longitude: longitude) else {
            snapshot.commandAccepted = false
            snapshot.summary = "坐标超出范围，没有发送。"
            return snapshot
        }
        let path = pairingPath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else {
            snapshot.commandAccepted = false
            snapshot.summary = "没有配对文件路径，没有发送。"
            return snapshot
        }
        let code = port.set(ip: ip, latitude: coordinate.latitude, longitude: coordinate.longitude, pairingPath: path)
        snapshot.lastCode = code
        snapshot.phoneLocation = .unconfirmed
        snapshot.selected = coordinate
        if code == UpstreamFacts.locationStatusOK {
            snapshot.commandAccepted = true
            snapshot.sessionAlive = true
            snapshot.cleanupUnconfirmed = false
            snapshot.summary = "控制命令返回 0。会话标记为进行中。手机定位仍未能确认。"
        } else {
            snapshot.commandAccepted = false
            snapshot.sessionAlive = false
            snapshot.summary = "控制命令返回 \(code)。没有把进程存活当成定位成功。"
        }
        return snapshot
    }

    public func stop(confirm: Bool) -> ControlSnapshot {
        guard confirm else {
            snapshot.summary = "未确认，没有发送清除。"
            return snapshot
        }
        let code = port.clear()
        snapshot.lastCode = code
        snapshot.phoneLocation = .unconfirmed
        if code == UpstreamFacts.locationStatusOK {
            snapshot.commandAccepted = true
            snapshot.sessionAlive = false
            snapshot.cleanupUnconfirmed = false
            snapshot.summary = "清除命令返回 0。按上游调用约定这表示 clear 被接受。手机是否回到真实定位仍未能确认。"
        } else {
            snapshot.commandAccepted = false
            snapshot.cleanupUnconfirmed = true
            snapshot.summary = "清除命令返回 \(code)。不能确认已经恢复真实定位。"
        }
        return snapshot
    }

    /// A new process must not send the last coordinate again.
    public func noteProcessRestart() -> ControlSnapshot {
        snapshot.sessionAlive = false
        snapshot.summary = "进程已重新启动。上次坐标没有自动重发。手机定位未能确认。"
        return snapshot
    }
}

public enum LocationFailureGuide {
    public static func text(for code: Int32) -> String {
        switch code {
        case 0:
            return "返回 0 只表示这次调用没有报错。它不是手机坐标回读。"
        case 1:
            return "地址无法解析。上游默认回环地址是 10.7.0.1，来自 DeviceConnectionContext.swift。本仓库没有验证它和其他 VPN 是否冲突。"
        case 2:
            return "配对文件没有读入。文件应留在本机，不要把它贴到日志或仓库。"
        case 3:
            return "隧道提供者没有建立。上游界面把这类失败和 DDI、连接状态一起提示。这里没有真机结果。"
        case 9, 10, 11:
            return "定位服务调用失败。上游 MapSelectionView 写明需要设备已连接且 DDI 已挂载。该条件未在本环境验证。"
        case 12:
            return "没有可清除的定位会话，或 clear 调用失败。不能确认手机已恢复真实定位。"
        case UpstreamFacts.notLinked:
            return "返回 -50。默认工程不再用这个码代替真桥接；缺库应在编译或链接阶段失败。"
        default:
            return "未识别的返回码 \(code)。不要把它解释成定位已经生效。"
        }
    }
}

public struct InterfaceAddress: Equatable {
    public var name: String
    public var ipv4: String

    public init(name: String, ipv4: String) {
        self.name = name
        self.ipv4 = ipv4
    }
}

public enum LoopbackGuidance: Equatable {
    case addressPresent(interfaceName: String)
    case addressAbsent
}

public func loopbackGuidance(
    addresses: [InterfaceAddress],
    expected: String = UpstreamFacts.documentedLoopbackAddress
) -> LoopbackGuidance {
    if let match = addresses.first(where: { $0.ipv4 == expected }) {
        return .addressPresent(interfaceName: match.name)
    }
    return .addressAbsent
}

public func loopbackGuidanceText(_ guidance: LoopbackGuidance) -> String {
    switch guidance {
    case .addressPresent(let name):
        return "本机接口 \(name) 上有地址 10.7.0.1。这只说明地址存在，没有证明定位隧道可用，也没有和其他 VPN 做过对比。"
    case .addressAbsent:
        return "本机接口上没有 10.7.0.1。上游默认用 LocalDevVPN 提供这个回环地址。本程序不包含该 VPN，也没有验证它和其他 VPN 能否同时使用。"
    }
}

public enum FavoriteStoreError: Error, Equatable {
    case refusedSecretMaterial
}

public struct FavoriteStore {
    public let fileURL: URL

    public init(fileURL: URL) {
        self.fileURL = fileURL
    }

    public func load() throws -> [FavoritePlace] {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return [] }
        let data = try Data(contentsOf: fileURL)
        return try JSONDecoder().decode([FavoritePlace].self, from: data)
    }

    public func save(_ favorites: [FavoritePlace]) throws {
        let data = try JSONEncoder().encode(favorites)
        let text = String(data: data, encoding: .utf8) ?? ""
        if text.contains("BEGIN ") || text.contains("HostPrivateKey") || text.contains("RootPrivateKey") {
            throw FavoriteStoreError.refusedSecretMaterial
        }
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let temporary = directory.appendingPathComponent(UUID().uuidString + ".tmp")
        try data.write(to: temporary)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
        if FileManager.default.fileExists(atPath: fileURL.path) {
            _ = try FileManager.default.replaceItemAt(fileURL, withItemAt: temporary)
        } else {
            try FileManager.default.moveItem(at: temporary, to: fileURL)
        }
        try? FileManager.default.removeItem(at: temporary)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
    }
}
