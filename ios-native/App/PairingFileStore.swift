// Adapted from StikDebug/Support/PairingFileStore.swift
// commit 63713ea2100660dc7066ee0e8d962858026f97aa.
// GNU AGPL-3.0.
// Change: the pairing file is stored only under Application Support,
// with complete file protection, mode 0600, and backup exclusion.
// The upstream copy in Documents is not made.

import Foundation
import UniformTypeIdentifiers

enum PairingFileStore {
    static let fileName = "pairingFile.plist"
    static let supportedContentTypes: [UTType] = [
        UTType(filenameExtension: "mobiledevicepairing", conformingTo: .data)!,
        UTType(filenameExtension: "mobiledevicepair", conformingTo: .data)!,
        .propertyList
    ]

    static var url: URL {
        directoryURL.appendingPathComponent(fileName)
    }

    static func prepareURL(fileManager: FileManager = .default) -> URL {
        try? fileManager.createDirectory(at: directoryURL, withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: url.path) {
            protect(url, fileManager: fileManager)
        }
        return url
    }

    static func fileExists(fileManager: FileManager = .default) -> Bool {
        fileManager.fileExists(atPath: prepareURL(fileManager: fileManager).path)
    }

    static func replace(with sourceURL: URL, fileManager: FileManager = .default) throws {
        try fileManager.createDirectory(at: directoryURL, withIntermediateDirectories: true)
        if sourceURL.standardizedFileURL == url.standardizedFileURL {
            protect(url, fileManager: fileManager)
            return
        }
        let temporary = directoryURL.appendingPathComponent(UUID().uuidString + ".tmp")
        try? fileManager.removeItem(at: temporary)
        defer { try? fileManager.removeItem(at: temporary) }
        try fileManager.copyItem(at: sourceURL, to: temporary)
        if fileManager.fileExists(atPath: url.path) {
            _ = try fileManager.replaceItemAt(url, withItemAt: temporary)
        } else {
            try fileManager.moveItem(at: temporary, to: url)
        }
        protect(url, fileManager: fileManager)
    }

    static func importFromPicker(_ sourceURL: URL, fileManager: FileManager = .default) throws {
        let accessing = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if accessing {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }
        guard fileManager.fileExists(atPath: sourceURL.path) else {
            throw CocoaError(.fileNoSuchFile)
        }
        try replace(with: sourceURL, fileManager: fileManager)
    }

    private static var directoryURL: URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LanLocation/Pairing", isDirectory: true)
    }

    private static func protect(_ url: URL, fileManager: FileManager) {
        try? fileManager.setAttributes(
            [
                .posixPermissions: 0o600,
                .protectionKey: FileProtectionType.complete
            ],
            ofItemAtPath: url.path
        )
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutable = url
        try? mutable.setResourceValues(values)
    }
}
