#!/bin/sh
set -eu
umask 077
# Build only on first use or when source changes; artifacts stay outside the
# plugin watcher directory. Runtime is one tiny native process while visible.
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tablet"
binary="$cache_dir/input-helper"
mkdir -p "$cache_dir"
exec 9>"$cache_dir/input-build.lock"
flock 9
source_hash=$(sha256sum "$source_dir/input-helper.c" "$source_dir/virtual-keyboard-unstable-v1.xml" "$source_dir/input-backend.sh")
saved_hash=""
if [ -f "$cache_dir/input-source.hash" ]; then saved_hash=$(cat "$cache_dir/input-source.hash"); fi
if [ ! -x "$binary" ] || [ "$source_hash" != "$saved_hash" ]; then
  wayland-scanner client-header "$source_dir/virtual-keyboard-unstable-v1.xml" "$cache_dir/virtual-keyboard.h"
  wayland-scanner private-code "$source_dir/virtual-keyboard-unstable-v1.xml" "$cache_dir/virtual-keyboard.c"
  cc -std=c11 -O2 -Wall -Wextra -Werror -I"$cache_dir" \
    "$source_dir/input-helper.c" "$cache_dir/virtual-keyboard.c" \
    $(pkg-config --cflags --libs wayland-client xkbcommon) -o "$binary.tmp"
  mv "$binary.tmp" "$binary"
  printf '%s\n' "$source_hash" > "$cache_dir/input-source.hash"
fi
flock -u 9
exec 9>&-
exec "$binary"
