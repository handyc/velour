#!/bin/sh
# test_officemoe.sh — exercise both routing modes on a battery of
# in-corpus and out-of-corpus prompts.  Reports the chosen specialist
# (via --verbose) plus the generated answer.
#
# Assumes /tmp/officemoe + /tmp/officesoulflt_{chat,apps,theory,mood}
# are built (run build_officemoe.sh first).
set -u

run_one() {
    local prompt="$1"
    local mode_flag="$2"
    local mode_label="$3"
    printf "  %-7s " "$mode_label"
    /tmp/officemoe $mode_flag -v --temp 0 --max 18 "$prompt" 2>/tmp/moe.err
    awk '{
        if (match($0, /\[moe->[a-z]+/)) {
            kind = substr($0, RSTART + 6, RLENGTH - 6)
            sub(/^\[moe->[^\]]*\] /, "")
            printf "  [%s]\n", kind
        }
    }' /tmp/moe.err
    rm -f /tmp/moe.err
}

prompts="
hi
thank you
where am i
what is velour
what is gary
what is hxhnt
what is rmsnorm
what is bpe
what is attention
i'm tired
my code crashed
tell me something
i fixed it
good morning
i love you
what is a hex
i'm overwhelmed
what is dropout
what is adam
i'm anxious
"

echo "=== test battery (each prompt: keyword vs best-of-N) ==="
echo "$prompts" | while IFS= read -r p; do
    [ -z "$p" ] && continue
    printf "PROMPT: %s\n" "$p"
    run_one "$p" "--keyword" "kw"
    run_one "$p" ""          "bofN"
done
