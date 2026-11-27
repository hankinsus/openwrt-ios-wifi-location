// Adapted from StikDebug/Device/JITEnableContext.swift
// commit 63713ea2100660dc7066ee0e8d962858026f97aa.
// GNU AGPL-3.0. Only the remote-pairing port resolver and paired-device
// discovery are kept. JIT, syslog, and process control from that file are not.

import Darwin
import Foundation
import Network

enum DeviceConnectionContext {
    static let defaultTargetIPAddress = "10.7.0.1"
    static let storageKey = "LanLocation.targetDeviceIP"

    static var targetIPAddress: String {
        let stored = UserDefaults.standard
            .string(forKey: storageKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard let stored, !stored.isEmpty else {
            return defaultTargetIPAddress
        }
        return stored
    }
}

final class RemotePairingPortResolver {
    static let fallback: UInt16 = 49152
    private static let overrideKey = "TunnelRemotePairingPort"
    private static let stateLock = NSLock()
    private static var selectedEndpoint = "Not attempted yet"

    /// The precise port and discovery method used for the latest connection attempt.
    static var lastAttemptDescription: String {
        stateLock.lock()
        defer { stateLock.unlock() }
        return selectedEndpoint
    }

    private static func record(targetIPAddress: String, port: UInt16, source: String) {
        let endpoint = "\(targetIPAddress):\(port) (\(source))"
        stateLock.lock()
        selectedEndpoint = endpoint
        stateLock.unlock()
        NSLog("[LanLocation] Remote Pairing selected endpoint: %@", endpoint)
    }

    private let discoveryQueue = DispatchQueue(label: "local.lanlocation.remotePairingDiscovery")
    private let completion = DispatchSemaphore(value: 0)
    private var browser: NWBrowser?
    private var connection: NWConnection?
    private var selectedService: NWEndpoint?
    private var selectedLoopback = false
    private var resolvedPort: UInt16?
    private var finished = false

    static func resolve(targetIPAddress: String = DeviceConnectionContext.targetIPAddress, timeout: TimeInterval = 5) -> UInt16 {
        let override = (UserDefaults.standard.string(forKey: overrideKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if !override.isEmpty, let port = UInt16(override), port != 0 {
            record(targetIPAddress: targetIPAddress, port: port, source: "Manual")
            return port
        }
        if !override.isEmpty {
            NSLog("[LanLocation] Ignoring invalid manual Remote Pairing port: %@", override)
        }

        let result = discover(targetIPAddress: targetIPAddress, timeout: timeout)
        record(targetIPAddress: targetIPAddress, port: result.port, source: result.source)
        return result.port
    }

    static func discover(targetIPAddress: String = DeviceConnectionContext.targetIPAddress, timeout: TimeInterval = 5) -> (port: UInt16, source: String) {
        if targetIPAddress != DeviceConnectionContext.defaultTargetIPAddress {
            var peer = sockaddr_in()
            peer.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            peer.sin_family = UInt8(AF_INET)
            guard targetIPAddress.withCString({ inet_pton(AF_INET, $0, &peer.sin_addr) }) == 1 else { return (fallback, "Fallback") }
            let address = withUnsafeBytes(of: &peer) { Data($0) }
            guard let resolved = try? PairedDeviceDiscovery(address: address).resolve(timeout: timeout),
                  resolved.count == MemoryLayout<sockaddr_in>.size else { return (fallback, "Fallback") }
            withUnsafeMutableBytes(of: &peer) { _ = resolved.copyBytes(to: $0) }
            let port = UInt16(bigEndian: peer.sin_port)
            return port == 0 ? (fallback, "Fallback") : (port, "Bonjour")
        }
        let worker = RemotePairingPortResolver()
        worker.discoveryQueue.async {
            worker.startDiscovery()
        }
        _ = worker.completion.wait(timeout: .now() + timeout)
        return worker.discoveryQueue.sync {
            worker.finishDiscovery()
            if let port = worker.resolvedPort {
                return (port, "Bonjour")
            }
            return (fallback, "Fallback")
        }
    }

    private static func preferredCandidate(
        from candidates: [(endpoint: NWEndpoint, isLoopback: Bool)]
    ) -> (endpoint: NWEndpoint, isLoopback: Bool)? {
        candidates.first(where: { $0.isLoopback }) ?? candidates.first
    }

    private func startDiscovery() {
        guard !finished else { return }
        let parameters = NWParameters.tcp
        parameters.includePeerToPeer = true
        let browser = NWBrowser(
            for: .bonjour(type: "_remotepairing._tcp", domain: "local."),
            using: parameters
        )
        self.browser = browser
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            guard let self, !self.finished else { return }
            let candidates = results.compactMap { result -> (endpoint: NWEndpoint, isLoopback: Bool)? in
                guard case .service = result.endpoint else { return nil }
                let isLoopback = result.interfaces.contains { $0.name.hasPrefix("lo") }
                return (result.endpoint, isLoopback)
            }
            guard let selected = Self.preferredCandidate(from: candidates),
                  self.selectedService == nil || (!self.selectedLoopback && selected.isLoopback) else {
                return
            }
            self.selectedService = selected.endpoint
            self.selectedLoopback = selected.isLoopback
            self.connection?.cancel()
            let connection = NWConnection(to: selected.endpoint, using: parameters)
            self.connection = connection
            connection.pathUpdateHandler = { [weak self, weak connection] path in
                guard let self, let connection, self.connection === connection, !self.finished else { return }
                if path.status == .satisfied {
                    self.recordResolvedPort(from: connection)
                }
            }
            connection.stateUpdateHandler = { [weak self, weak connection] state in
                guard let self, let connection, self.connection === connection, !self.finished else { return }
                switch state {
                case .ready, .waiting:
                    self.recordResolvedPort(from: connection)
                case .failed:
                    self.finishDiscovery()
                default:
                    break
                }
            }
            connection.start(queue: self.discoveryQueue)
        }
        browser.stateUpdateHandler = { [weak self] state in
            if case .failed = state {
                self?.finishDiscovery()
            }
        }
        browser.start(queue: discoveryQueue)
    }

    private func recordResolvedPort(from connection: NWConnection) {
        guard case .hostPort(_, let port) = connection.currentPath?.remoteEndpoint,
              port.rawValue != 0 else { return }
        resolvedPort = port.rawValue
        finishDiscovery()
    }

    private func finishDiscovery() {
        guard !finished else { return }
        finished = true
        browser?.cancel()
        connection?.cancel()
        completion.signal()
    }

}

struct PairingPlacementTarget: Sendable {
    let pairingFileURL: URL
    let address: Data
    let hostname: String
}

final class PairedDeviceDiscovery: NSObject, NetServiceBrowserDelegate, NetServiceDelegate {
    private let browser = NetServiceBrowser()
    private var services: [NetService] = []
    private let peerHost: String?
    private var resolvedAddress: Data?

