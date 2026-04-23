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
    # Slice off the tail 4096 bytes of an existing hunter binary.
    echo "reusing seed from: $1"
    tail -c 4096 "$1" > "$HERE/seed.bin"
else
    # Default seed: the IDENTITY genome (every situation → self-colour).
    # Activity=0 is the floor the GA climbs from. Random-chaos seeds
    # leave the GA stuck at ~75% activity with no gradient to escape.
    #
    # Encoding: situations are indexed by (self*K^6 + n0*K^5 + … + n5)
    # and packed 2 bits per output, 4 per byte. For K=4:
    #   self=0 → outputs all 0 → bytes 0000..1023 == 0x00
    #   self=1 → outputs all 1 → bytes 1024..2047 == 0x55 (01010101)
    #   self=2 → outputs all 2 → bytes 2048..3071 == 0xAA (10101010)
    #   self=3 → outputs all 3 → bytes 3072..4095 == 0xFF (11111111)
    echo "creating identity seed (activity=0 starting point)"
    python3 -c "
import sys
sys.stdout.buffer.write(b'\x00' * 1024 + b'\x55' * 1024
                        + b'\xaa' * 1024 + b'\xff' * 1024)
" > "$HERE/seed.bin"
fi

cat "$HERE/hunter_engine" "$HERE/seed.bin" > "$HERE/hunter"
chmod +x "$HERE/hunter"
rm -f "$HERE/hunter_engine" "$HERE/seed.bin"

printf 'built %s (%d bytes)\n' "$HERE/hunter" "$(stat -c%s "$HERE/hunter")"
