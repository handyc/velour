#!/usr/bin/env python3
"""diag_int8.py — diagnose where int8 forward (officesoulmin.c) diverges
from float forward (officesoulflt.c / PyTorch reference).

Loads a .pt checkpoint, quantises it via the same code path as
train_soul.py, then runs both float forward and a Python port of
officesoulmin.c's int8 forward on the same prompt — printing per-layer
intermediate activations side-by-side to locate the first divergence.

Usage:
  diag_int8.py /tmp/soul_chat.pt "hi"

Findings (2026-05-10): int8 mismatch is *not* a single bug.  It is
compound float→int8 quantisation noise that grows across the two
transformer layers.  Embeddings match (cos_sim ≈ 0.999), but each
attention block adds ~0.05-0.20 cos_sim drop, and the FFN adds
another ~0.05-0.10.  By layer 1's FFN, cos_sim has fallen to 0.2-0.6,
which corrupts top-1 predictions for freshly-trained models.

Concretely the matvec post_shift=1 attenuates each matvec output by
2× (output scale 2^7 vs input 2^8), and softmax_weighted_sum's
`scores >> 14` step truncates dot-products to integers — both are
substantial rounding events.  rms_norm rescales between blocks, so
the model doesn't crash, but cumulative top-1 corruption breaks
generation.

The legacy soul.bin in velour_models/ was trained with a slightly
different architecture (SL=80, different state-dict naming) and
happens to land in a region of weight-space where int8 noise still
preserves top-1 — i.e. it is an int8-tolerant lottery ticket, not
something train_soul.py reproduces.

Fix paths (all substantial, none done):
  - Quantization-aware training (round during forward, straight-through
    backward).
  - Higher-precision activations (int24 / float16) with int8 weights.
  - Per-tensor calibrated post_shift, chosen to preserve specific
    activation magnitudes rather than fixed=1.

For now, officesoulflt + officemoe (float inference) sidesteps the
issue at ~120 KB/specialist instead of ~33 KB.  Re-run this script
after any int8 work to verify per-layer cos_sim recovers towards 1.0.
"""
import json, math, struct, sys
from pathlib import Path
import numpy as np

import torch

sys.path.insert(0, str(Path(__file__).parent))
from train_soul import (BPETokenizer, Soul, build_examples,
                        quant_w8, quant_w16_at, serialise_soul,
                        VS, ED, NH, HD, FF, NL, SL, PAD, SEP)

ACT_SHIFT = 8


# ── int8 reference forward, mirroring officesoulmin.c exactly ────
def sat16(v):
    if v >  32767: return  32767
    if v < -32768: return -32768
    return int(v)

def sar32(v, sh):
    if sh >= 0: return int(v) >> sh
    return int(v) << (-sh)

def isqrt_u32(v):
    if v <= 0: return 0
    return int(math.isqrt(v))

def deshift(v, s):
    diff = ACT_SHIFT - s
    if diff >= 0: return int(v) << diff
    return int(v) >> (-diff)

EXP_LUT = [round(255 * math.exp(-i / 16.0)) for i in range(128)]


class Q8:
    def __init__(self, q, s):
        self.q = np.asarray(q, dtype=np.int8)
        self.s = int(s)

class Q16:
    def __init__(self, q, s):
        self.q = np.asarray(q, dtype=np.int16)
        self.s = int(s)


def matvec(W: Q8, x, rows, cols, post_shift):
    total = W.s + post_shift
    out = np.zeros(rows, dtype=np.int32)
    Wq = W.q.reshape(rows, cols).astype(np.int32)
    xv = np.asarray(x, dtype=np.int32)
    acc = (Wq * xv[None, :]).sum(axis=1)
    for r in range(rows):
        out[r] = sat16(sar32(int(acc[r]), total))
    return out.astype(np.int16)

def matvec_bias16(W: Q8, B: Q16, x, rows, cols, post_shift):
    total = W.s + post_shift
    out = np.zeros(rows, dtype=np.int32)
    Wq = W.q.reshape(rows, cols).astype(np.int32)
    xv = np.asarray(x, dtype=np.int32)
    bv = B.q.astype(np.int32)
    acc = (Wq * xv[None, :]).sum(axis=1) + bv
    for r in range(rows):
        out[r] = sat16(sar32(int(acc[r]), total))
    return out.astype(np.int16)

