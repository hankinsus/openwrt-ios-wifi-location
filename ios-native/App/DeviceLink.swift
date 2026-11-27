// Adapted from the location, tunnel, and DDI calls in
// StikDebug/Device/IdeviceFFIBridge.swift and JITEnableContext.swift
// at commit 63713ea2100660dc7066ee0e8d962858026f97aa.
// GNU AGPL-3.0. JIT, syslog, and process control are not included.
// The C API is idevice 0.1.68, whose header matches that commit.
// This file is in the default app target and imports the idevice module.
// A missing header or static library fails the Xcode build.

import Darwin
import Foundation
import idevice

struct IdeviceLocationCommandPort: LocationCommandPort {
    func set(ip: String, latitude: Double, longitude: Double, pairingPath: String) -> Int32 {
        DeviceLink.shared.simulate(ip: ip, latitude: latitude, longitude: longitude, pairingPath: pairingPath)
    }

    func clear() -> Int32 {
        DeviceLink.shared.clear()
    }
}

enum MountCheckResult: Equatable {
    case mounted
    case notMounted
    case unreachable(String)
}

final class DeviceLink {
    static let shared = DeviceLink()

    private let queue = DispatchQueue(label: "local.lanlocation.device")
    private var resendTimer: Timer?
    private var locationAdapter: OpaquePointer?
    private var locationHandshake: OpaquePointer?
    private var simulation: OpaquePointer?
    private var remoteServerStorage: OpaquePointer?
    private var mountAdapter: OpaquePointer?
    private var mountHandshake: OpaquePointer?

    private init() {}

    func simulate(ip: String, latitude: Double, longitude: Double, pairingPath: String) -> Int32 {
        queue.sync {
            simulateLocked(ip: ip, latitude: latitude, longitude: longitude, pairingPath: pairingPath)
        }
    }

    func clear() -> Int32 {
        queue.sync { clearLocked() }
    }

    func stopResend() {
        if Thread.isMainThread {
            resendTimer?.invalidate()
            resendTimer = nil
        } else {
            DispatchQueue.main.sync {
                self.resendTimer?.invalidate()
                self.resendTimer = nil
            }
        }
    }

    /// Repeats the same set call every 4 seconds, matching LocationSimulationSession.
    /// The timer lives only in this process. A relaunch does not start it.
    func startResend(
        ip: String,
        latitude: Double,
        longitude: Double,
        pairingPath: String,
        onCode: @escaping (Int32) -> Void
    ) {
        stopResend()
        let timer = Timer(timeInterval: 4, repeats: true) { [weak self] _ in
            self?.queue.async {
                let code = self?.simulateLocked(
                    ip: ip,
                    latitude: latitude,
                    longitude: longitude,
                    pairingPath: pairingPath
                ) ?? 12
                DispatchQueue.main.async {
                    onCode(code)
                }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        resendTimer = timer
    }

    func mountStatus() -> MountCheckResult {
        queue.sync { mountStatusLocked() }
    }

    func mountDeveloperDiskImage() -> String? {
        queue.sync { mountLocked() }
    }

    private func simulateLocked(ip: String, latitude: Double, longitude: Double, pairingPath: String) -> Int32 {
        if let simulation {
            if let error = location_simulation_set(simulation, latitude, longitude) {
                idevice_error_free(error)
                releaseLocationLocked()
            } else {
                return 0
            }
        }

        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(RemotePairingPortResolver.resolve(targetIPAddress: ip)).bigEndian
        guard ip.withCString({ inet_pton(AF_INET, $0, &address.sin_addr) }) == 1 else { return 1 }

        var pairing: OpaquePointer?
        if let error = pairingPath.withCString({ rp_pairing_file_read($0, &pairing) }) {
            idevice_error_free(error)
            return 2
        }
        guard let pairing else { return 2 }
        defer { rp_pairing_file_free(pairing) }

        let tunnelError = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                tunnel_create_rppairing(
                    $0,
                    socklen_t(MemoryLayout<sockaddr_in>.stride),
                    "LanLocation",
                    pairing,
                    nil,
                    nil,
                    &locationAdapter,
                    &locationHandshake
                )
            }
        }
        if let tunnelError {
            idevice_error_free(tunnelError)
            releaseLocationLocked()
            return 3
        }
        if let error = remote_server_connect_rsd(locationAdapter, locationHandshake, &remoteServerStorage) {
            idevice_error_free(error)
            releaseLocationLocked()
            return 9
        }
        if let error = location_simulation_new(remoteServerStorage, &simulation) {
            idevice_error_free(error)
            releaseLocationLocked()
            return 10
        }
        // Upstream drops this Swift reference without freeing. location_simulation_new
        // keeps the server it needs; freeing it here would not match that call.
        remoteServerStorage = nil
        if let error = location_simulation_set(simulation, latitude, longitude) {
            idevice_error_free(error)
            releaseLocationLocked()
            return 11
        }
        return 0
    }

