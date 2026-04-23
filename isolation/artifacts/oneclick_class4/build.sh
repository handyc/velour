#!/bin/sh
# Build the hunter binary: engine bytes + 4096-byte random seed = ~14-16 KB.
#
# Usage:
#   ./build.sh              # fresh random seed
#   ./build.sh winner_1     # reuse an existing winner's tail as new seed
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
# -Os: optimize for size; gc-sections: drop unused library code.
# No -lm: we inline fabs() in hunter.c to avoid pulling in libm.
cc -Os -s -Wall \
   -ffunction-sections -fdata-sections \
   -Wl,--gc-sections \
   "$HERE/hunter.c" -o "$HERE/hunter_engine"

if [ $# -ge 1 ] && [ -f "$1" ]; then
    # Slice off the tail 4096 bytes of an existing hunter binary
    echo "reusing seed from: $1"
    tail -c 4096 "$1" > "$HERE/seed.bin"
else
    # Fresh 4096-byte random seed
    dd if=/dev/urandom of="$HERE/seed.bin" bs=1 count=4096 status=none
fi

cat "$HERE/hunter_engine" "$HERE/seed.bin" > "$HERE/hunter"
chmod +x "$HERE/hunter"
rm -f "$HERE/hunter_engine" "$HERE/seed.bin"

printf 'built %s (%d bytes)\n' "$HERE/hunter" "$(stat -c%s "$HERE/hunter")"
