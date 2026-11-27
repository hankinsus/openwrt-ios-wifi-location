# 本机定位

这是给 iPhone 用的定位程序，按 AGPL-3.0 改编自公开项目 StikDebug 的提交 `63713ea2100660dc7066ee0e8d962858026f97aa`。它不使用上游名称和标志。评估见 `评估.md`。

同仓库里的 Python 控制台是另一个程序，许可证是 MIT。它跑在 R4S 一类主机上，不安装这个 App，所以没有这个 App 的 7 天签名。

## 在 Mac 上构建

需要一台装有 Xcode 的 Mac。本文件写于 Linux 云虚拟机，没有执行过 iOS 编译、签名或安装。

付费 Apple Developer Program 不是前提。工程使用 Automatic，没有填写开发团队。要装到自己的手机时，在 Xcode 的 Signing 里选择这台 Mac 上免费 Apple ID 的 Personal Team，并把 Bundle Identifier 改成你自己的。不要把 Apple ID、密码、证书或私钥放进这个目录，本程序里也没有这些输入框。

免费描述文件大约 7 天过期。到期后要用 Xcode 重新安装，或用你自己的侧载工具刷新。本程序不会在到期后自己重新签名，也不承诺免费签名可以一直有效。SideStore 的正常刷新是否适用于本程序，还没有真机结果。

手机上的开发者模式是系统开关。打开它不等于购买会员。

1. 在 `ios-native` 执行 `sh scripts/fetch-idevice.sh`。脚本下载官方 idevice 0.1.68 XCFramework，核对压缩包和头文件的 SHA-256，再把设备库和模拟器库放到 `Vendor/idevice/`。这些库不进 git。Xcode 的构建阶段也会跑这个脚本。缺库时链接失败，没有返回 -50 的假入口。
2. 用 Xcode 打开 `LanLocation.xcodeproj`。默认目标已经包含定位桥接、配对、隧道和磁盘镜像文件，不需要再把 Swift 文件加进目标。
3. 选择你信任的 iPhone 后运行。

逻辑库可以单独测试：

```bash
cd ios-native
swift test
```

Linux 上这条命令只编译 Foundation 逻辑，不生成 IPA。

## 界面在做什么

导入配对文件或走上游那条本机配对，查看本机有没有 `10.7.0.1`，下载并调用磁盘镜像挂载，输入坐标和收藏，确认后开始或停止。状态分成：命令是否返回 0、本机会话是否还标记为进行中、手机定位未能确认、清除失败时不能把恢复写成已经成功。

命令被接受后，本进程每 4 秒再发一次。没有复制后台音频和后台定位保活。进程重新创建时不会自动重发。

收藏写在 Application Support 的 `LanLocation/favorites.json`。配对文件在另一个受保护目录，模式 0600，完整文件保护，并排除备份。手填路径只在高级区。

## 还没做的事

- 没有 Mac 编译
- 没有代码签名，也没有 IPA
- 没有在真机上定位、配对、挂载镜像或对比 VPN
- 没有验证 SideStore 刷新
- 没有验证后台能持续发送定位
