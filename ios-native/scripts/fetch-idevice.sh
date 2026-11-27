#!/bin/sh
# Download idevice 0.1.68 XCFramework from the official GitHub release,
# verify the archive and header, and install the slices the Xcode target links.
# The static libraries are not committed. A checksum mismatch stops the build.
set -eu

root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
lock="$root/scripts/idevice.lock"
vendor="$root/Vendor/idevice"
include="$vendor/include"
device_dir="$vendor/iphoneos"
sim_dir="$vendor/iphonesimulator"
cache_dir="$vendor/.cache"

read_lock() {
    key=$1
    value=$(sed -n "s/^${key}=//p" "$lock" | head -n 1)
    if [ -z "$value" ]; then
        echo "idevice.lock 缺少 $key" >&2
        exit 1
    fi
    printf '%s' "$value"
}

version=$(read_lock version)
url=$(read_lock url)
expected=$(read_lock sha256)
header_expected=$(read_lock header_sha256)
stamp="$vendor/.fetched-sha256"

if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$expected" ] \
    && [ -f "$include/idevice.h" ] \
    && [ -f "$device_dir/libidevice_ffi.a" ] \
    && [ -f "$sim_dir/libidevice_ffi.a" ]; then
    echo "idevice $version 已在本地，校验戳匹配。"
    exit 0
fi

mkdir -p "$cache_dir" "$include" "$device_dir" "$sim_dir"
archive="${IDEVICE_ZIP_CACHE:-$cache_dir/idevice-xcframework-$version.zip}"

if [ ! -f "$archive" ]; then
    echo "下载 $url"
    curl -fL --retry 3 --output "$archive.partial" "$url"
    mv "$archive.partial" "$archive"
fi

actual=$(sha256sum "$archive" | awk '{print $1}')
if [ "$actual" != "$expected" ]; then
    echo "压缩包校验失败。" >&2
    echo "期望 $expected" >&2
    echo "实际 $actual" >&2
    exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
unzip -q "$archive" \
    "swift/IDevice.xcframework/ios-arm64/libidevice_ffi.a" \
    "swift/IDevice.xcframework/ios-arm64/Headers/idevice.h" \
    "swift/IDevice.xcframework/ios-arm64_x86_64-simulator/idevice-ios-sim.a" \
    -d "$work"

header="$work/swift/IDevice.xcframework/ios-arm64/Headers/idevice.h"
header_actual=$(sha256sum "$header" | awk '{print $1}')
if [ "$header_actual" != "$header_expected" ]; then
    echo "头文件校验失败。" >&2
    echo "期望 $header_expected" >&2
    echo "实际 $header_actual" >&2
    exit 1
fi

for symbol in \
    location_simulation_set \
    location_simulation_clear \
    location_simulation_new \
    tunnel_create_rppairing \
    rp_pairing_file_read \
    rp_pairing_file_write \
    pairable_host_prepare \
    pairable_host_accept_fd \
    cryptexd_install_ddi \
    cryptexd_installed_ddi \
    image_mounter_mount_personalized_rsd
do
    if ! grep -q "$symbol" "$header"; then
        echo "头文件缺少 $symbol" >&2
        exit 1
    fi
done

cp "$header" "$include/idevice.h"
cp "$work/swift/IDevice.xcframework/ios-arm64/libidevice_ffi.a" "$device_dir/libidevice_ffi.a"
cp "$work/swift/IDevice.xcframework/ios-arm64_x86_64-simulator/idevice-ios-sim.a" "$sim_dir/libidevice_ffi.a"
printf '%s\n' "$expected" > "$stamp"
echo "已安装 idevice $version。设备库和模拟器库都使用 libidevice_ffi.a 这个链接名。"
