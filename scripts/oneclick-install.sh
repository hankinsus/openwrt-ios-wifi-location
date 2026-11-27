#!/bin/sh
# One command for OpenWrt (opkg or apk) and Debian/Ubuntu (apt-get).
# Does not change routes, firewall, or PassWall, and does not listen on 0.0.0.0.
set -eu

usage() {
    cat <<'EOF'
用法：sh scripts/oneclick-install.sh [--interface br-lan] [--port 19443] [--dry-run] [--upgrade] [--root 路径] [--state-dir 路径] [--prefix 路径]

自动识别 OpenWrt（/etc/openwrt_release，opkg 或 apk，procd）、Debian/Ubuntu/Armbian 等（apt-get，systemd）、Alpine Linux（apk，OpenRC）。
补齐 Python 3.9+、pip、usbmuxd 和局域网发现（avahi），优先创建 venv。没有 venv 模块时改把依赖装进隔离目录，不写入系统 site-packages。
然后安装本工具和 pymobiledevice3，运行 preflight，并写入 procd、systemd 或 OpenRC。
不修改路由、防火墙或 PassWall，不监听 0.0.0.0。口令文件权限是 0600，输出只给路径。
编译依赖只在上游不能直接装上时才补。
OpenWrt 上默认把状态和配对文件放在 /etc/ios-wifi-loc（可写闪存），Debian/Alpine 默认 /var/lib/ios-wifi-loc。局域网页面默认免密，请勿把 19443 端口暴露到公网。再次运行或加 --upgrade 会保留已有口令、收藏和配对文件并重启服务。
EOF
}

