#!/bin/sh
set -eu
umask 077
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cache="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tablet"
mkdir -p "$cache"
exec 9>"$cache/sensor-build.lock"
flock 9
source_hash=$(sha256sum "$source_dir/sensor-helper.c" "$source_dir/sensor-backend.sh")
saved_hash=""
if [ -f "$cache/sensor-source.hash" ]; then saved_hash=$(cat "$cache/sensor-source.hash"); fi
if [ ! -x "$cache/sensor-helper" ] || [ "$source_hash" != "$saved_hash" ]; then
  cc -O2 -Wall -Wextra -Werror "$source_dir/sensor-helper.c" $(pkg-config --cflags --libs gio-2.0) -o "$cache/sensor-helper.tmp"
  mv "$cache/sensor-helper.tmp" "$cache/sensor-helper"
  printf '%s\n' "$source_hash" > "$cache/sensor-source.hash"
fi
flock -u 9
exec 9>&-
exec "$cache/sensor-helper" "$@"
