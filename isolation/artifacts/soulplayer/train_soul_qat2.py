#!/usr/bin/env python3
"""train_soul_qat2.py — activation-aware QAT (v2 of the experiment).

train_soul_qat.py fake-quantized *weights only* and got worse cos_sim
than plain float training:
  float-trained "hello":  embed 1.00 → l0_attn 0.84 → final 0.48
  qat-trained  "hello":  embed 1.00 → l0_attn 0.61 → final 0.20

Its docstring identified the gap: officesoulmin.c also rounds
*activations* (int16 at scale 2^8 between layers) and halves each
matvec output (post_shift=1 right-shifts by w_shift+1 instead of
w_shift, giving 2× attenuation per matvec).  Weight-only QAT doesn't
know about either, so the trained activations land at scales that
don't match what the int8 forward expects.

This script extends QAT by:
  1) Fake-quantizing weights (as before; round-to-int8 STE).
  2) Fake-quantizing activations between blocks to int16 at scale 2^8
     (round to 1/256 and clamp to ±128, the int16/scale range).
  3) Attenuating each matvec output by 0.5 in the forward, mirroring
     post_shift=1 in matvec()/matvec_bias16().

If this still doesn't close cos_sim, the remaining suspects are:
  - softmax's `scores >> 14` step (would need EXP_LUT path in
    training, currently F.softmax over raw scores)
  - rms_norm's isqrt arithmetic (currently float rms in training)

Usage (mirrors train_soul_qat.py):
  python3 train_soul_qat2.py --corpus my.txt --out /tmp/qat2.bin

After training, diag_int8 the resulting .pt the same way to compare.
"""
import argparse, json, math, sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
from train_soul import (BPETokenizer, build_examples,
                        serialise_soul, train_loop, pad,
                        VS, ED, NH, HD, FF, NL, SL, PAD, SEP)


ACT_SHIFT  = 8                  # activations live at scale 2^8 (int16)
ACT_MAX    = 32767.0 / 256.0    #  ≈ 127.996
ACT_MIN    = -32768.0 / 256.0   # = -128.0
MATVEC_ATTN = 0.5               # post_shift=1 → ×0.5 per matvec


# ── fake-quant: weight (int8) and activation (int16 at 2^8) ──
def fake_quantize_w8(w):
    max_abs = w.detach().abs().max().clamp(min=1e-9)
    shift = torch.floor(torch.log2(127.0 / max_abs))
    shift = shift.clamp(-7, 14)
    scale = (2.0 ** shift)
    q = (w * scale).round().clamp(-128, 127)
    fake = q / scale
    return w + (fake - w).detach()


def fake_quantize_act(x):
    """Round to 1/256 increments, clamp to ±128 (int16 at scale 2^8)."""
    q = (x * 256.0).round().clamp(-32768.0, 32767.0) / 256.0
    return x + (q - x).detach()


# ── layers ────────────────────────────────────────────────
class QATLinear(nn.Module):
    """Linear with weight fake-quant + ×0.5 output attenuation."""
    def __init__(self, in_f, out_f, bias=False):
        super().__init__()
        self.weight = nn.Parameter(torch.empty(out_f, in_f))
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        if bias:
            self.bias = nn.Parameter(torch.zeros(out_f))
        else:
            self.bias = None

    def forward(self, x):
        w = fake_quantize_w8(self.weight)
        y = F.linear(x, w, self.bias)
        return y * MATVEC_ATTN


class QATEmbedding(nn.Module):
    def __init__(self, n, d):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(n, d) * 0.02)

    def forward(self, ids):
        w = fake_quantize_w8(self.weight)
        return F.embedding(ids, w)


class QATRMSNorm(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))

    def forward(self, x):
        rms = x.pow(2).mean(-1, keepdim=True).add(1e-6).sqrt()
        gain = fake_quantize_w8(self.w)
        return x / rms * gain


class QATAttention(nn.Module):
    def __init__(self):
        super().__init__()
        self.q = QATLinear(ED, ED, bias=False)
        self.k = QATLinear(ED, ED, bias=False)
        self.v = QATLinear(ED, ED, bias=False)
        self.proj = QATLinear(ED, ED, bias=False)

    def forward(self, x, mask):
        B, T, _ = x.shape
        q = self.q(x).view(B, T, NH, HD).transpose(1, 2)
        k = self.k(x).view(B, T, NH, HD).transpose(1, 2)
        v = self.v(x).view(B, T, NH, HD).transpose(1, 2)
        scores = (q @ k.transpose(-2, -1))
        scores = scores.masked_fill(mask, float('-inf'))
        attn = F.softmax(scores, dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(B, T, ED)
        return self.proj(out)


class QATFFN(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = QATLinear(ED, FF, bias=True)
        self.fc2 = QATLinear(FF, ED, bias=True)

    def forward(self, x):
        return self.fc2(F.relu(self.fc1(x)))


class QATBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.n1 = QATRMSNorm(ED)
        self.att = QATAttention()
        self.n2 = QATRMSNorm(ED)
        self.ffn = QATFFN()

    def forward(self, x, mask):
        # Round/clamp residual stream between sub-blocks so the FFN
        # input is what the int8 forward will see.
        x = fake_quantize_act(x + self.att(self.n1(x), mask))
        x = fake_quantize_act(x + self.ffn(self.n2(x)))
        return x


class QATSoul(nn.Module):
    def __init__(self):
        super().__init__()
        self.te = QATEmbedding(VS, ED)
        self.pe = QATEmbedding(SL, ED)
        self.layers = nn.ModuleList([QATBlock() for _ in range(NL)])
        self.norm = QATRMSNorm(ED)
        self.out = QATLinear(ED, VS, bias=False)

    def forward(self, ids):
        B, T = ids.shape
        pos = torch.arange(T, device=ids.device)
        x = fake_quantize_act(self.te(ids) + self.pe(pos))
        mask = torch.triu(torch.ones(T, T, dtype=torch.bool, device=ids.device),
                          diagonal=1)
        for ly in self.layers:
            x = ly(x, mask)
        x = self.norm(x)
        return self.out(x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--tokenizer', default='tokenizer.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--epochs', type=int, default=8000)
    ap.add_argument('--batch',  type=int, default=8)
    ap.add_argument('--lr',     type=float, default=3e-3)
    ap.add_argument('--seed',   type=int, default=42)
    ap.add_argument('--log_every', type=int, default=2000)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = 'cpu'

    tok = BPETokenizer(json.loads(Path(args.tokenizer).read_text()))
    text = Path(args.corpus).read_text()
    examples = build_examples(text, tok)
    if not examples:
        print("error: no <SEP>-delimited examples found", file=sys.stderr)
        sys.exit(1)
    print(f"corpus: {len(text)} bytes -> {len(examples)} examples", flush=True)

    model = QATSoul().to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model: {n_params} params "
          f"(QAT v2 — weights+activations fake-quantized, matvec ×0.5)",
          flush=True)

    train_loop(model, examples, args.epochs, args.lr, args.batch,
               args.log_every, device)

    pt_out = Path(args.out).with_suffix('.pt')
    sd = model.state_dict()
    torch.save(sd, pt_out)
    print(f"saved torch checkpoint: {pt_out}", flush=True)

    soul_bytes = serialise_soul(model)
    Path(args.out).write_bytes(soul_bytes)
    print(f"saved soul.bin: {args.out}  ({len(soul_bytes)} bytes)", flush=True)


if __name__ == '__main__':
    main()