    init(address: Data) {
        peerHost = Self.numericHost(address)
        super.init()
        browser.delegate = self
        browser.includesPeerToPeer = true
    }

    static func numericHost(_ address: Data) -> String? {
        guard address.count >= MemoryLayout<sockaddr>.size else { return nil }
        return address.withUnsafeBytes { bytes in
            let socketAddress = bytes.baseAddress!.assumingMemoryBound(to: sockaddr.self)
            let family = Int32(socketAddress.pointee.sa_family)
            let length: Int
            switch family {
            case AF_INET: length = MemoryLayout<sockaddr_in>.size
            case AF_INET6: length = MemoryLayout<sockaddr_in6>.size
            default: return nil
            }
            guard address.count >= length else { return nil }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            guard getnameinfo(socketAddress, socklen_t(length), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 else { return nil }
            return String(cString: host)
        }
    }

    func resolve(timeout: TimeInterval = 8) throws -> Data {
        guard peerHost != nil else {
            throw NSError(domain: "LanLocation", code: -18, userInfo: [NSLocalizedDescriptionKey: "The paired device has an invalid network address."])
        }
        browser.searchForServices(ofType: "_remotepairing._tcp.", inDomain: "local.")
        defer {
            browser.stop()
            services.forEach { $0.stop() }
        }
        let deadline = Date().addingTimeInterval(timeout)
        while resolvedAddress == nil && Date() < deadline {
            RunLoop.current.run(until: min(deadline, Date().addingTimeInterval(0.05)))
        }
        guard let resolvedAddress else {
            throw NSError(domain: "LanLocation", code: -19, userInfo: [NSLocalizedDescriptionKey: "Could not discover the paired device. Keep both devices on the same Wi-Fi network and try again."])
        }
        return resolvedAddress
    }

    func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
        services.append(service)
        service.includesPeerToPeer = true
        service.delegate = self
        service.resolve(withTimeout: 6)
    }

    func netServiceDidResolveAddress(_ sender: NetService) {
        if let address = sender.addresses?.first(where: { Self.numericHost($0) == peerHost }) {
            resolvedAddress = address
        }
    }
}
