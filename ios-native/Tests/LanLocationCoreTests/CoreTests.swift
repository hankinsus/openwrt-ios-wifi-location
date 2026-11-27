import XCTest
@testable import LanLocationCore

private final class RecordingPort: LocationCommandPort {
    var setCode: Int32 = 0
    var clearCode: Int32 = 0
    var sets: [(Double, Double)] = []
    var clears = 0

    func set(ip: String, latitude: Double, longitude: Double, pairingPath: String) -> Int32 {
        sets.append((latitude, longitude))
        return setCode
    }

    func clear() -> Int32 {
        clears += 1
        return clearCode
    }
}

final class CoreTests: XCTestCase {
    func testCoordinateBounds() {
        XCTAssertNotNil(Coordinate(latitude: -90, longitude: -180))
        XCTAssertNotNil(Coordinate(latitude: 90, longitude: 180))
        XCTAssertNil(Coordinate(latitude: 90.0001, longitude: 0))
        XCTAssertNil(Coordinate(latitude: .nan, longitude: 0))
        XCTAssertNil(Coordinate(latitude: .infinity, longitude: 1))
        XCTAssertNil(Coordinate(latitude: 1, longitude: .nan))
    }

    func testStartRequiresConfirmationAndDoesNotTreatAcceptanceAsPhoneFix() {
        let port = RecordingPort()
        let controller = LocationController(port: port)
        let blocked = controller.start(latitude: 10, longitude: 20, ip: "10.7.0.1", pairingPath: "secret.plist", confirm: false)
        XCTAssertTrue(port.sets.isEmpty)
        XCTAssertFalse(blocked.commandAccepted)
        XCTAssertEqual(blocked.phoneLocation, .unconfirmed)

        let accepted = controller.start(latitude: 10, longitude: 20, ip: "10.7.0.1", pairingPath: "secret.plist", confirm: true)
        XCTAssertEqual(port.sets.count, 1)
        XCTAssertTrue(accepted.commandAccepted)
        XCTAssertTrue(accepted.sessionAlive)
        XCTAssertEqual(accepted.phoneLocation, .unconfirmed)
        XCTAssertFalse(accepted.summary.contains("定位成功"))
    }

    func testRejectedCommandDoesNotLeaveSessionAlive() {
        let port = RecordingPort()
        port.setCode = 11
        let controller = LocationController(port: port)
        let snapshot = controller.start(latitude: 1, longitude: 2, ip: "10.7.0.1", pairingPath: "secret.plist", confirm: true)
        XCTAssertFalse(snapshot.commandAccepted)
        XCTAssertFalse(snapshot.sessionAlive)
        XCTAssertEqual(snapshot.phoneLocation, .unconfirmed)
        XCTAssertTrue(LocationFailureGuide.text(for: 11).contains("DDI"))
    }

    func testClearFailureStaysUnconfirmedAndRestartDoesNotReplay() {
        let port = RecordingPort()
        let controller = LocationController(port: port)
        _ = controller.start(latitude: -33.8, longitude: 151.2, ip: "10.7.0.1", pairingPath: "secret.plist", confirm: true)
        port.clearCode = 12
        let cleared = controller.stop(confirm: true)
        XCTAssertEqual(port.clears, 1)
        XCTAssertTrue(cleared.cleanupUnconfirmed)
        XCTAssertTrue(cleared.summary.contains("不能确认"))

        let restarted = controller.noteProcessRestart()
        XCTAssertFalse(restarted.sessionAlive)
        XCTAssertEqual(port.sets.count, 1)
        XCTAssertEqual(port.clears, 1)
    }

    func testEmptyPairingPathDoesNotCallPort() {
        let port = RecordingPort()
        let controller = LocationController(port: port)
        let snapshot = controller.start(latitude: 1, longitude: 2, ip: "10.7.0.1", pairingPath: "  ", confirm: true)
        XCTAssertTrue(port.sets.isEmpty)
        XCTAssertFalse(snapshot.commandAccepted)
        XCTAssertTrue(snapshot.summary.contains("配对文件"))
    }

    func testFavoritesAndPairingRoute() {
        let controller = LocationController(port: RecordingPort())
        let saved = controller.addFavorite(name: "门口", latitude: 31.2, longitude: 121.4)
        XCTAssertEqual(saved.favorites.count, 1)
        XCTAssertTrue(controller.addFavorite(name: "  ", latitude: 1, longitude: 2).summary.contains("无效"))
        XCTAssertEqual(pairingRoute(systemMajor: 26), .externalComputerRequired)
        XCTAssertEqual(
            pairingRoute(systemMajor: 27),
            .onDeviceWirelessDocumentedUntested(minimumMajor: 27)
        )
    }

    func testExportOmitsPairingMaterial() {
        let controller = LocationController(port: RecordingPort())
        _ = controller.addFavorite(name: "门口", latitude: 1, longitude: 2)
        let data = try? JSONEncoder().encode(controller.snapshot.favorites)
        let text = String(data: data ?? Data(), encoding: .utf8) ?? ""
        XCTAssertFalse(text.contains("BEGIN"))
        XCTAssertFalse(text.contains("HostPrivateKey"))
        XCTAssertTrue(text.contains("门口"))
    }

    func testFavoriteStoreRoundTripAndLoopbackGuidance() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("fav-\(UUID().uuidString).json")
        let store = FavoriteStore(fileURL: url)
        let controller = LocationController(port: RecordingPort())
        _ = controller.addFavorite(name: "门口", latitude: 1, longitude: 2)
        try store.save(controller.snapshot.favorites)
        XCTAssertEqual(try store.load(), controller.snapshot.favorites)
        let text = try String(contentsOf: url, encoding: .utf8)
        XCTAssertFalse(text.contains("HostPrivateKey"))
        XCTAssertFalse(text.contains("BEGIN "))
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let mode = (attributes[.posixPermissions] as? NSNumber)?.uint16Value
            ?? UInt16(attributes[.posixPermissions] as? Int ?? 0)
        XCTAssertEqual(mode & 0o777, 0o600)

        XCTAssertEqual(
            loopbackGuidance(addresses: [InterfaceAddress(name: "utun3", ipv4: "10.7.0.1")]),
            .addressPresent(interfaceName: "utun3")
        )
        XCTAssertEqual(
            loopbackGuidance(addresses: [InterfaceAddress(name: "en0", ipv4: "192.168.1.9")]),
            .addressAbsent
        )
        XCTAssertTrue(loopbackGuidanceText(.addressAbsent).contains("LocalDevVPN"))
        let reloaded = LocationController(port: RecordingPort())
        reloaded.replaceFavorites(try store.load())
        XCTAssertEqual(reloaded.snapshot.favorites.count, 1)
        XCTAssertFalse(reloaded.snapshot.sessionAlive)
    }
}
