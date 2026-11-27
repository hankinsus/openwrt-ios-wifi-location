# ios-wifi-loc 0.2.1

在 NanoPi R4S 上，把这个目录传上去之后只跑一条：

```bash
sh scripts/oneclick-install.sh --interface br-lan
```

它会识别 OpenWrt（看 `/etc/openwrt_release`，用 `opkg`，OpenWrt 24.10+ 则用 `apk`）或 Debian/Ubuntu（`apt-get`），先打印要装的包、内存和磁盘，再补齐 Python 3.9+、pip 和 usbmuxd。优先创建 venv；OpenWrt 上没有 venv 模块时改把依赖装进隔离目录，不写入系统 site-packages。然后安装本工具和 `requirements-upstream.txt` 里的 pymobiledevice3，运行 preflight，并写入 procd 或 systemd。局域网访问用 `--interface br-lan`，只绑定这块网卡，不监听 `0.0.0.0`。

先看会做什么，不改系统：

```bash
sh scripts/oneclick-install.sh --interface br-lan --dry-run
```

卸掉启动脚本和隔离环境。不卸载系统里的 Python，也不改防火墙。默认保留口令；`--purge-state` 才删状态目录：

```bash
sh scripts/oneclick-uninstall.sh
```

这条安装没有在真机 R4S 或 OpenWrt 上跑过。下面的包管理器测试用的是替身命令。

iPhone 本机精简版在 `ios-native/`，许可证是 AGPL-3.0，和这个 Python 控制台不是同一个程序。本机程序用免费 Apple ID 侧载，描述文件大约 7 天有效；付费开发者计划不是前提。这个 Python 控制台不在 R4S 上安装该 App，因此没有该 App 的 7 天签名。手机开发者模式是系统开关，不是会员。

在同一局域网里，用浏览器控制 iPhone 的开发者定位模拟。日常不需要再敲定位命令。

手机协议仍由上游 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 11.63.1 执行。本工具不改路由、防火墙或 PassWall，不刷固件，不读取配对文件，也不使用 Apple ID。

公开仓库目标仍是 <https://github.com/ilovestudyus-sketch/openwrt-ios-wifi-location>。当前环境没有 GitHub 登录凭据，这一版也没有推上去，该仓库会保持为空，直到 Cursor 的 GitHub 连接把写入权限交给 git。

## 安装时做了什么

`preflight` 报告架构、内存和初始化系统。内存很低或系统是 OpenWrt 时会警告，不会因此声称上游已经能跑。

OpenWrt 写入 procd 脚本，Debian/Ubuntu 写入 systemd 单元。两者都只把网页进程拉起来，失败后有限次重试。进程重启不会重新发送坐标。编译用的 gcc、头文件和 libimobiledevice 只在 pymobiledevice3 不能直接装上时才补。

默认只监听 `127.0.0.1:47321`。口令在状态目录的 `web.secret`，文件权限是 `0600`。安装输出只打印这个路径。

128MB/MIPS 的 XE300 仍然不承诺能跑上游。

手动安装仍然可以，效果和上面那条命令相同：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install .
python3 -m pip install -r requirements-upstream.txt
python3 -m ios_wifi_loc preflight
sh scripts/install.sh --root / --state-dir /var/lib/ios-wifi-loc --interface br-lan
```

## 首次配对

网页里的“首次配对”说明来自当前上游文档，安装后的 `pymobiledevice3 remote pair-host --help` 也写着 iOS 27+ 的手机发起配对。那不是“所有 iPhone 都不用 USB”的结论，这里也没有配过真机。

普通 iPhone 仍按上游的做法：插上数据线，由你在手机上确认信任和开发者模式，再执行一次 `lockdown wifi-connections on`。需要 RemotePairing 时，上游的一次性 USB 命令是 `lockdown remotepairing --pair`。这些命令要你自己在终端运行，网页不会代跑，也不会绕过信任提示。

完成后拔掉数据线。手机和这台主机留在同一个局域网。Linux 的 usbmuxd 经常看不到 Wi-Fi 设备，这时在网页里选用 mobdev2，并填手机在局域网上的地址。

## 日常使用

1. 浏览器打开 `http://127.0.0.1:47321`（如果启用了网卡绑定，用那块网卡的地址和同一端口）。
2. 把口令文件里的内容输入一次。页面本身不显示口令。
3. 点“重新发现”，再点“选择这台设备”。有多台时必须点明一台。
4. 填写经纬度，或点一个收藏把数字填进输入框。可以先“保存为收藏”。
5. 勾选确认后，点“启动定位”。没有勾选不会发送。
6. 页面上的三行要分开看：上游是否接受了命令、本机会话进程是否还在、手机定位是否确认。第三行一直是“未能确认”，因为上游没有把手机的真实坐标回读给这个控制台。
7. 点“请求恢复真实定位”才会发送 clear。若上游没有成功，页面会写明不能确认已经恢复。
8. “只检查连接”最多试 3 次，不发送坐标。主机关机或手机重新连上之后，也不会自动重放上次的坐标；要再次定位，必须重新勾选并按启动。

收藏和已选设备记在状态目录的 `state.json`。口令、配对 plist 和证书不在里面。
