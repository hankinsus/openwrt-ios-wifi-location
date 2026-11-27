# R4S 上还没有核对的事实

NanoPi R4S 常见硬件是 RK3399，CPU 为 aarch64。这只说明板子的常见型号，不能代替你这块板子上正在运行的系统。本仓库没有登录过这块板，也没有在 OpenWrt 根文件系统里安装 pymobiledevice3。

请在板子上抄下面几项，不要附带配对 plist、证书或密钥：

- `uname -srm`
- `MemTotal`（`/proc/meminfo` 的那一行）
- 是否存在 `/etc/openwrt_release`；若存在，只抄 `DISTRIB_ID`、`DISTRIB_RELEASE`、`DISTRIB_ARCH`、`DISTRIB_TARGET`
- `python3 --version`，以及 `python3 -m pip --version` 是否可用
- 磁盘剩余空间
- 手机和板子是否在同一局域网
- iPhone 的系统版本字符串
- 是否可以由你亲手完成一次 USB 信任

## 能力分级（现在就能说的）

| 环境 | 结论 |
| --- | --- |
| 这台云开发机 | 可以跑本工具的模拟进程测试。不是 R4S。 |
| GitHub `ubuntu-24.04` | 用来安装上游并核对帮助。x86_64 glibc。 |
| GitHub `ubuntu-24.04-arm` | 只验证 Ubuntu arm64 能否装上同一个上游版本。不是 OpenWrt。 |
| OpenWrt 根文件系统 | 未安装，未验证。 |
| 128MB / MIPS 的 GL.iNet XE300 原版系统 | 未验证，不承诺单机能跑 Python、cryptography 和 pymobiledevice3。 |

上游在 PyPI 上的依赖很多（含 `cryptography`、`pmd-pytcp`、`qh3`、`pytun-pmd3`、`av` 等）。OpenWrt 软件源里有没有对应版本，要等上面的系统信息到了再在那台机器上安装，不能用模拟进程推断。
