GUIDE = """\
一次性配对引导（本命令只打印说明，不连接手机，不写入配对记录）

上游 pymobiledevice3 11.63.1 的公开文档仍把普通 iPhone 的首次信任和 Wi-Fi 开发通道分成两步。
本工具不执行配对，也不绕过手机上的信任或开发者模式确认。下面的命令需要你自己在准备好的电脑上运行。

1. 用数据线连接已解锁的 iPhone。手机弹出信任提示时，由你亲手确认。
2. 开发者模式要在手机设置里由你打开。本工具不会替你打开它。
3. 首次 lockdown 配对（仍是 USB 步骤）：
   pymobiledevice3 lockdown pair
4. 允许这台电脑以后走 Wi-Fi lockdown（文档写明要在 USB 上做一次）：
   pymobiledevice3 lockdown wifi-connections on
5. 若准备使用 RemotePairing / --remotepairing，文档中的一次性 USB 引导是：
   pymobiledevice3 lockdown remotepairing --pair
   它使用已经信任的 lockdownd。本工具不调用它。
6. 拔掉数据线后，手机和这台 Linux 主机要在同一个局域网。文档没有要求公网 IPv6 或关闭 CGNAT。
7. Linux 自带的 usbmuxd 经常看不到 Wi-Fi 设备。这时用局域网发现，而不是假装 USB 列表里会有它：
   pymobiledevice3 bonjour mobdev2
   然后由 ios-wifi-loc select --transport mobdev2 或 --transport mobdev2 --host <局域网地址>
8. iOS 17.0 到 17.3 在 Linux 上，上游写明需要 root 的 tunneld。本工具不启动 tunneld，也不创建隧道网卡。
9. 上游另有 `pymobiledevice3 remote pair-host`，文档把它写成 iOS 27+ 上由手机发起的配对。
   这不是“所有 iPhone 都不必再用 USB”的结论。先看 `ios-wifi-loc doctor` 里该帮助是否真的存在，
   再在你自己的手机上验证。本仓库没有做过这件事。
10. `pymobiledevice3 remote pair` 在文档里主要用于会显示 PIN 的设备（例如 Apple TV）。
    文档写明普通 iOS 设备通常不需要这一步。

配对产生的 plist、证书和密钥由上游存放。不要把那些文件贴到工单、提交到 git，或放进本工具的状态目录。
"""


def pair_guide() -> str:
    return GUIDE