src=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
DRY=0
UPGRADE=0
INTERFACE=
PORT=
ROOT=
STATE=
PREFIX=

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1; shift ;;
        --upgrade) UPGRADE=1; shift ;;
        --interface)
            [ $# -ge 2 ] || { echo "缺少 --interface 的网卡名" >&2; exit 2; }
            INTERFACE=$2
            shift 2
            ;;
        --interface=*) INTERFACE=${1#--interface=}; shift ;;
        --port)
            [ $# -ge 2 ] || { echo "缺少 --port 的端口" >&2; exit 2; }
            PORT=$2
            shift 2
            ;;
        --port=*) PORT=${1#--port=}; shift ;;
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
STATE_SET=0
if [ -n "$STATE" ]; then
    STATE_SET=1
elif [ -n "${IOS_WIFI_LOC_STATE_DIR:-}" ]; then
    STATE=$IOS_WIFI_LOC_STATE_DIR
    STATE_SET=1
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

if [ -n "$INTERFACE" ]; then
    printf '%s\n' "$INTERFACE" | grep -Eq '^[A-Za-z][A-Za-z0-9._:-]{0,14}$' || {
        echo "网卡名无效。局域网请写 --interface br-lan，不能写 0.0.0.0。" >&2
        exit 2
    }
    if [ "$INTERFACE" = "0.0.0.0" ]; then
        echo "拒绝监听 0.0.0.0。" >&2
        exit 2
    fi
fi

if [ -n "$PORT" ]; then
    printf '%s\n' "$PORT" | grep -Eq '^[0-9]+$' || {
        echo "端口无效。请写 1 到 65535 之间的数字，默认 19443。" >&2
        exit 2
    }
    if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
        echo "端口无效。请写 1 到 65535 之间的数字，默认 19443。" >&2
        exit 2
    fi
fi

KIND=
PM=
if [ -f "$ROOT/etc/openwrt_release" ]; then
    KIND=openwrt
    if command -v opkg >/dev/null 2>&1; then
        PM=opkg
    elif command -v apk >/dev/null 2>&1; then
        PM=apk
    else
        echo "识别为 OpenWrt，但找不到 opkg 或 apk。" >&2
        exit 1
    fi
elif [ -f "$ROOT/etc/alpine-release" ]; then
    KIND=alpine
    PM=apk
    if [ "$ROOT" = "/" ] && ! command -v apk >/dev/null 2>&1; then
        echo "识别为 Alpine Linux，但找不到 apk。" >&2
        exit 1
    fi
elif [ -f "$ROOT/etc/debian_version" ] || { [ -f "$ROOT/etc/os-release" ] && grep -Eq '^(ID|ID_LIKE)=.*(debian|ubuntu)' "$ROOT/etc/os-release"; }; then
    KIND=debian
    PM=apt-get
    if [ "$ROOT" = "/" ] && ! command -v apt-get >/dev/null 2>&1; then
        echo "识别为 Debian/Ubuntu，但找不到 apt-get。" >&2
        exit 1
    fi
else
    echo "只自动安装 OpenWrt（opkg/apk）、Debian/Ubuntu（apt-get）和 Alpine Linux（apk）。当前根目录不是这几种系统。" >&2
    exit 1
fi

if [ "$STATE_SET" -eq 0 ]; then
    if [ "$KIND" = openwrt ]; then
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

BASE_PKGS="python3 python3-pip usbmuxd"
BUILD_PKGS="gcc python3-dev libopenssl-dev libffi-dev libimobiledevice"
if [ "$KIND" = debian ]; then
    BASE_PKGS="python3 python3-pip python3-venv usbmuxd avahi-daemon"
    BUILD_PKGS="build-essential python3-dev libssl-dev libffi-dev libimobiledevice-utils"
elif [ "$KIND" = alpine ]; then
    BASE_PKGS="python3 py3-pip py3-virtualenv usbmuxd avahi dbus"
    BUILD_PKGS="build-base python3-dev openssl-dev libffi-dev libimobiledevice"
fi

echo "系统：$KIND，包管理器：$PM"
echo "将要安装的包：$BASE_PKGS"
if [ "$KIND" = openwrt ]; then
    echo "若没有 venv 模块，会再尝试 python3-venv。OpenWrt 上可能没有这个包，失败后改用隔离目录。"
fi
echo "仅当 pymobiledevice3 不能直接装上时才补：$BUILD_PKGS"
echo "安装前缀：$PREFIX"
echo "状态目录：$STATE"
if [ -n "$INTERFACE" ]; then
    echo "服务绑定网卡：$INTERFACE（不是 0.0.0.0）"
else
    echo "服务只监听 127.0.0.1。局域网请加 --interface br-lan。"
fi
if [ -n "$PORT" ]; then
    echo "网页端口：$PORT"
else
    echo "网页端口：19443（可用 --port 修改）"
fi
echo "不会修改路由、防火墙或 PassWall。"
if [ "$UPGRADE" -eq 1 ]; then
    echo "这是升级安装，会保留已有口令、收藏和配对文件，并在写入启动脚本后重启服务。"
fi

if [ -r /proc/meminfo ]; then
    mem_total=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
    mem_avail=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
    echo "内存 MemTotal=${mem_total:-未知}kB MemAvailable=${mem_avail:-未知}kB"
    if [ -n "${mem_total:-}" ] && [ "$mem_total" -lt 262144 ]; then
        echo "警告：内存低于 256MB。控制台很小，但 pymobiledevice3 没有在这个内存上验证。"
    fi
else
    echo "内存：读不到 /proc/meminfo。"
fi

disk_dir=$PREFIX
while [ ! -d "$disk_dir" ]; do
    disk_dir=$(dirname "$disk_dir")
done
disk_avail=$(df -Pk "$disk_dir" | awk 'NR==2 {print $4}')
echo "可用磁盘 ${disk_avail:-未知}kB（$disk_dir）"
if [ -n "${disk_avail:-}" ] && [ "$disk_avail" -lt 40960 ] && [ "$DRY" -eq 0 ]; then
    echo "可用磁盘低于 40MB，停止安装。" >&2
    exit 1
fi

if [ "$DRY" -eq 1 ]; then
    echo "这是预览，没有安装软件包，没有创建环境，没有写启动脚本。"
    exit 0
fi

if [ "$ROOT" = "/" ] && [ "$(id -u)" -ne 0 ]; then
    echo "安装到系统需要 root。可以先加 --dry-run。" >&2
    exit 1
fi

BASEPY=${IOS_WIFI_LOC_PYTHON:-$(command -v python3 || true)}
if [ -z "$BASEPY" ]; then
    echo "还没有 python3，将先安装软件包。" >&2
fi

pm_install() {
    if [ "$PM" = opkg ]; then
        opkg update || echo "opkg update 失败，仍尝试安装已有列表里的包。"
        # shellcheck disable=SC2086
        opkg install $1
    elif [ "$PM" = apk ]; then
        apk update || echo "apk update 失败，仍尝试安装已有列表里的包。"
        # shellcheck disable=SC2086
        apk add $1
    else
        apt-get update
        # shellcheck disable=SC2086
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $1
    fi
}

echo "开始安装基础包。"
pm_install "$BASE_PKGS"

BASEPY=${IOS_WIFI_LOC_PYTHON:-$(command -v python3 || true)}
if [ -z "$BASEPY" ] || [ ! -x "$BASEPY" ]; then
    echo "安装软件包后仍没有 python3。" >&2
    exit 1
fi
if ! "$BASEPY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "需要 Python 3.9 或更新。当前 $($BASEPY --version 2>&1) 不够。" >&2
    exit 1
fi

if ! "$BASEPY" -c 'import venv' >/dev/null 2>&1 && [ "$KIND" = openwrt ]; then
    echo "尝试安装 python3-venv。OpenWrt 上可能没有这个包。"
    if [ "$PM" = opkg ]; then
        opkg install python3-venv || echo "没有装上 python3-venv。"
    else
        apk add python3-venv || echo "没有装上 python3-venv。"
    fi
fi

mkdir -p "$PREFIX"
USE_TARGET=0
if "$BASEPY" -c 'import venv' >/dev/null 2>&1; then
    if ! "$BASEPY" -m venv "$PREFIX/venv"; then
        echo "venv 创建失败，改用 $PREFIX/pydeps，不写入系统 site-packages。"
        USE_TARGET=1
    fi
else
    echo "没有 venv 模块，改用 $PREFIX/pydeps，不写入系统 site-packages。"
    USE_TARGET=1
fi

if [ "$USE_TARGET" -eq 0 ]; then
    PYBIN=$PREFIX/venv/bin/python3
    PIP_PY=$PYBIN
    TARGET_ARGS=
else
    mkdir -p "$PREFIX/pydeps" "$PREFIX/bin"
    cat > "$PREFIX/bin/ios-wifi-loc-python" <<EOF
#!/bin/sh
export PYTHONPATH="$PREFIX/pydeps\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$BASEPY" "\$@"
EOF
    chmod 755 "$PREFIX/bin/ios-wifi-loc-python"
    PYBIN=$PREFIX/bin/ios-wifi-loc-python
    PIP_PY=$BASEPY
    TARGET_ARGS="--target $PREFIX/pydeps"
fi

run_pip() {
    subcmd=$1
    shift
    # shellcheck disable=SC2086
    if [ -n "${IOS_WIFI_LOC_PIP:-}" ]; then
        # shellcheck disable=SC2086
        "$IOS_WIFI_LOC_PIP" "$subcmd" $TARGET_ARGS "$@"
    else
        # shellcheck disable=SC2086
        "$PIP_PY" -m pip "$subcmd" $TARGET_ARGS "$@"
    fi
}

install_build() {
    echo "上游没有直接装上，开始按包补齐编译依赖。"
    for pkg in $BUILD_PKGS; do
        echo "补齐 $pkg"
        if [ "$PM" = opkg ]; then
            opkg install "$pkg" || echo "没有装上 $pkg"
        elif [ "$PM" = apk ]; then
            apk add "$pkg" || echo "没有装上 $pkg"
        else
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$pkg" || echo "没有装上 $pkg"
        fi
    done
}

echo "安装本工具。"
run_pip install --disable-pip-version-check "$src"
echo "安装 pymobiledevice3。"
if ! run_pip install --disable-pip-version-check -r "$src/requirements-upstream.txt"; then
    install_build
    run_pip install --disable-pip-version-check -r "$src/requirements-upstream.txt"
fi

run_tool() {
    if "$PYBIN" -c 'import ios_wifi_loc' >/dev/null 2>&1; then
        "$PYBIN" "$@"
        return
    fi
    if [ -n "${IOS_WIFI_LOC_SRC_PYTHONPATH:-}" ]; then
        PYTHONPATH="$IOS_WIFI_LOC_SRC_PYTHONPATH${PYTHONPATH:+:$PYTHONPATH}" "$PYBIN" "$@"
        return
    fi
    echo "安装后仍无法导入 ios_wifi_loc。" >&2
    exit 1
}


migrate_state() {
    old_state=
    if [ "$ROOT" = "/" ]; then
        old_state=/var/lib/ios-wifi-loc
        old_lockdown=/var/lib/lockdown
    else
        old_state=$ROOT/var/lib/ios-wifi-loc
        old_lockdown=$ROOT/var/lib/lockdown
    fi
    mkdir -p "$STATE" "$STATE/lockdown"
    chmod 700 "$STATE" "$STATE/lockdown" 2>/dev/null || true
    if [ -d "$old_state" ] && [ "$old_state" != "$STATE" ]; then
        if [ -f "$old_state/web.secret" ] && [ ! -f "$STATE/web.secret" ]; then
            cp "$old_state/web.secret" "$STATE/web.secret"
            chmod 600 "$STATE/web.secret"
            echo "已保留原来的口令文件。"
        fi
        if [ -f "$old_state/state.json" ] && [ ! -f "$STATE/state.json" ]; then
            cp "$old_state/state.json" "$STATE/state.json"
            chmod 600 "$STATE/state.json"
            echo "已保留原来的收藏和设备选择。"
        fi
        if [ -d "$old_state/lockdown" ]; then
            for f in "$old_state/lockdown"/*.plist; do
                [ -f "$f" ] || continue
                base=${f##*/}
                if [ ! -f "$STATE/lockdown/$base" ]; then
                    cp "$f" "$STATE/lockdown/$base"
                    chmod 600 "$STATE/lockdown/$base"
                fi
            done
        fi
    fi
    if [ -d "$old_lockdown" ]; then
        mkdir -p "$STATE/lockdown"
        for f in "$old_lockdown"/*.plist; do
            [ -f "$f" ] || continue
            base=${f##*/}
            if [ ! -f "$STATE/lockdown/$base" ]; then
                cp "$f" "$STATE/lockdown/$base"
                chmod 600 "$STATE/lockdown/$base"
            fi
        done
    fi
}

