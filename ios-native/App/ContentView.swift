import Darwin
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @State private var controller: LocationController
    @State private var snapshot: ControlSnapshot
    @ObservedObject private var pairing = OnDevicePairingService.shared
    @State private var latitude = ""
    @State private var longitude = ""
    @State private var favoriteName = ""
    @State private var advancedPath = ""
    @State private var addressText = ""
    @State private var confirmSend = false
    @State private var importing = false
    @State private var pairingMessage = "还没有导入配对文件。"
    @State private var ddiMessage = "还没有下载或挂载开发者磁盘镜像。"
    @State private var isBusy = false
    @State private var loopbackText = ""

    init(controller: LocationController) {
        _controller = State(initialValue: controller)
        let store = FavoriteStore(fileURL: Self.favoritesURL())
        if let loaded = try? store.load() {
            controller.replaceFavorites(loaded)
        }
        _snapshot = State(initialValue: controller.snapshot)
        _addressText = State(initialValue: DeviceConnectionContext.targetIPAddress)
    }

    var body: some View {
        NavigationStack {
            Form {
                statusSection
                pairingSection
                connectionSection
                diskImageSection
                coordinateSection
                advancedSection
                Section("许可与安装") {
                    Text("本程序基于 StikDebug 提交 \(UpstreamFacts.commit) 改编，许可证是 AGPL-3.0。idevice 0.1.68 是 MIT。没有担保。完整许可证随源码提供。")
                        .font(.footnote)
                    Text("装到自己的手机时，在 Xcode 里选免费 Apple ID 的 Personal Team 即可，付费开发者计划不是前提。免费描述文件大约 7 天过期。本程序没有 Apple ID 登录，也不在到期后自己重新签名。SideStore 能否刷新，还没有真机结果。")
                        .font(.footnote)
                }
            }
            .navigationTitle("本机定位")
            .fileImporter(isPresented: $importing, allowedContentTypes: PairingFileStore.supportedContentTypes) { result in
                switch result {
                case .success(let url):
                    do {
                        try PairingFileStore.importFromPicker(url)
                        pairingMessage = "已把配对文件放进受保护存储。内容不会显示。"
                    } catch {
                        pairingMessage = "导入没有完成：\(error.localizedDescription)"
                    }
                case .failure(let error):
                    pairingMessage = "没有选择文件：\(error.localizedDescription)"
                }
            }
            .onAppear {
                loopbackText = loopbackGuidanceText(LoopbackReader.guidance())
                pairingMessage = PairingFileStore.fileExists() ? "已有受保护的配对文件。内容不会显示。" : pairingMessage
            }
        }
    }

    private var statusSection: some View {
        Section("状态") {
            Text(snapshot.commandAccepted ? "控制命令：调用返回 0" : "控制命令：尚未接受或上次失败")
            Text(snapshot.sessionAlive ? "会话：本机标记为进行中" : "会话：没有在进行")
            Text("手机定位：未能确认")
            Text(snapshot.cleanupUnconfirmed ? "恢复：清除没有返回 0，不能确认已经回到真实定位" : "恢复：没有未确认的清除失败")
            Text(snapshot.summary).font(.footnote)
            if let code = snapshot.lastCode {
                Text(LocationFailureGuide.text(for: code)).font(.footnote)
            }
            Text("命令被接受后，本进程每 4 秒再发一次。没有复制后台音频和后台定位保活，系统挂起后不会继续。重新打开应用不会自动重发。")
                .font(.footnote)
        }
    }

    private var pairingSection: some View {
        Section("配对") {
            Text(pairingMessage).font(.footnote)
            Text("PAIRING.md 写：iOS 或 iPadOS 27 及以上可以在设备上生成配对文件；其他情况用电脑上的 iloader，并建议先接数据线。源码里的 iOS 27 条件只包住通知和后台保活，配对函数在条件外调用。本程序保留这条配对调用，但没有在真机上跑过。")
                .font(.footnote)
            Button("导入配对文件") { importing = true }
            Button("在本机生成配对文件") {
                pairing.start(discoverAppleTVs: false)
            }
            .disabled(pairing.phase.isRunning)
            if pairing.phase.isRunning {
                Button("取消配对") { pairing.cancel() }
            }
            pairingPhase
        }
    }

    @ViewBuilder
    private var pairingPhase: some View {
        switch pairing.phase {
        case .idle:
            EmptyView()
        case .discovering, .waiting:
            ProgressView()
            Text("在被配对的设备上打开设置，进入隐私与安全性、开发者模式，点按与 \(pairing.hostname) 配对，再输入本页或通知里的代码。")
                .font(.footnote)
        case .pin(let pin):
            Text("输入这个代码").font(.headline)
            Text(pin).font(.system(size: 40, weight: .bold, design: .rounded))
        case .appleTVPIN:
            Text("Apple TV 配对码流程还在改编后的服务里，主界面不走这条。").font(.footnote)
        case .success(let name, _, let isLocal):
            Text(isLocal ? "本机配对调用已返回。文件在受保护存储里，内容不显示。" : "配对调用已返回：\(name)。这不是定位已经生效。")
        case .failed(let message):
            Text("配对没有完成：\(message)")
        }
    }

    private var connectionSection: some View {
        Section("连接") {
            Text(loopbackText).font(.footnote)
            Text("最近一次端口选择：\(RemotePairingPortResolver.lastAttemptDescription)")
                .font(.footnote)
            Button("重新检查本机地址") {
                loopbackText = loopbackGuidanceText(LoopbackReader.guidance())
            }
        }
    }

    private var diskImageSection: some View {
        Section("开发者磁盘镜像") {
            Text(DeveloperDiskImageService.filesAreReady ? "本地镜像文件按当前系统版本的清单已经齐。" : "本地镜像文件还不齐，或系统版本对应的清单变了。")
            Text(ddiMessage).font(.footnote)
            Button("下载缺失的镜像") { downloadImages() }
            Button("按接口挂载") { mountImages() }
                .disabled(isBusy)
            Button("查询挂载状态") { queryMount() }
                .disabled(isBusy)
        }
    }

    private var coordinateSection: some View {
        Section("坐标") {
            TextField("纬度", text: $latitude)
                .keyboardType(.numbersAndPunctuation)
            TextField("经度", text: $longitude)
                .keyboardType(.numbersAndPunctuation)
            TextField("收藏名称", text: $favoriteName)
            Button("保存收藏") { saveFavorite() }
            if snapshot.favorites.isEmpty {
                Text("还没有收藏。").font(.footnote)
            }
            ForEach(snapshot.favorites) { place in
                Button("\(place.name)  \(place.coordinate.latitude), \(place.coordinate.longitude)") {
                    latitude = String(place.coordinate.latitude)
                    longitude = String(place.coordinate.longitude)
                }
            }
            Toggle("我确认发送开始或停止", isOn: $confirmSend)
            Button("开始") { start() }
                .disabled(isBusy)
            Button("停止并请求恢复真实定位") { stop() }
                .disabled(isBusy)
        }
    }

    private var advancedSection: some View {
        Section("高级") {
            Text("普通使用走上面的导入或本机配对。这里的路径和地址只留作开发选项，不会写进收藏文件。")
                .font(.footnote)
            TextField("配对文件路径", text: $advancedPath)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            TextField("目标地址", text: $addressText)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("记住这个目标地址") {
                let trimmed = addressText.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.isEmpty {
                    UserDefaults.standard.removeObject(forKey: DeviceConnectionContext.storageKey)
                    addressText = DeviceConnectionContext.defaultTargetIPAddress
                } else {
                    UserDefaults.standard.set(trimmed, forKey: DeviceConnectionContext.storageKey)
                }
                snapshot.summary = "目标地址已更新。还没有发送定位命令。"
            }
        }
    }

    private func activePairingPath() -> String {
        let typed = advancedPath.trimmingCharacters(in: .whitespacesAndNewlines)
        if !typed.isEmpty { return typed }
        let url = PairingFileStore.prepareURL()
        return FileManager.default.fileExists(atPath: url.path) ? url.path : ""
    }

    private func parsed() -> (Double, Double)? {
        guard let lat = Double(latitude), let lon = Double(longitude) else { return nil }
        return (lat, lon)
    }

    private func saveFavorite() {
        guard let values = parsed() else {
            snapshot.summary = "纬度或经度不是数字，没有保存。"
            return
        }
        snapshot = controller.addFavorite(name: favoriteName, latitude: values.0, longitude: values.1)
        do {
            try FavoriteStore(fileURL: Self.favoritesURL()).save(snapshot.favorites)
        } catch {
            snapshot.summary = "收藏没有写入磁盘：\(error.localizedDescription)"
        }
    }

    private func start() {
        guard let values = parsed() else {
            snapshot.summary = "纬度或经度不是数字，没有发送。"
            return
        }
        let path = activePairingPath()
        let ip = DeviceConnectionContext.targetIPAddress
        let confirmed = confirmSend
        isBusy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let next = controller.start(
                latitude: values.0,
                longitude: values.1,
                ip: ip,
                pairingPath: path,
                confirm: confirmed
            )
            DispatchQueue.main.async {
                snapshot = next
                isBusy = false
                guard next.commandAccepted else {
                    DeviceLink.shared.stopResend()
                    return
                }
                DeviceLink.shared.startResend(ip: ip, latitude: values.0, longitude: values.1, pairingPath: path) { code in
                    guard code != 0 else { return }
                    DeviceLink.shared.stopResend()
                    snapshot.commandAccepted = false
                    snapshot.sessionAlive = false
                    snapshot.phoneLocation = .unconfirmed
                    snapshot.lastCode = code
                    snapshot.summary = "重复发送返回 \(code)。会话不再标记为进行中。手机定位仍未能确认。"
                }
            }
        }
    }

    private func stop() {
        let confirmed = confirmSend
        guard confirmed else {
            snapshot = controller.stop(confirm: false)
            return
        }
        DeviceLink.shared.stopResend()
        isBusy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let next = controller.stop(confirm: true)
            DispatchQueue.main.async {
                snapshot = next
                isBusy = false
            }
        }
    }

    private func downloadImages() {
        ddiMessage = "正在下载镜像。这一步还不是挂载成功。"
        Task {
            do {
                try await DeveloperDiskImageService.shared.downloadMissingFiles()
                ddiMessage = "下载函数已返回。还要单独挂载，而且这里不能代替真机结果。"
            } catch {
                ddiMessage = "下载没有完成：\(error.localizedDescription)"
            }
        }
    }

    private func mountImages() {
        isBusy = true
        ddiMessage = "正在调用挂载接口。"
        DispatchQueue.global(qos: .userInitiated).async {
            let failure = DeviceLink.shared.mountDeveloperDiskImage()
            DispatchQueue.main.async {
                isBusy = false
                if let failure {
                    ddiMessage = "挂载调用没有成功：\(failure)"
                } else {
                    ddiMessage = "挂载调用返回时没有错误。这不是手机坐标回读，也没有在这台开发机上验证。"
                }
            }
        }
    }

    private func queryMount() {
        isBusy = true
        DispatchQueue.global(qos: .userInitiated).async {
            let status = DeviceLink.shared.mountStatus()
            DispatchQueue.main.async {
                isBusy = false
                switch status {
                case .mounted:
                    ddiMessage = "挂载查询接口返回：已挂载。这不是定位坐标确认。"
                case .notMounted:
                    ddiMessage = "挂载查询接口返回：未挂载。"
                case .unreachable(let message):
                    ddiMessage = "挂载状态问不到：\(message)"
                }
            }
        }
    }

    private static func favoritesURL() -> URL {
        FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LanLocation/favorites.json")
    }
}

enum LoopbackReader {
    static func guidance() -> LoopbackGuidance {
        loopbackGuidance(addresses: interfaces())
    }

    static func interfaces() -> [InterfaceAddress] {
        var head: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&head) == 0, let first = head else { return [] }
        defer { freeifaddrs(first) }
        var found: [InterfaceAddress] = []
        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let item = cursor {
            if let address = item.pointee.ifa_addr, address.pointee.sa_family == UInt8(AF_INET) {
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                let length = socklen_t(address.pointee.sa_len)
                if getnameinfo(address, length, &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                    found.append(InterfaceAddress(name: String(cString: item.pointee.ifa_name), ipv4: String(cString: host)))
                }
            }
            cursor = item.pointee.ifa_next
        }
        return found
    }
}
