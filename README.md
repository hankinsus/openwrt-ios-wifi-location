# ios-wifi-loc 0.4.7

在 R4S 或其它 OpenWrt / Debian / Ubuntu 机器上，**一条命令**完成下载、补齐环境和安装。升级同一条命令即可，会保留已有口令和配对文件：

```sh
curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/install.sh | sh
```

没有 `curl` 时：

```sh
wget -qO- https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/install.sh | sh
```

OpenWrt 常用：

```sh
uclient-fetch -O- https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/install.sh | sh
```

需要指定网卡，或先预览再安装：

```sh
curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/install.sh | sh -s -- --interface br-lan
curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/install.sh | sh -s -- --dry-run
```

在 OpenWrt 上如果存在 `br-lan`，并且你没有写 `--interface`，安装脚本会自动加上 `--interface br-lan`，方便在局域网打开页面。服务仍然不会监听 `0.0.0.0`。

卸载启动脚本和隔离环境（不卸载系统里的 Python，也不改防火墙；默认保留口令和配对文件）：

```sh
curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/uninstall.sh | sh
```

同时删除状态目录：

```sh
curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/uninstall.sh | sh -s -- --purge-state
```

对外使用的公开仓库是 <https://github.com/hankinsus/openwrt-ios-wifi-location>。

已经把源码目录放到机器上时，也可以直接跑：

```bash
sh scripts/oneclick-install.sh --interface br-lan
sh scripts/oneclick-install.sh --interface br-lan --dry-run
sh scripts/oneclick-uninstall.sh
```

它会识别 OpenWrt（看 `/etc/openwrt_release`，用 `opkg`，OpenWrt 24.10+ 则用 `apk`）或 Debian/Ubuntu（`apt-get`），先打印要装的包、内存和磁盘，再补齐 Python 3.9+、pip 和 usbmuxd。优先创建 venv；OpenWrt 上没有 venv 模块时改把依赖装进隔离目录，不写入系统 site-packages。然后安装本工具和 `requirements-upstream.txt` 里的 pymobiledevice3，运行 preflight，并写入 procd 或 systemd。局域网访问用 `--interface br-lan`，只绑定这块网卡，不监听 `0.0.0.0`。

v0.3.0 按 NanoPi R4S（OpenWrt 24.10.0）与 iPhone 17 Pro（iOS 27.2.1）上的无线 `tunneld` + `--tunnel <UDID>` 定位流程做了相应调整：安装后会自动常驻 `pymobiledevice3 remote tunneld --protocol tcp --no-usb --no-usbmux --mobdev2`，网页改定位走 `--tunnel`。OpenWrt 的状态目录默认是 `/etc/ios-wifi-loc`（可写闪存）。`/var` 在 OpenWrt 上通常指向内存盘，所以不再把口令和配对文件放在 `/var/lib/ios-wifi-loc`。从旧版本升级时，会把已有口令、收藏和 `.plist` 迁移过来，不会轮换口令。

局域网页面**默认免密**。打开 `http://<路由器地址>:19443` 即可使用。这只适合受信局域网，请勿把 19443 端口暴露到公网。若需要口令，安装或启动时加 `--require-auth`，口令仍在状态目录的 `web.secret`，权限 `0600`。

支持同时管理多台 iPhone：每台设备有独立的模拟进程，给 B 设定位不会打断 A；清除某一台也只影响这一台。

v0.3.1 为每台正在模拟的设备加上自动重连守护：当手机休眠或 Wi-Fi 隧道复位导致 `simulate-location set` 因 `Network unreachable` / `DTX reader exiting` 退出时，会等待隧道恢复并按原坐标重新发起，直到你在页面上清除或改选其它坐标。网页顶部用设备下拉菜单选择已发现的 iPhone，配对卡片提供可复制的 Windows 三步说明。按钮点击会有按压和加载反馈；在普通 HTTP 局域网地址上，「当前位置」不再调用浏览器 GPS（会因非 HTTPS 被拒绝），请直接在地图点选或搜索地点。

v0.4.0 增加本机 iOS 快捷指令与地图分享接口（`/api/shortcut/set` 可解析高德 / 苹果 / 谷歌 / 百度分享链接或坐标，并自动把 GCJ-02、BD-09 转成 WGS-84），网页或快捷指令再次设置同一台设备时会自动替换旧坐标。配对页可下载 Windows 一键配对工具，并把 `C:\ProgramData\Apple\Lockdown\` 里的 `.plist` 直接上传到路由器；配对列表会显示设备名称。安装脚本自动识别 OpenWrt / Debian / Alpine，升级时保留状态。

v0.4.1 将网页默认端口改为 `19443`。Wi-Fi 断开再连上时，自动重连守护会发现 tunneld 换了新的隧道地址/端口，主动结束卡住的旧进程并按原坐标重新设置定位。设置过的坐标会写入状态文件，只有点「一键恢复真实定位」才会清除；路由器重启或服务拉起后，只要手机重新连上 Wi-Fi，就会自动按保存的坐标重新定位。网页默认地址改为 `http://<路由器地址>:19443`。