echo "同步状态目录（升级时保留已有口令和配对文件）。"
migrate_state

echo "运行 preflight。"
run_tool -m ios_wifi_loc preflight --root "$ROOT"

PMBIN=pymobiledevice3
if [ -d "$PREFIX/venv/bin" ]; then
    PMBIN=$PREFIX/venv/bin/pymobiledevice3
elif [ -x "$PREFIX/pydeps/bin/pymobiledevice3" ] || [ -e "$PREFIX/pydeps/bin/pymobiledevice3" ]; then
    PMBIN=$PREFIX/pydeps/bin/pymobiledevice3
fi

install_args="--root $ROOT --python $PYBIN"
if [ -n "$INTERFACE" ]; then
    install_args="$install_args --interface $INTERFACE"
fi
if [ -n "$PORT" ]; then
    install_args="$install_args --port $PORT"
fi
# shellcheck disable=SC2086
report=$(run_tool -m ios_wifi_loc --json --state-dir "$STATE" --binary "$PMBIN" install $install_args)
secret_path=$(printf '%s' "$report" | "$BASEPY" -c 'import json,sys; print(json.load(sys.stdin)["details"]["secret_path"])')
echo "已写入启动脚本。状态目录：$STATE"
echo "口令文件：$secret_path（默认免密，不需要输入；文件权限应为 0600，需要时可用 --require-auth）。"
echo "口令内容没有打印。请勿把 19443 端口暴露到公网。"

