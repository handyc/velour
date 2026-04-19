# Piper voices

Drop per-language ONNX voice models here. The `speak` endpoint in
`lingua/views.py` prefers Piper when a matching model is present and
falls back to `espeak-ng` otherwise.

The `.onnx` and `.onnx.json` files are gitignored — each is ~60 MB and
installs per-machine. Filenames must match the keys in `PIPER_VOICE`
in `lingua/views.py`.

## Installing a voice

```
cd lingua/data/piper_voices/
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

# French (siwis, medium)
curl -fsSL -O "$BASE/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx"
curl -fsSL -O "$BASE/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json"

# Mandarin Chinese (huayan, medium)
curl -fsSL -O "$BASE/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
curl -fsSL -O "$BASE/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"
```

Browse the full voice catalog at
<https://huggingface.co/rhasspy/piper-voices/tree/main>.

## Python dependency

```
venv/bin/python -m pip install piper-tts
```