v0.4.2 整理了网页布局：地图仍在最上方，设备下拉框下只保留一张蓝边选中卡片，「高级 / 手动添加」只用于手工填写传输/标识/主机。复制按钮在普通 HTTP 局域网也能用；收藏下方可直接输入纬度、经度并跳转。

v0.4.3 把选中设备卡片改成横向紧凑布局（左侧名称与标识，右侧状态与「已选择」徽章），并把坐标输入合并进「搜索地点」：可以搜地名，也可以直接输入 `35.6812, 139.7671` 跳转，少一个模块。

v0.4.4 把两个已验证可用的 iOS 快捷指令做成网页一键安装按钮，并去掉下面繁琐的手动配置说明。安装后如路由器 IP 不是默认地址，在快捷指令里改成当前路由器地址即可：

- 地图分享定位：<https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861>
- 一键恢复真实定位：<https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1>

配对列表的删除按钮与「我的收藏」统一为圆形浅底红 ×。网页「配对管理」默认只显示已导入列表和醒目的「下载 Windows 一键配对工具」按钮：双击运行即可自动检测/安装 Python（兼容 `python` / `py`，跳过 WindowsApps 空壳占位符；没有时用 `winget` 安装 Python 3.12 并刷新 PATH），开启开发者模式、配对并打开 Wi-Fi，再按当前网页地址把最新的 `<UDID>.plist` 和 `SystemConfiguration.plist` 自动上传到本机 `/api/pairing/import`。手动 PowerShell 步骤和拖拽上传收在默认折叠的「展开手动配置与手动上传」里，作为兜底。设备下拉框和选中卡片都会显示完整的手机名称与 iOS 版本（例如 `iPhone17 PRO (iOS 27.2.1)`），发现结果只有泛泛的「iPhone」时会回填已保存或配对记录里的名称，避免把友好名称冲掉。页面同时适配手机、iPad 和电脑宽度：窄屏竖排不溢出，长 UDID / IPv6 会换行，按钮更好点。

v0.4.5 修复了配对管理卡片下方漏出残缺 HTML 文本的问题。电脑端把主容器收窄到 720px 居中，地图与卡片对齐，手机和 iPad 仍自适应、不溢出。选中设备蓝框改为三行：第一行左侧是设备名与 iOS 版本（例如 `iPhone17 PRO · iOS 27.2.1`），右侧同一行是蓝色「已选择」徽章；第二行是 UDID 与隧道信息；第三行是绿色状态胶囊，单独占一行。折叠面板里的手动配置改回简短的几行命令；完整的自动检测/安装 Python、开启开发者模式、配对开 Wi-Fi、并按网页地址自动上传两个 `.plist` 的能力，仍然保留在 Windows 一键配对工具（`.bat`）里。同时去掉「当前模拟状态」卡片和页脚长说明，页脚只保留 `OpenWrt 无线虚拟定位 · v0.4.5`。

v0.4.7 针对实机 `ps` / `logread` 里同时出现两个 `_hold`、两个 `simulate-location set`，以及旧 `tunneld` 占着 49151 导致 procd `ios-wifi-loc::tunneld` crash loop 的问题做了根治：按 UDID 加线程锁和 `fcntl.flock`，拉起新 `_hold` 前先按进程表和 `state.json` 清掉该设备的旧 `_hold` / `simulate-location`；`serve()` 启动和停止时统一接管，避免升级后孤儿进程继续占着连接。网页点「设置定位」即使坐标没变也会先停掉旧会话再重新下发。OpenWrt `start_service` / `stop_service`（以及 systemd / OpenRC）会清理残留 holder 和占用 49151 的旧 tunneld，并把 procd `respawn` 调整为 `3600 10 3`。页脚与上方卡片拉开间距并去掉多余白框；图层切换栏改为在地图两侧留白内换行，不再使用会在 Windows 下溢出的 `100vw`，六个按钮在手机 / iPad / 电脑都完整可见。