def rms_norm(x, gain: Q8, n):
    sum_sq = 0
    for i in range(n):
        xs = int(x[i]) >> 4
        sum_sq += xs * xs
    mean_sq = max(1, sum_sq // n)
    rms = max(1, isqrt_u32(mean_sq))
    inv = (1 << 19) // rms
    if inv > 32767: inv = 32767
    out = np.zeros(n, dtype=np.int16)
    for i in range(n):
        y_raw = (int(x[i]) * inv) >> 15
        y = (y_raw * int(gain.q[i])) >> gain.s
        out[i] = sat16(y)
    return out

def softmax_weighted_sum(scores, n_keys, vals, hd):
    sf = [int(s) >> 14 for s in scores[:n_keys]]
    max_sf = max(sf)
    w = []
    w_sum = 0
    for i in range(n_keys):
        d = max(0, min(127, max_sf - sf[i]))
        w.append(EXP_LUT[d])
        w_sum += EXP_LUT[d]
    if w_sum == 0: w_sum = 1
    out = np.zeros(hd, dtype=np.int16)
    for j in range(hd):
        acc = 0
        for i in range(n_keys):
            acc += w[i] * int(vals[i][j])
        out[j] = sat16(acc // w_sum)
    return out


def int8_forward(weights, ids, T, *, capture=None):
    """Returns (logits, intermediates).  weights = dict of Q8/Q16 layers."""
    h = np.zeros((SL, ED), dtype=np.int16)
    for t in range(T):
        tok = ids[t]
        for d in range(ED):
            v = (deshift(int(weights['te'].q[tok * ED + d]), weights['te'].s)
               + deshift(int(weights['pe'].q[t   * ED + d]), weights['pe'].s))
            h[t, d] = sat16(v)
    if capture is not None: capture['embed'] = h.copy()

    q_all = np.zeros((SL, ED), dtype=np.int16)
    k_all = np.zeros((SL, ED), dtype=np.int16)
    v_all = np.zeros((SL, ED), dtype=np.int16)
    att_n = np.zeros((SL, ED), dtype=np.int16)

    for L in range(NL):
        ly = weights[f'layer{L}']
        for t in range(T):
            xn = rms_norm(h[t], ly['n1'], ED)
            q_all[t] = matvec(ly['q'], xn, ED, ED, 1)
            k_all[t] = matvec(ly['k'], xn, ED, ED, 1)
            v_all[t] = matvec(ly['v'], xn, ED, ED, 1)
        if capture is not None:
            capture[f'layer{L}_qkv_q'] = q_all[:T].copy()
            capture[f'layer{L}_qkv_k'] = k_all[:T].copy()
            capture[f'layer{L}_qkv_v'] = v_all[:T].copy()
        for tq in range(T):
            for head in range(NH):
                off = head * HD
                n_keys = tq + 1
                scores = []
                v_head = []
                for tk in range(n_keys):
                    s = 0
                    for d in range(HD):
                        s += int(q_all[tq, off + d]) * int(k_all[tk, off + d])
                    scores.append(s)
                    v_head.append([int(v_all[tk, off + d]) for d in range(HD)])
                out_head = softmax_weighted_sum(scores, n_keys, v_head, HD)
                for d in range(HD):
                    att_n[tq, off + d] = out_head[d]
        for t in range(T):
            att_proj = matvec(ly['proj'], att_n[t], ED, ED, 1)
            for d in range(ED):
                h[t, d] = sat16(int(h[t, d]) + int(att_proj[d]))
        if capture is not None:
            capture[f'layer{L}_after_attn'] = h[:T].copy()
        for t in range(T):
            yn = rms_norm(h[t], ly['n2'], ED)
            z  = matvec_bias16(ly['fc1_w'], ly['fc1_b'], yn, FF, ED, 1)
            z  = np.where(z < 0, 0, z).astype(np.int16)
            w2 = matvec_bias16(ly['fc2_w'], ly['fc2_b'], z, ED, FF, 1)
            for d in range(ED):
                h[t, d] = sat16(int(h[t, d]) + int(w2[d]))
        if capture is not None:
            capture[f'layer{L}_after_ffn'] = h[:T].copy()

    y = rms_norm(h[T - 1], weights['norm'], ED)
    logits = matvec(weights['out'], y, VS, ED, 0)
    return logits, capture


def quantise_model(model: Soul):
    w = {}
    q, s = quant_w8(model.te.weight); w['te'] = Q8(q.reshape(-1), s)
    q, s = quant_w8(model.pe.weight); w['pe'] = Q8(q.reshape(-1), s)
    for L, ly in enumerate(model.layers):
        d = {}
        q, s = quant_w8(ly.n1.w);            d['n1'] = Q8(q.reshape(-1), s)
        q, s = quant_w8(ly.att.q.weight);    d['q'] = Q8(q.reshape(-1), s)
        q, s = quant_w8(ly.att.k.weight);    d['k'] = Q8(q.reshape(-1), s)
        q, s = quant_w8(ly.att.v.weight);    d['v'] = Q8(q.reshape(-1), s)
        q, s = quant_w8(ly.att.proj.weight); d['proj'] = Q8(q.reshape(-1), s)
        q, s = quant_w8(ly.n2.w);            d['n2'] = Q8(q.reshape(-1), s)
        q1, s1 = quant_w8(ly.ffn.fc1.weight); d['fc1_w'] = Q8(q1.reshape(-1), s1)
        b_shift1 = s1 + 8
        d['fc1_b'] = Q16(quant_w16_at(ly.ffn.fc1.bias, b_shift1).reshape(-1), b_shift1)
        q2, s2 = quant_w8(ly.ffn.fc2.weight); d['fc2_w'] = Q8(q2.reshape(-1), s2)
        b_shift2 = s2 + 8
        d['fc2_b'] = Q16(quant_w16_at(ly.ffn.fc2.bias, b_shift2).reshape(-1), b_shift2)
        w[f'layer{L}'] = d
    q, s = quant_w8(model.norm.w); w['norm'] = Q8(q.reshape(-1), s)
    q, s = quant_w8(model.out.weight); w['out'] = Q8(q.reshape(-1), s)
    return w


def float_forward_with_capture(model: Soul, ids):
    model.eval()
    captures = {}
    with torch.no_grad():
        x_in = torch.tensor([ids], dtype=torch.long)
        T = len(ids)
        x = model.te(x_in) + model.pe(torch.arange(T))
        captures['embed'] = x[0].numpy()
        mask = torch.triu(torch.ones(T, T, dtype=torch.bool), diagonal=1)
        for L, ly in enumerate(model.layers):
            x = x + ly.att(ly.n1(x), mask)
            captures[f'layer{L}_after_attn'] = x[0].numpy()
            x = x + ly.ffn(ly.n2(x))
            captures[f'layer{L}_after_ffn'] = x[0].numpy()
        x = model.norm(x)
        logits = model.out(x)
    return logits[0, T - 1].numpy(), captures


def main():
    pt_path  = Path(sys.argv[1])
    prompt   = sys.argv[2]
    tok_path = Path('velour_models/tokenizer.json')

    sd = torch.load(pt_path, map_location='cpu', weights_only=False)
    model = Soul()
    model.load_state_dict(sd)

    tok = BPETokenizer(json.loads(tok_path.read_text()))
    body = tok.encode(prompt.lower(), cap=SL - 2)
    ids = [SEP] + body + [SEP]
    T = len(ids)
    print(f"prompt={prompt!r}")
    print(f"ids={ids}")

    # Float forward
    fl_logits, fl_cap = float_forward_with_capture(model, ids)
    fl_top5 = np.argsort(-fl_logits)[:5]
    print(f"\n[float] top-5 next-token: {fl_top5} "
          f"vals={[round(float(fl_logits[i]), 3) for i in fl_top5]}")

    # Int8 quant + forward
    weights = quantise_model(model)
    int_cap = {}
    int_logits, _ = int8_forward(weights, ids, T, capture=int_cap)
    int_top5 = np.argsort(-int_logits)[:5]
    print(f"[int8 ] top-5 next-token: {int_top5} "
          f"vals={[int(int_logits[i]) for i in int_top5]}")

    # Per-layer divergence summary
    print("\n[per-layer divergence after embed / each block]")
    for key in ['embed', 'layer0_after_attn', 'layer0_after_ffn',
                'layer1_after_attn', 'layer1_after_ffn']:
        if key not in fl_cap or key not in int_cap:
            continue
        fl = fl_cap[key]              # (T, ED) float
        it = int_cap[key].astype(float)  # (T, ED) int16
        # int values are at scale 2^8, so divide
        it_eq = it / 256.0
        # Use last-position vector for compactness
        fl_v = fl[T - 1]
        it_v = it_eq[T - 1]
        cos = float(fl_v @ it_v) / (float(np.linalg.norm(fl_v)) *
                                    float(np.linalg.norm(it_v)) + 1e-9)
        rel = float(np.linalg.norm(fl_v - it_v)) / (float(np.linalg.norm(fl_v)) + 1e-9)
        print(f"  {key:24s}  cos_sim={cos:+.4f}  "
              f"rel_err={rel:.4f}  "
              f"fl_norm={float(np.linalg.norm(fl_v)):.3f}  "
              f"it_norm={float(np.linalg.norm(it_v)):.3f}")


if __name__ == '__main__':
    main()
