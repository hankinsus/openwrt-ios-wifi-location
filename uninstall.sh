#!/bin/sh
# Bootstrap uninstaller. Fetches or calls scripts/oneclick-uninstall.sh.
set -eu

usage() {
    cat <<'USAGE'
用法：
  curl -fsSL https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/uninstall.sh | sh
  wget -qO- https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/uninstall.sh | sh
  uclient-fetch -O- https://raw.githubusercontent.com/hankinsus/openwrt-ios-wifi-location/main/uninstall.sh | sh

传参（管道时用 sh -s --）：
  curl -fsSL .../uninstall.sh | sh -s -- --purge-state
  curl -fsSL .../uninstall.sh | sh -s -- --dry-run

其余参数原样交给 scripts/oneclick-uninstall.sh，例如 --dry-run、--purge-state、--root、--state-dir、--prefix。

可用环境变量：
  IOS_WIFI_LOC_REPO         默认 hankinsus/openwrt-ios-wifi-location
  IOS_WIFI_LOC_REF          默认 main
  IOS_WIFI_LOC_ARCHIVE_URL  覆盖压缩包地址（可用 file:///path/to/archive.tar.gz 或镜像）
USAGE
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            usage
            exit 0
            ;;
    esac
done

REPO=${IOS_WIFI_LOC_REPO:-hankinsus/openwrt-ios-wifi-location}
REF=${IOS_WIFI_LOC_REF:-main}
ARCHIVE_URL=${IOS_WIFI_LOC_ARCHIVE_URL:-https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz}

HERE=
case $0 in
    /*|.*/*|*/*)
        if [ -f "$0" ]; then
            HERE=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
        fi
        ;;
esac

WORKDIR=
cleanup() {
    if [ -n "${WORKDIR:-}" ] && [ -d "$WORKDIR" ]; then
        rm -rf "$WORKDIR"
    fi
}
trap cleanup EXIT INT TERM HUP

download_archive() {
    url=$1
    dest=$2
    case $url in
        file://*)
            src=${url#file://}
            case $src in
                localhost/*) src=/${src#localhost/} ;;
                /*) ;;
                *)
                    echo "file:// 地址必须是绝对路径，例如 file:///tmp/archive.tar.gz" >&2
                    return 1
                    ;;
            esac
            if [ ! -f "$src" ]; then
                echo "找不到本地压缩包：$src" >&2
                return 1
            fi
            cp -- "$src" "$dest"
            return 0
            ;;
    esac

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$dest" -- "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$dest" -- "$url"
    elif command -v uclient-fetch >/dev/null 2>&1; then
        uclient-fetch -O "$dest" "$url"
    else
        echo "需要 curl、wget 或 uclient-fetch 才能下载卸载脚本所用的压缩包。" >&2
        return 1
    fi
}

extract_archive() {
    archive=$1
    dest=$2
    if tar -xzf "$archive" -C "$dest"; then
        return 0
    fi
    if command -v gzip >/dev/null 2>&1; then
        gzip -dc "$archive" | tar -xf - -C "$dest"
        return 0
    fi
    echo "无法解压压缩包，需要支持 gzip 的 tar。" >&2
    return 1
}

find_oneclick() {
    root=$1
    name=$2
    if [ -f "$root/scripts/$name" ]; then
        printf '%s\n' "$root/scripts/$name"
        return 0
    fi
    for d in "$root"/*; do
        if [ -f "$d/scripts/$name" ]; then
            printf '%s\n' "$d/scripts/$name"
            return 0
        fi
    done
    return 1
}

SCRIPT=
if [ -z "${IOS_WIFI_LOC_ARCHIVE_URL:-}" ] && [ -n "$HERE" ] && [ -f "$HERE/scripts/oneclick-uninstall.sh" ]; then
    SCRIPT=$HERE/scripts/oneclick-uninstall.sh
    echo "使用本地目录：$HERE"
else
    WORKDIR=$(mktemp -d 2>/dev/null || mktemp -d "${TMPDIR:-/tmp}/ios-wifi-loc.XXXXXX") || {
        WORKDIR=${TMPDIR:-/tmp}/ios-wifi-loc.$$
        mkdir -m 700 "$WORKDIR"
    }
    SRC=$WORKDIR/src
    ARCHIVE=$WORKDIR/source.tar.gz
    mkdir -p "$SRC"
    echo "下载压缩包：$ARCHIVE_URL"
    if ! download_archive "$ARCHIVE_URL" "$ARCHIVE"; then
        echo "下载失败。OpenWrt 上可先安装 ca-bundle，或设置 IOS_WIFI_LOC_ARCHIVE_URL 使用镜像。" >&2
        exit 1
    fi
    if ! extract_archive "$ARCHIVE" "$SRC"; then
        exit 1
    fi
    if ! SCRIPT=$(find_oneclick "$SRC" oneclick-uninstall.sh); then
        echo "压缩包里没有 scripts/oneclick-uninstall.sh。" >&2
        exit 1
    fi
fi

sh "$SCRIPT" "$@"
