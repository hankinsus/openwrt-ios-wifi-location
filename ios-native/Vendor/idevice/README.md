这个目录在构建时由 `scripts/fetch-idevice.sh` 填入。

固定版本是官方发布的 idevice 0.1.68 XCFramework。压缩包和头文件的 SHA-256 写在 `scripts/idevice.lock`。静态库不进 git，也不进源码包。

`include/module.modulemap` 把模块名定为 `idevice`，和改编后的 Swift `import idevice` 一致。官方压缩包里的模块名是 `IDevice`，头文件内容相同。

许可证见 `third-party/idevice-MIT-LICENSE.txt`。
