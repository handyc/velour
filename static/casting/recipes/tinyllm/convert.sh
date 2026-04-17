#!/bin/bash
# convert.sh — HuggingFace checkpoint -> GGUF for llama.cpp / ollama / wllama.
#
# Usage: bash convert.sh <checkpoint-dir>       (default: tinyllm-out)
#        LLAMA_CPP=/path/to/llama.cpp bash convert.sh ...
#
# On first run this clones llama.cpp and installs its Python requirements.
# If your llama.cpp is older, the conversion script may be named
# convert-hf-to-gguf.py (with hyphens) instead of convert_hf_to_gguf.py.
set -euo pipefail

CKPT=${1:-tinyllm-out}
OUT=${OUT:-tinyllm.gguf}
LLAMA_CPP=${LLAMA_CPP:-./llama.cpp}

if [ ! -d "$LLAMA_CPP" ]; then
    echo "cloning llama.cpp into $LLAMA_CPP ..."
    git clone --depth=1 https://github.com/ggml-org/llama.cpp "$LLAMA_CPP"
    (cd "$LLAMA_CPP" && pip install -r requirements.txt)
fi

SCRIPT="$LLAMA_CPP/convert_hf_to_gguf.py"
if [ ! -f "$SCRIPT" ]; then
    SCRIPT="$LLAMA_CPP/convert-hf-to-gguf.py"   # older naming
fi
if [ ! -f "$SCRIPT" ]; then
    echo "cannot find convert_hf_to_gguf.py in $LLAMA_CPP"
    exit 1
fi

python "$SCRIPT" "$CKPT" --outfile "$OUT"
echo "wrote $OUT"

# Optional quantization (requires a built llama.cpp):
#   cmake -B $LLAMA_CPP/build -DGGML_NATIVE=ON
#   cmake --build $LLAMA_CPP/build --target llama-quantize -j
#   $LLAMA_CPP/build/bin/llama-quantize $OUT tinyllm-q8_0.gguf q8_0
