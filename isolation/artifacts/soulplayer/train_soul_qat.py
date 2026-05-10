#!/usr/bin/env python3
"""train_soul_qat.py — quantization-aware-training fork of train_soul.py.

**Outcome (2026-05-10):** weight-only QAT did NOT fix the int8
mismatch.  Diag on theory soul:
  - float-trained:  embed cos_sim 0.999 → layer0_attn 0.84 → final 0.37
  - QAT-trained:    embed cos_sim 0.999 → layer0_attn -0.10 → final 0.08

Why it failed: with adaptive per-tensor shift, fake-quantizing weights
encourages the model to drift to a region where weights round cleanly,
but the activation magnitudes drift along with them (embed norms
dropped 7× from 6.9 to 0.93 in QAT).  officesoulmin.c uses a FIXED
activation scale (ACT_SHIFT=8) and a fixed post_shift=1 attenuation
per matvec; QAT doesn't know about either, so the trained activation
scales no longer match what the int8 forward expects.  Float inference
on the QAT model still works fine (same answers as the float-trained
soul), but feeding the same weights through serialise_soul →
officesoulmin produces gibberish, just like before.

**What would actually fix it (not done):** simulate the full int8
forward in PyTorch — quantize *activations* to int16 at scale 2^8,
right-shift by post_shift=1 after each matmul, replicate the EXP_LUT
softmax and isqrt rms_norm — and put the STE through *all* of those.
That makes the network solve the actual constrained-arithmetic
problem, not a weight-rounding stand-in.  ~1-2 days of work.

For now, officesoulflt + officemoe (float inference, ~120 KB) remain
the only path that produces working output from freshly-trained souls.

Usage (kept for future experiments — runs but produces no useful
int8 model):
  python3 train_soul_qat.py --corpus my_corpus.txt --out /tmp/qat.bin
"""
import argparse, json, math, sys, time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parent))
from train_soul import (BPETokenizer, RMSNorm, Block, build_examples,
                        serialise_soul, train_loop, pad,
                        VS, ED, NH, HD, FF, NL, SL, PAD, SEP)


# ── fake-quantize ────────────────────────────────────────────
def fake_quantize_w8(w):
    """Round-trip through symmetric int8 (per-tensor shift) with STE."""
    max_abs = w.detach().abs().max().clamp(min=1e-9)
    shift = torch.floor(torch.log2(127.0 / max_abs))
    shift = shift.clamp(-7, 14)
    scale = (2.0 ** shift)
    q = (w * scale).round().clamp(-128, 127)
    fake = q / scale
    return w + (fake - w).detach()


class QATLinear(nn.Module):
    """Linear with fake-quantized weight on forward."""
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
        return F.linear(x, w, self.bias)


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
        # Fake-quantize the gain (loaded as int8 in officesoulmin).
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
        x = x + self.att(self.n1(x), mask)
        x = x + self.ffn(self.n2(x))
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
        x = self.te(ids) + self.pe(pos)
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
    print(f"model: {n_params} params (QAT — weights fake-quantized to int8)",
          flush=True)

    train_loop(model, examples, args.epochs, args.lr, args.batch,
               args.log_every, device)

    # Save .pt with the same key names as the float Soul, so existing
    # bake_soul_float.py / serialise_soul work without changes.
    pt_out = Path(args.out).with_suffix('.pt')
    sd = model.state_dict()
    torch.save(sd, pt_out)
    print(f"saved torch checkpoint: {pt_out}", flush=True)

    # Pack via the existing serialise_soul (same per-tensor int8 quant).
    soul_bytes = serialise_soul(model)
    Path(args.out).write_bytes(soul_bytes)
    print(f"saved soul.bin: {args.out}  ({len(soul_bytes)} bytes)", flush=True)


if __name__ == '__main__':
    main()
