#!/bin/bash
# Host smoke test for xcc_embedded — build + run, plus diff against
# the vendor CLI to confirm both paths produce the same ELF.
set -euo pipefail
cd "$(dirname "$0")"

echo "[1/3] building embedded test binary..."
gcc -O2 -w -o test_host test_host.c xcc_shim.c xcc_vendor_wrap.c

echo "[2/3] running in-process compile..."
./test_host -o /tmp/xcc_emb.elf

echo "[3/3] cross-checking vs vendor CLI..."
if [ ! -x ../xcc700 ]; then
    (cd .. && ./build.sh)
fi
echo 'int main() {
  int x = 42;
  return x;
}' > /tmp/xcc_in.c
../xcc700 /tmp/xcc_in.c -o /tmp/xcc_cli.elf >/dev/null

if cmp /tmp/xcc_emb.elf /tmp/xcc_cli.elf; then
    echo "OK: embedded ELF == CLI ELF (byte-for-byte)"
else
    echo "MISMATCH: embedded ELF differs from CLI ELF"
    ls -la /tmp/xcc_emb.elf /tmp/xcc_cli.elf
    exit 1
fi
