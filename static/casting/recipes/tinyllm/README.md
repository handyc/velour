# Tiny LLM — train on a cluster, ship as GGUF, load in the browser

A complete recipe that closes the cycle Casting could not:
brute-force bit search cannot find a transformer, but gradient
descent on a GPU can. Here we train a ~11 M-parameter GPT-2 on
TinyStories (or any corpus you hand it), convert the checkpoint to
GGUF, and load it in the browser via the `gguf-wasm` Casting
experiment (wllama).

## Files

| file             | what it does                                          |
| ---------------- | ----------------------------------------------------- |
| train.py         | train a tiny GPT-2 from scratch (HuggingFace format). |
| slurm.sh         | SLURM job spec. Adjust modules for your cluster.      |
| convert.sh       | HF checkpoint → GGUF using llama.cpp's converter.     |
| requirements.txt | pip install targets.                                  |
| sample_corpus.txt| a tiny toy corpus for local smoke tests.              |

## Pipeline

```
  [corpus] ──┐
             │  train.py            slurm.sh
             ▼                      ▼
      [HF checkpoint] ── convert.sh ──► [tinyllm.gguf]
                                              │
                                              │  upload to HF or host yourself
                                              ▼
                              [gguf-wasm Casting experiment]
                              loads the GGUF in-browser via wllama
```

## Quick start — local smoke test (CPU or one GPU)

```bash
pip install -r requirements.txt
python train.py --steps 200 --batch 4 --block 128 \
                --n_embd 96 --n_layer 2 --n_head 4 \
                --corpus sample_corpus.txt
bash convert.sh tinyllm-out
```

This should produce a ~5 MB `tinyllm.gguf` in a few minutes on CPU.
It will overfit the toy corpus (by design) — the point is to confirm
the pipeline works end-to-end.

## Real run — SLURM

```bash
sbatch slurm.sh
# watch the log:
tail -f tinyllm-<jobid>.log
# once done:
bash convert.sh tinyllm-out
```

Defaults: ~11 M params, 4000 steps, block 256, batch 16. On a single
H100 this finishes in roughly 30 minutes. On an A100 roughly an hour.
The resulting tinyllm.gguf is about 40 MB (fp16) or ~12 MB after
q4_k_m quantization (see the tail of convert.sh for how to quantize).

## Load your GGUF in the browser

Upload `tinyllm.gguf` to a Hugging Face repo (or any static URL),
then in the `gguf-wasm` Casting experiment, wire in the URL via the
preset list or adapt the JS to point at your model. wllama streams
the download the first time and caches it thereafter.

## Notes and caveats

- This is the minimum viable recipe. It does not use gradient
  accumulation, cosine LR schedule, mixed precision, or any of the
  other training niceties. Add them if you care about quality.
- Byte-pair (GPT-2) vocab is 50257 tokens. The embedding alone is
  192 × 50257 ≈ 10 M parameters — a large fraction of the model. If
  you want smaller, train your own BPE tokenizer with `tokenizers`
  or use a byte-level vocab of 256.
- llama.cpp renames its conversion script periodically. If the one
  here fails to find it, look in your llama.cpp checkout for
  `convert_hf_to_gguf.py` or `convert-hf-to-gguf.py`.
- The `gguf-wasm` Casting experiment currently lists a few public
  tiny GGUFs as presets. To load your own, either upload to a public
  URL or extend the PRESETS array in the browser module.
