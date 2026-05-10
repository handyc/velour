#!/bin/sh
# build_officemoe.sh — bake each trained specialist .pt into a
# soul_data_float_<name>.h header and compile officesoulflt against
# it, then compile the moe router.  Outputs land in /tmp.
#
# Inputs (one per specialist, default /tmp/soul_<name>.pt):
#   /tmp/soul_chat.pt   /tmp/soul_apps.pt
#   /tmp/soul_theory.pt /tmp/soul_mood.pt
# Outputs:
#   /tmp/officesoulflt_<name>   (~120 KB each)
#   /tmp/officemoe              (~14 KB)
#   /tmp/soul_data_float_<name>.h
set -e

SOULPLAYER=/home/handyc/claubsh/velour-dev/isolation/artifacts/soulplayer
OFFICE=/home/handyc/claubsh/velour-dev/isolation/artifacts/office
PY=/home/handyc/claubsh/velour-dev/venv/bin/python
TOK=$SOULPLAYER/velour_models/tokenizer.json
CFLAGS="-Os -nostdlib -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables -static"

cd "$SOULPLAYER"
for name in chat apps theory mood router; do
    pt=/tmp/soul_${name}.pt
    hdr=/tmp/soul_data_float_${name}.h
    if [ ! -f "$pt" ]; then
        echo "missing $pt — train first" >&2
        exit 1
    fi
    "$PY" bake_soul_float.py "$pt" "$TOK" "$hdr"
done

cd "$OFFICE"
for name in chat apps theory mood router; do
    hdr=/tmp/soul_data_float_${name}.h
    out=/tmp/officesoulflt_${name}
    cc $CFLAGS \
       -DSOUL_HEADER="\"$hdr\"" \
       -o "$out" officesoulflt.c
    echo "built $out  ($(stat -c %s "$out") bytes)"
done

cc $CFLAGS -o /tmp/officemoe officemoe.c
echo "built /tmp/officemoe ($(stat -c %s /tmp/officemoe) bytes)"
