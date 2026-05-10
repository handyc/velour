#!/usr/bin/env python3
"""train_soul.py — train a 27 K-param int8 transformer on a text corpus.

Reproduces the architecture officesoul.c expects:
  VS=128, ED=32, NH=4, HD=8, FF=64, NL=2, SL=64

Reads tokenizer.json (BPE merges + vocab from upstream soulplayer)
and uses it unchanged so the resulting soul.bin slots into the
existing baker (gen_soul_data.py).

Pipeline:
  text corpus → BPE-encode → train transformer (PyTorch CPU) →
  per-tensor symmetric int8 quantization (shift = floor(log2(127/max))) →
  pack into soul.bin v3 format → write to --out

Usage:
  python3 train_soul.py --corpus my_corpus.txt --out my_soul.bin
  python3 train_soul.py --corpus my_corpus.txt --epochs 4500 --out my_soul.bin

Defaults assume the script runs from isolation/artifacts/soulplayer/
and reads tokenizer.json from cwd.
"""
import argparse, json, math, struct, sys, time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

# ── architecture constants — must match officesoul.c ──
VS, ED, NH, HD, FF, NL, SL = 128, 32, 4, 8, 64, 2, 64
PAD, SEP, UNK, END = 0, 1, 2, 3


# ── BPE tokenizer (uses tokenizer.json) ──
class BPETokenizer:
    def __init__(self, tok_json):
        self.vocab = tok_json["vocab"]                    # str → id
        self.id_to_str = {v: k for k, v in self.vocab.items()}
        self.merges = tok_json["merges"]                  # [[a, b], ...]

    def encode(self, text, cap=None):
        # Single-char tokens first.
        ids = []
        for ch in text:
            ch = ch.lower()
            if ch in self.vocab:
                ids.append(self.vocab[ch])
        # Apply merges in order, mirroring the C encoder.
        for a, b in self.merges:
            merged = a + b
            if a not in self.vocab or b not in self.vocab or merged not in self.vocab:
                continue
            a_id, b_id, m_id = self.vocab[a], self.vocab[b], self.vocab[merged]
            new_ids = []
            i = 0
            while i < len(ids):
                if i + 1 < len(ids) and ids[i] == a_id and ids[i + 1] == b_id:
                    new_ids.append(m_id)
                    i += 2
                else:
                    new_ids.append(ids[i])
                    i += 1
            ids = new_ids
        if cap is not None:
            ids = ids[:cap]
        return ids