    private func clearLocked() -> Int32 {
        guard let simulation else { return 12 }
        let error = location_simulation_clear(simulation)
        releaseLocationLocked()
        if let error {
            idevice_error_free(error)
            return 12
        }
        return 0
    }

    private func releaseLocationLocked() {
        if let simulation {
            location_simulation_free(simulation)
            self.simulation = nil
        }
        if let remoteServerStorage {
            remote_server_free(remoteServerStorage)
            self.remoteServerStorage = nil
        }
        if let locationHandshake {
            rsd_handshake_free(locationHandshake)
            self.locationHandshake = nil
        }
        if let locationAdapter {
            adapter_free(locationAdapter)
            self.locationAdapter = nil
        }
    }

    private func releaseMountTunnelLocked() {
        if let mountHandshake {
            rsd_handshake_free(mountHandshake)
            self.mountHandshake = nil
        }
        if let mountAdapter {
            adapter_free(mountAdapter)
            self.mountAdapter = nil
        }
    }

    private func ensureTunnel(pairingPath: String) throws {
        if mountAdapter == nil || mountHandshake == nil {
            try openTunnel(pairingPath: pairingPath)
        }
    }

    private func openTunnel(pairingPath: String) throws {
        let deviceIP = DeviceConnectionContext.targetIPAddress
        var pairing: OpaquePointer?
        if let error = pairingPath.withCString({ rp_pairing_file_read($0, &pairing) }) {
            throw bridgeError(error, fallback: "没有读入配对文件")
        }
        guard let pairing else {
            throw NSError(domain: "LanLocation", code: 2, userInfo: [NSLocalizedDescriptionKey: "没有读入配对文件"])
        }
        defer { rp_pairing_file_free(pairing) }

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        guard deviceIP.withCString({ inet_pton(AF_INET, $0, &address.sin_addr) }) == 1 else {
            throw NSError(domain: "LanLocation", code: 1, userInfo: [NSLocalizedDescriptionKey: "地址无法解析"])
        }
        let port = RemotePairingPortResolver.resolve(targetIPAddress: deviceIP)
        address.sin_port = port.bigEndian
        var storage = sockaddr_storage()
        withUnsafeMutableBytes(of: &storage) { raw in
            withUnsafeBytes(of: address) { raw.copyMemory(from: $0) }
        }
        var newAdapter: OpaquePointer?
        var newHandshake: OpaquePointer?
        let tunnelError = withUnsafePointer(to: &storage) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                tunnel_create_rppairing(
                    $0,
                    socklen_t(MemoryLayout<sockaddr_in>.size),
                    "LanLocation",
                    pairing,
                    nil,
                    nil,
                    &newAdapter,
                    &newHandshake
                )
            }
        }
        if let tunnelError {
            throw bridgeError(tunnelError, fallback: "隧道没有建立")
        }
        guard newAdapter != nil, newHandshake != nil else {
            throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "隧道没有返回句柄"])
        }
        releaseMountTunnelLocked()
        mountAdapter = newAdapter
        mountHandshake = newHandshake
    }

    private func mountStatusLocked() -> MountCheckResult {
        let path = PairingFileStore.prepareURL().path
        guard FileManager.default.fileExists(atPath: path) else {
            return .unreachable("没有配对文件，挂载状态问不了。")
        }
        do {
            try ensureTunnel(pairingPath: path)
        } catch {
            return .unreachable(error.localizedDescription)
        }
        guard let mountAdapter, let mountHandshake else {
            return .unreachable("隧道句柄是空的。")
        }
        var cryptexQuerySucceeded = false
        var cryptexQueryError: NSError?
        if DeveloperDiskImageService.usesCryptexDDI {
            var installed: UnsafeMutablePointer<InstalledCryptexC>?
            defer { cryptexd_free_installed_cryptex(installed) }
            if let error = cryptexd_installed_ddi(mountAdapter, mountHandshake, &installed) {
                cryptexQueryError = bridgeError(error, fallback: "查询 cryptex 镜像失败")
            } else {
                cryptexQuerySucceeded = true
                if installed != nil {
                    return .mounted
                }
            }
        }
        do {
            let mounted = try withImageMounter { client in
                var devices: UnsafeMutablePointer<plist_t?>?
                var deviceCount = 0
                if let error = image_mounter_copy_devices(client, &devices, &deviceCount) {
                    throw bridgeError(error, fallback: "读取已挂载镜像失败")
                }
                if let devices {
                    for index in 0..<deviceCount {
                        plist_free(devices[index])
                    }
                    idevice_data_free(
                        UnsafeMutableRawPointer(devices).assumingMemoryBound(to: UInt8.self),
                        UInt(deviceCount * MemoryLayout<plist_t?>.stride)
                    )
                }
                return deviceCount > 0
            }
            return mounted ? .mounted : .notMounted
        } catch {
            if cryptexQuerySucceeded {
                return .notMounted
            }
            return .unreachable((cryptexQueryError ?? (error as NSError)).localizedDescription)
        }
    }

    private func mountLocked() -> String? {
        let directory = DeveloperDiskImageService.directoryURL.path
        let pairingPath = PairingFileStore.prepareURL().path
        guard FileManager.default.fileExists(atPath: pairingPath) else {
            return "没有配对文件，没有开始挂载。"
        }
        do {
            if DeveloperDiskImageService.usesCryptexDDI {
                var assets: OpaquePointer?
                if let error = cryptex1_assets_load(directory, &assets) {
                    throw bridgeError(error, fallback: "没有载入 cryptex 镜像目录")
                }
                guard let assets else {
                    throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "cryptex 资源是空的"])
                }
                defer { cryptex1_assets_free(assets) }
                try ensureTunnel(pairingPath: pairingPath)
                guard let mountAdapter, let mountHandshake else {
                    throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "隧道句柄是空的"])
                }
                if let error = cryptexd_install_ddi(mountAdapter, mountHandshake, assets, nil) {
                    throw bridgeError(error, fallback: "安装 cryptex 镜像失败")
                }
            } else {
                let image = directory + "/Image.dmg"
                let trust = directory + "/Image.dmg.trustcache"
                let manifest = directory + "/BuildManifest.plist"
                let imageData = try Data(contentsOf: URL(fileURLWithPath: image), options: .mappedIfSafe)
                let trustData = try Data(contentsOf: URL(fileURLWithPath: trust), options: .mappedIfSafe)
                let manifestData = try Data(contentsOf: URL(fileURLWithPath: manifest), options: .mappedIfSafe)
                try ensureTunnel(pairingPath: pairingPath)
                guard let mountAdapter, let mountHandshake else {
                    throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "隧道句柄是空的"])
                }
                let chip = try withLockdown { client -> UInt64 in
                    var node: plist_t?
                    if let error = lockdownd_get_value(client, "UniqueChipID", nil, &node) {
                        throw bridgeError(error, fallback: "没有读到 UniqueChipID")
                    }
                    defer { plist_free(node) }
                    var value: UInt64 = 0
                    plist_get_uint_val(node, &value)
                    if value == 0 {
                        throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "UniqueChipID 是空的"])
                    }
                    return value
                }
                try withImageMounter { client in
                    let error = imageData.withUnsafeBytes { imageBuffer in
                        trustData.withUnsafeBytes { trustBuffer in
                            manifestData.withUnsafeBytes { manifestBuffer in
                                image_mounter_mount_personalized_rsd(
                                    client,
                                    mountAdapter,
                                    mountHandshake,
                                    imageBuffer.bindMemory(to: UInt8.self).baseAddress,
                                    imageData.count,
                                    trustBuffer.bindMemory(to: UInt8.self).baseAddress,
                                    trustData.count,
                                    manifestBuffer.bindMemory(to: UInt8.self).baseAddress,
                                    manifestData.count,
                                    nil,
                                    chip
                                )
                            }
                        }
                    }
                    if let error {
                        throw bridgeError(error, fallback: "挂载 personalized 镜像失败")
                    }
                }
            }
        } catch {
            return error.localizedDescription
        }
        return nil
    }

    private func withImageMounter<T>(_ body: (OpaquePointer) throws -> T) throws -> T {
        guard let mountAdapter, let mountHandshake else {
            throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "隧道句柄是空的"])
        }
        var client: OpaquePointer?
        if let error = image_mounter_connect_rsd(mountAdapter, mountHandshake, &client) {
            throw bridgeError(error, fallback: "没有连上镜像挂载服务")
        }
        guard let client else {
            throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "镜像挂载客户端是空的"])
        }
        defer { image_mounter_free(client) }
        return try body(client)
    }

    private func withLockdown<T>(_ body: (OpaquePointer) throws -> T) throws -> T {
        guard let mountAdapter, let mountHandshake else {
            throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "隧道句柄是空的"])
        }
        var client: OpaquePointer?
        if let error = lockdownd_connect_rsd(mountAdapter, mountHandshake, &client) {
            throw bridgeError(error, fallback: "没有连上 lockdownd")
        }
        guard let client else {
            throw NSError(domain: "LanLocation", code: 3, userInfo: [NSLocalizedDescriptionKey: "lockdownd 客户端是空的"])
        }
        defer { lockdownd_client_free(client) }
        return try body(client)
    }

    private func bridgeError(_ error: UnsafeMutablePointer<IdeviceFfiError>?, fallback: String) -> NSError {
        guard let error else {
            return NSError(domain: "LanLocation", code: -1, userInfo: [NSLocalizedDescriptionKey: fallback])
        }
        let detail = error.pointee.message.flatMap { String(validatingUTF8: $0) } ?? fallback
        let code = Int(error.pointee.code)
        idevice_error_free(error)
        return NSError(domain: "LanLocation", code: code, userInfo: [NSLocalizedDescriptionKey: detail])
    }
}
