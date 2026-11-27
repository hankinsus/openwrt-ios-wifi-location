#!/bin/sh
# Archive the committed tree. Refuses to include untracked pairing material
# because git archive only packs tracked files.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
version=$(PYTHONPATH="$root/src" python3 -c "from ios_wifi_loc import __version__; print(__version__)")
mkdir -p "$root/dist"
out="$root/dist/ios-wifi-loc-$version-source.tar.gz"
git -C "$root" archive --format=tar.gz --prefix="ios-wifi-loc-$version/" -o "$out" HEAD
echo "$out"
