#!/bin/sh
# If this tool is already importable, only write the service file.
# Otherwise do the full environment install.
set -eu
if python3 -c "import ios_wifi_loc" 2>/dev/null; then
    exec python3 -m ios_wifi_loc install "$@"
fi
exec "$(CDPATH= cd -- "$(dirname "$0")" && pwd)/oneclick-install.sh" "$@"
