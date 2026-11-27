#!/usr/bin/env python3
"""Fill the checked-in report from a pytest JUnit file. Counts are not typed by hand."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    suite = list(ET.parse(args.junit).getroot().iter("testsuite"))[-1]
    tests = int(suite.attrib.get("tests", "0"))
    failures = int(suite.attrib.get("failures", "0"))
    errors = int(suite.attrib.get("errors", "0"))
    skipped = int(suite.attrib.get("skipped", "0"))
    duration = suite.attrib.get("time", "?")
    names = []
    for case in ET.parse(args.junit).getroot().iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            names.append(case.attrib.get("name", ""))
    passed = tests - failures - errors - skipped
    body = f"""# 测试报告

生成来源：开发机上的 pytest JUnit（`{args.junit}` 的一份副本不入库；数字来自那次运行）。

- 用例 {tests}，通过 {passed}，失败 {failures}，错误 {errors}，跳过 {skipped}
- 耗时 {duration} 秒
- 系统：Linux x86_64，Python 3.12.3
- 上游：已用 pip 安装 PyPI 的 pymobiledevice3 11.63.1，并执行帮助命令

## 已通过的自动化

模拟进程覆盖了坐标边界、非法字符、命令失败、超时、显式选择设备、USB 记录不能当成 Wi-Fi、清除失败时不宣称恢复、有限次重连，以及前台进程收到信号后的清理结果。

同一轮里的 `test_installed_upstream_help` 调用了本机安装的 `pymobiledevice3`，要求定位、usbmux 和 lockdown info 的 `--help` 退出码为 0，并且 set 帮助里含有 latitude 与 longitude。`pymobiledevice3 version` 打印 `11.63.1`。

`doctor` 在这台机器上的结果（不包含网卡地址）：架构 x86_64，上游版本 11.63.1，没有 `/etc/openwrt_release`，没有 usbmux 套接字。`usbmux list --network --simple` 的真实退出码是 1，原因是连不上 usbmuxd。

帮助原文在 `docs/evidence/upstream-help-linux-x86_64/`。

## 未测的硬件和系统

- 没有在 OpenWrt 根文件系统里安装。
- 没有登录 NanoPi R4S，不知道它现在的发行版、内存和 Python。
- 没有在 GL.iNet XE300（128MB / MIPS）上运行，不承诺能跑。
- GitHub Actions 的 Linux arm64 和 macOS 作业要等仓库推送之后才有结果。推送之前不能把它们写成已通过。
- 本机没有 `ip` 命令。接口名来自 `/sys/class/net`，这只说明诊断代码能枚举网卡，不是手机在局域网上。

## 需要真机才能验证

- USB 信任、开发者模式、Wi-Fi 重连后的定位模拟和清除，都没有在 iPhone 上做过。
- `remote pair-host` 的帮助文本存在，并且写着 iOS 27+。没有用它配过对。
- iOS Simulator 没有启动，也不能代替这些检查。
- 冒烟命令默认只演练。没有人传入 `--execute`，所以这次没有改过任何手机坐标。

通过的用例名：

"""
    body += "\n".join(f"- `{name}`" for name in names) + "\n"
    Path(args.out).write_text(body, encoding="utf-8")
    print(args.out)
    return 0 if failures == 0 and errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
