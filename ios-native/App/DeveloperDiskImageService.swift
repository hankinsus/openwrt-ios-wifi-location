// Adapted from StikDebug/Services/DeveloperDiskImageService.swift
// commit 63713ea2100660dc7066ee0e8d962858026f97aa.
// GNU AGPL-3.0.
// The download URLs are the ones in that file. This adaptation stores the
// images under Application Support and does not claim a device mount.

import Foundation

final class DeveloperDiskImageService {
    static let shared = DeveloperDiskImageService()

    static var directoryURL: URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LanLocation/DDI", isDirectory: true)
    }

    static var filesAreReady: Bool {
        downloadItems.allSatisfy {
            FileManager.default.fileExists(atPath: directoryURL.appendingPathComponent($0.fileName).path)
        } && UserDefaults.standard.string(forKey: mountMethodKey) == mountMethod.rawValue
    }

    static var usesCryptexDDI: Bool {
        mountMethod == .cryptex
    }

    private let fileManager: FileManager
    private let session: URLSession

    init(fileManager: FileManager = .default, session: URLSession = .shared) {
        self.fileManager = fileManager
        self.session = session
    }

    func downloadMissingFiles() async throws {
        let installedMethod = UserDefaults.standard.string(forKey: Self.mountMethodKey)
        let replaceFiles = installedMethod != Self.mountMethod.rawValue
        if replaceFiles {
            UserDefaults.standard.removeObject(forKey: Self.mountMethodKey)
        }
        if !Self.usesCryptexDDI {
            try removeCryptexOnlyFiles()
        }
        for item in Self.downloadItems {
            let destinationURL = Self.directoryURL.appendingPathComponent(item.fileName)
            guard replaceFiles || !fileManager.fileExists(atPath: destinationURL.path) else { continue }
            try await downloadFile(from: item.urlString, to: destinationURL)
        }
        UserDefaults.standard.set(Self.mountMethod.rawValue, forKey: Self.mountMethodKey)
    }

    private func downloadFile(from urlString: String, to destinationURL: URL) async throws {
        guard let url = URL(string: urlString), url.scheme?.lowercased() == "https" else {
            throw DDIDownloadError.invalidURL(urlString)
        }
        let (temporaryURL, response) = try await session.download(from: url)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw DDIDownloadError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw DDIDownloadError.badStatus(httpResponse.statusCode)
        }
        try fileManager.createDirectory(at: destinationURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        if fileManager.fileExists(atPath: destinationURL.path) {
            try fileManager.removeItem(at: destinationURL)
        }
        try fileManager.moveItem(at: temporaryURL, to: destinationURL)
    }

    private func removeCryptexOnlyFiles() throws {
        for fileName in Self.cryptexOnlyFileNames {
            let fileURL = Self.directoryURL.appendingPathComponent(fileName)
            if fileManager.fileExists(atPath: fileURL.path) {
                try fileManager.removeItem(at: fileURL)
            }
        }
    }

    private static var mountMethod: DDIMountMethod {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        return version.majorVersion > 26 || (version.majorVersion == 26 && version.minorVersion >= 4)
            ? .cryptex
            : .personalized
    }

    private static let mountMethodKey = "LanLocation.DDIMountMethod"
    private static let cryptexOnlyFileNames = ["Image.dmg.cryptex_info", "Image.dmg.root_hash"]

    private static var downloadItems: [DDIDownloadItem] {
        switch mountMethod {
        case .cryptex:
            return cryptexDownloadItems
        case .personalized:
            return personalizedDownloadItems
        }
    }

    private static let cryptexDownloadItems: [DDIDownloadItem] = [
        .init(name: "Build Manifest", fileName: "BuildManifest.plist", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Cryptex/BuildManifest.plist"),
        .init(name: "Image", fileName: "Image.dmg", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Cryptex/Image.dmg"),
        .init(name: "TrustCache", fileName: "Image.dmg.trustcache", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Cryptex/Image.dmg.trustcache"),
        .init(name: "Cryptex Info", fileName: "Image.dmg.cryptex_info", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Cryptex/Image.dmg.cryptex_info"),
        .init(name: "Root Hash", fileName: "Image.dmg.root_hash", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Cryptex/Image.dmg.root_hash")
    ]

    private static let personalizedDownloadItems: [DDIDownloadItem] = [
        .init(name: "Build Manifest", fileName: "BuildManifest.plist", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Personalized/BuildManifest.plist"),
        .init(name: "Image", fileName: "Image.dmg", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Personalized/Image.dmg"),
        .init(name: "TrustCache", fileName: "Image.dmg.trustcache", urlString: "https://github.com/doronz88/DeveloperDiskImage/raw/refs/heads/main/PersonalizedImages/Xcode_iOS_DDI_Personalized/Image.dmg.trustcache")
    ]
}

private enum DDIMountMethod: String {
    case cryptex
    case personalized
}

private struct DDIDownloadItem {
    let name: String
    let fileName: String
    let urlString: String
}

enum DDIDownloadError: LocalizedError {
    case invalidURL(String)
    case invalidResponse
    case badStatus(Int)

    var errorDescription: String? {
        switch self {
        case .invalidURL(let string):
            return "下载地址无效：\(string)"
        case .invalidResponse:
            return "镜像服务器没有返回 HTTP 响应。"
        case .badStatus(let statusCode):
            return "镜像服务器返回 HTTP \(statusCode)。"
        }
    }
}