v0.4.6 把顶部地图恢复为视口全宽（电脑端约 420px 高，平板和手机自适应），功能卡片仍按 720px 居中。修复了删除状态卡片后 `paint()` 里残留的 `ready is not defined` 报错，并收紧页脚与空错误条的边距。选中设备卡片右上角徽章改为真实的隧道状态：「已连接」/「未连接」。服务启动或升级重启后，会在后台持续等待 tunneld 发现已保存的设备，再自动重新下发 `desired_targets` 里的坐标；运行中隧道短暂断开再连上时（即使地址端口没变），也会杀掉可能假活的 `simulate-location` 进程并重新设置，避免只显示「保持中、已重连」但手机定位已经掉了。安装/升级脚本仍保留 `/etc/ios-wifi-loc` 里的状态文件。仓库增加前端 JS 语法检查和手机 / iPad / 电脑三个视口的 Playwright 渲染回归，并由 GitHub Actions 在每次推送时自动运行。

iPhone 本机精简版在 `ios-native/`，许可证是 AGPL-3.0，和这个 Python 控制台不是同一个程序。本机程序用免费 Apple ID 侧载，描述文件大约 7 天有效；付费开发者计划不是前提。这个 Python 控制台不在 R4S 上安装该 App，因此没有该 App 的 7 天签名。手机开发者模式是系统开关，不是会员。

手机协议仍由上游 [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) 执行。本工具不改路由、防火墙或 PassWall，不刷固件，也不使用 Apple ID。

## 安装时做了什么

`preflight` 报告架构、内存和初始化系统。内存很低或系统是 OpenWrt 时会警告，不会因此声称上游已经能跑。

OpenWrt 写入 procd 脚本，Debian/Ubuntu 写入 systemd 单元。两者都会拉起网页控制台和 `tunneld`，失败后有限次重试。进程重启不会重新发送坐标。编译用的 gcc、头文件和 libimobiledevice 只在 pymobiledevice3 不能直接装上时才补。启动时会把 `/etc/ios-wifi-loc/lockdown/*.plist` 同步到 `/var/lib/lockdown`，以便无线发现能用到配对记录。

默认只绑定指定网卡的地址，端口 `19443`。安装输出只打印口令文件路径，不打印口令内容。

128MB/MIPS 的 XE300 仍然不承诺能跑上游。

手动安装仍然可以，效果和上面那条命令相同：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install .
python3 -m pip install -r requirements-upstream.txt
python3 -m ios_wifi_loc preflight
python3 -m ios_wifi_loc --state-dir /etc/ios-wifi-loc install --root / --interface br-lan
```

## 首次配对

普通 iPhone 仍按上游的做法：在电脑上用数据线连接，由你在手机上确认信任和开发者模式，再执行一次：

```sh
pymobiledevice3 lockdown pair
pymobiledevice3 lockdown wifi-connections on
```

配对文件通常在 Windows 的 `C:\ProgramData\Apple\Lockdown\` 或 macOS 的 `/var/db/lockdown/`。打开网页里的「配对管理」，把对应的 `<UDID>.plist` 和 `SystemConfiguration.plist` 拖进去即可，不用再通过 SCP 拷到路由器。多台手机就导入各自的 `<UDID>.plist`。

网页不会代跑配对命令，也不会绕过手机上的信任提示。完成后拔掉数据线。手机和这台主机留在同一个局域网。

## iOS 快捷指令

网页「iOS 快捷指令 & 地图分享」提供两个一键安装按钮，也可以直接打开下面的 iCloud 链接：

- 地图分享定位：<https://www.icloud.com/shortcuts/cf3227b48a8f484283069a087727f861>
- 一键恢复真实定位：<https://www.icloud.com/shortcuts/395385a36be94384a85480d7459d1fa1>

安装后如路由器 IP 不是默认地址，在快捷指令里改成当前路由器地址即可。接口仍是本机 `/api/shortcut/set` 和 `/api/shortcut/clear`，可解析高德 / 苹果 / 谷歌 / 百度分享链接或坐标。

## 日常使用

1. 浏览器打开 `http://<路由器局域网地址>:19443`。默认免密，进入后即可操作。
2. 页面会自动扫描局域网里的 iPhone。点「选择此设备」，或点「重新扫描」。
3. 在地图上点选位置、搜索地名、粘贴地图链接，或点城市预设。坐标按 WGS-84 发给手机；选用高德图层时会自动做 GCJ-02 转换。
4. 点「设置定位」或城市按钮，立即向当前选中的手机发送坐标。可再点另一台手机，给它设置不同的位置，不会打断第一台的模拟。
5. 选中设备卡片上的绿色状态条会显示保持与自动重连情况。请在苹果地图里看蓝点确认手机位置。
6. 点「一键恢复真实定位」只会清除**当前选中**的那台手机。若上游没有成功，页面会写明不能确认已经恢复。
7. 收藏保存在路由器的状态目录里，重启后还在。

收藏、已选设备和各台手机的模拟会话记在状态目录的 `state.json`。口令文件和配对 plist 也在同一状态目录，但页面接口不会返回私钥或文件内容。
