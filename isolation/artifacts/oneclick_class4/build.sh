#!/bin/sh
# Build the hunter binary: engine bytes + 4-byte palette + 4096-byte genome.
# Tail is 4100 bytes; total ~14-16 KB after -Os -s.
#
# Usage:
#   ./build.sh              # fresh random palette + identity genome
#   ./build.sh winner_1     # reuse an existing winner's full tail (pal+genome)
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
# -Os: optimize for size; gc-sections: drop unused library code.
# No -lm: we inline fabs() in hunter.c to avoid pulling in libm.
cc -Os -s -Wall \
   -ffunction-sections -fdata-sections \
   -Wl,--gc-sections \
   "$HERE/hunter.c" -o "$HERE/hunter_engine"

if [ $# -ge 1 ] && [ -f "$1" ]; then
    # Slice off the tail 4100 bytes of an existing hunter binary:
    # [4-byte palette][4096-byte genome]. Both inherited wholesale.
    echo "reusing seed from: $1"
    tail -c 4100 "$1" > "$HERE/seed.bin"
else
    # Default seed: random palette + IDENTITY genome.
    #
    # Palette: 4 distinct ANSI-256 indices, mostly from the saturated
    # 6×6×6 cube (16..231), occasional greys (232..255). Matches
    # invent_palette() in hunter.c so a fresh build looks just like a
    # palette-mutated descendant.
    #
    # Genome: every situation → self-colour (activity=0 floor).
    # Random-chaos seeds leave the GA stuck at ~75% activity with no
    # gradient to escape; identity climbs smoothly toward class-4.
    #
    # Encoding: situations are indexed by (self*K^6 + n0*K^5 + … + n5)
    # and packed 2 bits per output, 4 per byte. For K=4:
    #   self=0 → outputs all 0 → bytes 0000..1023 == 0x00
    #   self=1 → outputs all 1 → bytes 1024..2047 == 0x55 (01010101)
    #   self=2 → outputs all 2 → bytes 2048..3071 == 0xAA (10101010)
    #   self=3 → outputs all 3 → bytes 3072..4095 == 0xFF (11111111)
    echo "creating random palette + identity seed"
    python3 -c "
import random, sys
pal = []
while len(pal) < 4:
    c = random.randint(16, 231) if random.random() < 0.9 \
        else random.randint(232, 255)
    if c not in pal: pal.append(c)
sys.stdout.buffer.write(bytes(pal))
sys.stdout.buffer.write(b'\x00' * 1024 + b'\x55' * 1024
                        + b'\xaa' * 1024 + b'\xff' * 1024)
sys.stderr.write(f'palette = {pal}\n')
" > "$HERE/seed.bin"
fi

cat "$HERE/hunter_engine" "$HERE/seed.bin" > "$HERE/hunter"
chmod +x "$HERE/hunter"
rm -f "$HERE/hunter_engine" "$HERE/seed.bin"

printf 'built %s (%d bytes)\n' "$HERE/hunter" "$(stat -c%s "$HERE/hunter")"
