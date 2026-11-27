#!/bin/sh
set -eu
if ! python3 -c "import ios_wifi_loc" 2>/dev/null; then
  echo "本工具未安装，没有可删除的启动脚本。" >&2
  exit 2
fi
exec python3 -m ios_wifi_loc uninstall "$@"
