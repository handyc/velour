#!/usr/bin/env python3
"""diag_int8_qat.py — like diag_int8.py but uses QATSoul (with matvec
attenuation + activation rounding) as the float reference, not the
plain Soul.

Reason: QAT v2 trains a model whose forward has ×0.5 per-matvec
attenuation.  diag_int8.py imports Soul (no attenuation) and loads
the state_dict into it, so its "float forward" is *not* what the
model was trained against.  Cos_sim numbers then look bad even when
the int8 output actually matches the trained float behaviour.

This script loads the QATSoul forward directly and quantises the same
weights via the existing serialise_soul path, then runs int8_forward
from diag_int8.  Layer-wise cos_sim and top-k overlap reflect how
close the int8 forward gets to what training optimised.

Usage:
  diag_int8_qat.py /tmp/soul_theory_qat2.pt "hello"
"""
import json, sys
from pathlib import Path
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).parent))
from train_soul import BPETokenizer, SL, SEP
from train_soul_qat2 import QATSoul, fake_quantize_act
from diag_int8 import int8_forward, quantise_model


def qat_forward_with_capture(model, ids):
    """Run QATSoul forward but capture per-layer hidden states."""
    model.eval()
    captures = {}
    with torch.no_grad():
        x_in = torch.tensor([ids], dtype=torch.long)
        T = len(ids)
        x = fake_quantize_act(model.te(x_in) + model.pe(torch.arange(T)))
        captures['embed'] = x[0].numpy()
        mask = torch.triu(torch.ones(T, T, dtype=torch.bool), diagonal=1)
        for L, ly in enumerate(model.layers):
            x = fake_quantize_act(x + ly.att(ly.n1(x), mask))
            captures[f'layer{L}_after_attn'] = x[0].numpy()
            x = fake_quantize_act(x + ly.ffn(ly.n2(x)))
            captures[f'layer{L}_after_ffn'] = x[0].numpy()
        x = model.norm(x)
        logits = model.out(x)
    return logits[0, T - 1].numpy(), captures


def main():
    pt_path  = Path(sys.argv[1])
    prompt   = sys.argv[2]
    tok_path = Path('velour_models/tokenizer.json')

    sd = torch.load(pt_path, map_location='cpu', weights_only=False)
    model = QATSoul()
    model.load_state_dict(sd)

    tok = BPETokenizer(json.loads(tok_path.read_text()))
    body = tok.encode(prompt.lower(), cap=SL - 2)
    ids = [SEP] + body + [SEP]
    T = len(ids)
    print(f"prompt={prompt!r}")
    print(f"ids={ids}")

    fl_logits, fl_cap = qat_forward_with_capture(model, ids)
    fl_top5 = np.argsort(-fl_logits)[:5]
    print(f"\n[QATfloat] top-5 next-token: {fl_top5} "
          f"vals={[round(float(fl_logits[i]), 3) for i in fl_top5]}")

    weights = quantise_model(model)
    int_cap = {}
    int_logits, _ = int8_forward(weights, ids, T, capture=int_cap)
    int_top5 = np.argsort(-int_logits)[:5]
    print(f"[int8    ] top-5 next-token: {int_top5} "
          f"vals={[int(int_logits[i]) for i in int_top5]}")

    print("\n[per-layer divergence after embed / each block]")
    for key in ['embed', 'layer0_after_attn', 'layer0_after_ffn',
                'layer1_after_attn', 'layer1_after_ffn']:
        if key not in fl_cap or key not in int_cap:
            continue
        fl = fl_cap[key]
        it = int_cap[key].astype(float) / 256.0
        fl_v = fl[T - 1]
        it_v = it[T - 1]
        cos = float(fl_v @ it_v) / (float(np.linalg.norm(fl_v)) *
                                    float(np.linalg.norm(it_v)) + 1e-9)
        rel = float(np.linalg.norm(fl_v - it_v)) / (float(np.linalg.norm(fl_v)) + 1e-9)
        print(f"  {key:24s}  cos_sim={cos:+.4f}  rel_err={rel:.4f}  "
              f"fl_norm={float(np.linalg.norm(fl_v)):.3f}  "
              f"it_norm={float(np.linalg.norm(it_v)):.3f}")


if __name__ == '__main__':
    main()
