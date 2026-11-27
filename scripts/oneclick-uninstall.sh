#!/bin/sh
# Remove the one-click service and the private prefix.
# Does not remove system packages, routes, firewall rules, or PassWall.
set -eu

usage() {
    cat <<'EOF'
用法：sh scripts/oneclick-uninstall.sh [--dry-run] [--purge-state] [--root 路径] [--state-dir 路径] [--prefix 路径]

删除 procd 或 systemd 启动脚本，以及 oneclick 创建的 venv 或隔离目录。
不卸载系统里的 Python、usbmuxd 或其他软件包，也不改防火墙。
默认保留状态目录里的口令。加上 --purge-state 才删除状态目录。
EOF
}

DRY=0
PURGE=0
ROOT=
STATE=
PREFIX=

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1; shift ;;
        --purge-state) PURGE=1; shift ;;
        --root)
            [ $# -ge 2 ] || { echo "缺少 --root 的路径" >&2; exit 2; }
            ROOT=$2
            shift 2
            ;;
        --state-dir)
            [ $# -ge 2 ] || { echo "缺少 --state-dir 的路径" >&2; exit 2; }
            STATE=$2
            shift 2
            ;;
        --prefix)
            [ $# -ge 2 ] || { echo "缺少 --prefix 的路径" >&2; exit 2; }
            PREFIX=$2
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "未知参数：$1" >&2; usage >&2; exit 2 ;;
    esac
done

if [ -z "$ROOT" ]; then
    ROOT=${IOS_WIFI_LOC_ROOT:-/}
fi
if [ -z "$STATE" ]; then
    if [ -n "${IOS_WIFI_LOC_STATE_DIR:-}" ]; then
        STATE=$IOS_WIFI_LOC_STATE_DIR
    elif [ -f "$ROOT/etc/openwrt_release" ]; then
        if [ "$ROOT" = "/" ]; then
            STATE=/etc/ios-wifi-loc
        else
            STATE=$ROOT/etc/ios-wifi-loc
        fi
    elif [ "$ROOT" = "/" ]; then
        STATE=/var/lib/ios-wifi-loc
    else
        STATE=$ROOT/var/lib/ios-wifi-loc
    fi
fi
if [ -z "$PREFIX" ]; then
    if [ -n "${IOS_WIFI_LOC_PREFIX:-}" ]; then
        PREFIX=$IOS_WIFI_LOC_PREFIX
    elif [ "$ROOT" = "/" ]; then
        PREFIX=/usr/local/ios-wifi-loc
    else
        PREFIX=$ROOT/usr/local/ios-wifi-loc
    fi
fi

echo "将删除启动脚本（$ROOT 下的 procd 或 systemd 单元）。"
echo "将删除隔离环境：$PREFIX"
if [ "$PURGE" -eq 1 ]; then
    echo "将删除状态目录：$STATE"
else
    echo "保留状态目录：$STATE"
fi
echo "不卸载系统软件包，不修改路由、防火墙或 PassWall。"

if [ "$DRY" -eq 1 ]; then
    echo "这是预览，没有删除文件。"
    exit 0
fi

PY=${IOS_WIFI_LOC_PYTHON:-python3}
if [ -x "$PREFIX/venv/bin/python3" ]; then
    PY=$PREFIX/venv/bin/python3
elif [ -x "$PREFIX/bin/ios-wifi-loc-python" ]; then
    PY=$PREFIX/bin/ios-wifi-loc-python
fi

purge_arg=
if [ "$PURGE" -eq 1 ]; then
    purge_arg=--purge-state
fi
if [ -n "${IOS_WIFI_LOC_SRC_PYTHONPATH:-}" ]; then
    PYTHONPATH="$IOS_WIFI_LOC_SRC_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m ios_wifi_loc --state-dir "$STATE" uninstall --root "$ROOT" $purge_arg
else
    "$PY" -m ios_wifi_loc --state-dir "$STATE" uninstall --root "$ROOT" $purge_arg
fi

if [ -d "$PREFIX" ]; then
    rm -rf "$PREFIX"
    echo "已删除 $PREFIX"
fi
echo "卸载完成。"