if [ "$ROOT" = "/" ]; then
    if [ -f /etc/openwrt_release ] && [ -x /etc/init.d/ios-wifi-loc ]; then
        /etc/init.d/ios-wifi-loc enable || echo "没有启用 procd 服务。"
        /etc/init.d/ios-wifi-loc restart 2>/dev/null || /etc/init.d/ios-wifi-loc start || echo "没有启动 procd 服务。"
    elif command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/ios-wifi-loc.service ]; then
        systemctl daemon-reload || true
        systemctl enable ios-wifi-loc-tunneld.service ios-wifi-loc.service || echo "没有启用 systemd 服务。"
        systemctl restart ios-wifi-loc-tunneld.service ios-wifi-loc.service 2>/dev/null || systemctl start ios-wifi-loc-tunneld.service ios-wifi-loc.service || echo "没有启动 systemd 服务。"
    elif command -v rc-update >/dev/null 2>&1 && [ -x /etc/init.d/ios-wifi-loc ]; then
        rc-update add ios-wifi-loc-tunneld default 2>/dev/null || true
        rc-update add ios-wifi-loc default 2>/dev/null || true
        if [ -x /etc/init.d/ios-wifi-loc-tunneld ]; then
            /etc/init.d/ios-wifi-loc-tunneld restart 2>/dev/null || /etc/init.d/ios-wifi-loc-tunneld start || true
        fi
        /etc/init.d/ios-wifi-loc restart 2>/dev/null || /etc/init.d/ios-wifi-loc start || echo "没有启动 OpenRC 服务。"
    fi
fi