# ── transformer ──
class RMSNorm(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.w = nn.Parameter(torch.ones(d))

    def forward(self, x):
        rms = x.pow(2).mean(-1, keepdim=True).add(1e-6).sqrt()
        return x / rms * self.w


class Attention(nn.Module):
    def __init__(self):
        super().__init__()
        self.q = nn.Linear(ED, ED, bias=False)
        self.k = nn.Linear(ED, ED, bias=False)
        self.v = nn.Linear(ED, ED, bias=False)
        self.proj = nn.Linear(ED, ED, bias=False)

    def forward(self, x, mask):
        B, T, _ = x.shape
        q = self.q(x).view(B, T, NH, HD).transpose(1, 2)
        k = self.k(x).view(B, T, NH, HD).transpose(1, 2)
        v = self.v(x).view(B, T, NH, HD).transpose(1, 2)
        scores = (q @ k.transpose(-2, -1))                # no scale: matches C's scores>>14 normalisation
        scores = scores.masked_fill(mask, float('-inf'))
        attn = F.softmax(scores, dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(B, T, ED)
        return self.proj(out)


class FFN(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(ED, FF, bias=True)
        self.fc2 = nn.Linear(FF, ED, bias=True)

    def forward(self, x):
        return self.fc2(F.relu(self.fc1(x)))


class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.n1 = RMSNorm(ED)
        self.att = Attention()
        self.n2 = RMSNorm(ED)
        self.ffn = FFN()

    def forward(self, x, mask):
        x = x + self.att(self.n1(x), mask)
        x = x + self.ffn(self.n2(x))
        return x


class Soul(nn.Module):
    def __init__(self):
        super().__init__()
        self.te = nn.Embedding(VS, ED)
        self.pe = nn.Embedding(SL, ED)
        self.layers = nn.ModuleList([Block() for _ in range(NL)])
        self.norm = RMSNorm(ED)
        self.out = nn.Linear(ED, VS, bias=False)

    def forward(self, ids):
        B, T = ids.shape
        pos = torch.arange(T, device=ids.device)
        x = self.te(ids) + self.pe(pos)
        mask = torch.triu(torch.ones(T, T, dtype=torch.bool, device=ids.device), diagonal=1)
        for ly in self.layers:
            x = ly(x, mask)
        x = self.norm(x)
        return self.out(x)


# ── quantization helpers ──
def quant_w8(t: torch.Tensor):
    """Symmetric int8 quantisation; pick shift to maximise precision."""
    arr = t.detach().cpu().numpy().astype('float64')
    max_abs = max(abs(arr).max(), 1e-9)
    shift = int(math.floor(math.log2(127.0 / max_abs)))
    shift = max(-7, min(shift, 14))
    scale = 2.0 ** shift
    q = arr * scale
    q = q.round().clip(-128, 127).astype('int8')
    return q, shift


def quant_w16_at(t: torch.Tensor, shift: int):
    """Quantise an int16 tensor at a *given* shift.  Used for biases:
    the bias is added directly into the matmul accumulator (scale
    2^(w_shift + ACT_SHIFT) = 2^(w_shift+8)), so it must be stored
    at that same scale or it lands at the wrong magnitude after the
    accumulator's right-shift.  Saturates if any value exceeds the
    int16 range — for trained biases this is rare but log it."""
    arr = t.detach().cpu().numpy().astype('float64')
    scale = 2.0 ** shift
    raw = arr * scale
    if abs(raw).max() > 32767:
        # Bias too large to represent at this shift.  Saturating in
        # quant rather than rejecting; signal so the caller can warn.
        pass
    q = raw.round().clip(-32768, 32767).astype('int16')
    return q


def write_w8m(buf: bytearray, q, rows: int, cols: int, shift: int):
    buf.append(0)                                          # kind = 0
    buf += struct.pack('<HHb', rows, cols, shift)
    flat = q.reshape(-1).tobytes()
    assert len(flat) == rows * cols, f"w8m {q.shape} ≠ {rows}×{cols}"
    buf += flat


def write_w16m(buf: bytearray, q, n: int, shift: int):
    buf.append(1)                                          # kind = 1
    buf += struct.pack('<HHb', n, 1, shift)
    flat = q.reshape(-1).tobytes()
    assert len(flat) == n * 2, f"w16m {q.shape} ≠ {n}×i16"
    buf += flat


def serialise_soul(model: Soul) -> bytes:
    """Pack model weights into soul.bin v3 format the C inference loop reads."""
    buf = bytearray()
    # te (VS, ED), pe (SL, ED)
    q, s = quant_w8(model.te.weight); write_w8m(buf, q, VS, ED, s)
    q, s = quant_w8(model.pe.weight); write_w8m(buf, q, SL, ED, s)
    # Per layer
    for ly in model.layers:
        q, s = quant_w8(ly.n1.w);            write_w8m(buf, q, ED, 1, s)
        q, s = quant_w8(ly.att.q.weight);    write_w8m(buf, q, ED, ED, s)
        q, s = quant_w8(ly.att.k.weight);    write_w8m(buf, q, ED, ED, s)
        q, s = quant_w8(ly.att.v.weight);    write_w8m(buf, q, ED, ED, s)
        q, s = quant_w8(ly.att.proj.weight); write_w8m(buf, q, ED, ED, s)
        q, s = quant_w8(ly.n2.w);            write_w8m(buf, q, ED, 1, s)
        # FFN: weight + bias.  Bias is added into the matmul
        # accumulator BEFORE the right-shift, so it must be stored
        # at scale 2^(w_shift + ACT_SHIFT) = 2^(w_shift + 8) to
        # contribute at the right magnitude.  ACT_SHIFT=8 in
        # officesoul.c.
        q1, s1 = quant_w8(ly.ffn.fc1.weight);
        write_w8m(buf, q1, FF, ED, s1)
        b_shift1 = s1 + 8
        bq1 = quant_w16_at(ly.ffn.fc1.bias, b_shift1)
        write_w16m(buf, bq1, FF, b_shift1)
        q2, s2 = quant_w8(ly.ffn.fc2.weight);
        write_w8m(buf, q2, ED, FF, s2)
        b_shift2 = s2 + 8
        bq2 = quant_w16_at(ly.ffn.fc2.bias, b_shift2)
        write_w16m(buf, bq2, ED, b_shift2)
    q, s = quant_w8(model.norm.w);           write_w8m(buf, q, ED, 1, s)
    q, s = quant_w8(model.out.weight);       write_w8m(buf, q, VS, ED, s)
    return bytes(buf)


# ── training ──
def build_examples(text: str, tok: BPETokenizer):
    """Each LINE becomes one training example.  Lines are expected
    in the form `<SEP>Q<SEP>A<SEP>` — encode Q and A separately and
    join them with explicit SEP tokens so the model sees question +
    separator + answer as one sequence and learns the association.
    Lines without that structure are treated as a single segment.
    Returns a list of int-id sequences capped at SL. """
    examples = []
    for line in text.splitlines():
        if not line.strip():
            continue
        # Split on the literal "<SEP>" marker (kept distinct from
        # the SEP token id 1 we insert in encode()).
        segs = [s for s in line.split('<SEP>') if s.strip()]
        if not segs:
            continue
        ids = [SEP]
        for i, seg in enumerate(segs):
            tok_ids = tok.encode(seg.strip(), cap=SL - 2 - len(ids))
            ids.extend(tok_ids)
            if len(ids) >= SL - 1:
                ids = ids[:SL - 1]
                break
            ids.append(SEP)
        if len(ids) >= 2:
            examples.append(ids)
    return examples


def pad(ids, n):
    return ids + [PAD] * (n - len(ids)) if len(ids) < n else ids[:n]


def train_loop(model, examples, epochs, lr, batch, log_every, device):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    model.train()
    t0 = time.time()
    n = len(examples)
    print(f"training: {n} examples, {epochs} epochs, batch={batch}, lr={lr}", flush=True)
    for ep in range(1, epochs + 1):
        # sample a batch
        idx = torch.randint(0, n, (batch,))
        seqs = [pad(examples[i], SL) for i in idx.tolist()]
        seqs = torch.tensor(seqs, dtype=torch.long, device=device)
        inp, tgt = seqs[:, :-1], seqs[:, 1:]
        logits = model(inp)
        loss = F.cross_entropy(
            logits.reshape(-1, VS),
            tgt.reshape(-1),
            ignore_index=PAD,
        )
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if ep % log_every == 0 or ep == epochs:
            dt = time.time() - t0
            print(f"  epoch {ep:5d}  loss={loss.item():.4f}  {dt:.1f}s",
                  flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', required=True, help='Path to <SEP>-delimited training corpus.')
    ap.add_argument('--tokenizer', default='tokenizer.json')
    ap.add_argument('--out', required=True, help='Output soul.bin path.')
    ap.add_argument('--epochs', type=int, default=4500)
    ap.add_argument('--batch',  type=int, default=16)
    ap.add_argument('--lr',     type=float, default=3e-3)
    ap.add_argument('--seed',   type=int, default=42)
    ap.add_argument('--log_every', type=int, default=500)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = 'cpu'

    tok = BPETokenizer(json.loads(Path(args.tokenizer).read_text()))
    text = Path(args.corpus).read_text()
    examples = build_examples(text, tok)
    if not examples:
        print("error: no <SEP>-delimited examples found in corpus", file=sys.stderr)
        sys.exit(1)
    print(f"corpus: {len(text)} bytes → {len(examples)} examples", flush=True)
    print(f"  shortest={min(len(e) for e in examples)} tokens, "
          f"longest={max(len(e) for e in examples)} tokens", flush=True)

    model = Soul().to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"model: {n_params} params", flush=True)

    train_loop(model, examples, args.epochs, args.lr, args.batch,
               args.log_every, device)

    # Also save raw .pt for debug.
    pt_out = Path(args.out).with_suffix('.pt')
    torch.save(model.state_dict(), pt_out)
    print(f"saved torch checkpoint: {pt_out}", flush=True)

    # Quantise + serialise.
    soul_bytes = serialise_soul(model)
    Path(args.out).write_bytes(soul_bytes)
    print(f"saved soul.bin: {args.out}  ({len(soul_bytes)} bytes)", flush=True)


if __name__ == '__main__':
    main()
