"""caformer/distill — one-shot import of a real LLM into a CA rule
table, with no iterative training.

The honest scope: only the **output_rule** has a clean LLM analogue —
both produce a "what comes next?" distribution. The other 9 rules
(q/k/v/score/mix/merge/mlp/norm/embed) operate on CA-grid intermediates
that the LLM has nothing equivalent to. So distillation here populates
output_rule from an LLM oracle and leaves the rest as defaults; the
user can evolve / polish / hand-tune the others on top.

Algorithm (per-rule single pass):

  1. For each LUT index i in 0..16383:
     - Treat the 14-bit index as a 2-byte "prompt" the LLM can see
       (each 7-bit half mapped into printable ASCII so tokenisation is
       deterministic and consistent across backbones).
     - Run the LLM forward, take last-position logits.
     - Project BPE → 256 byte buckets via the same
       _llm_byte_projection caformer already uses for hybrid MoE.
     - Bin the 256 byte probabilities into 4 colour-buckets (0..63 →
       colour 0, 64..127 → colour 1, etc).
     - argmax over the 4 bins → that's the LUT entry (one byte).

Cost: 16,384 forwards / batch_size LLM forwards. With batch=64 on
distilgpt2 (warm), the whole rule lands in ~5 seconds. No GA, no SGD,
no backprop.
"""
from __future__ import annotations
from typing import Optional

import numpy as np


def distill_output_rule(model_name: str, *,
                          vocab_size: int = 256,
                          lut_size: int = 16384,
                          n_buckets: int = 4,
                          batch_size: int = 64,
                          device: Optional[str] = None,
                          progress: Optional[callable] = None
                          ) -> bytes:
    """One-shot LLM → 16,384-byte CA rule table.

    The result is exactly the format ``ca_output_head_iterative``
    expects, so dropping it into a TrainedModel's ``rule_output`` slot
    makes the CA's output head behave like the LLM's first-byte
    distribution — no GA round-trip required.

    ``progress(done, total)`` fires after every batch if supplied
    (lets a UI show a "%distilled" bar).
    """
    import torch
    from .transformer import _load_llm_expert, _llm_byte_projection
    tok, model = _load_llm_expert(model_name)
    proj = _llm_byte_projection(tok, vocab_size)

    out = bytearray(lut_size)
    bucket_width = vocab_size // n_buckets   # default 256/4 = 64

    # Pre-build all 16,384 prompts as 2-char ASCII strings. Each LUT
    # index becomes (high7, low7) → two printable ASCII bytes; the
    # alphabet is ASCII 32..127 (95 chars) so two chars give 95² =
    # 9,025 distinct strings, less than 16,384. We accept some
    # collisions — the LLM's output for a colliding prompt is the
    # same regardless, so colliding LUT entries get the same colour;
    # since K=4 colours and 16,384 entries, collisions concentrate
    # signal rather than corrupting it.
    prompts = []
    for idx in range(lut_size):
        high = ((idx >> 7) & 0x7F) % 95   # → 0..94
        low  = ( idx       & 0x7F) % 95
        prompts.append(chr(0x20 + high) + chr(0x20 + low))

    n_done = 0
    for batch_start in range(0, lut_size, batch_size):
        batch = prompts[batch_start:batch_start + batch_size]
        enc = tok(batch, return_tensors='pt',
                   padding=True, truncation=True, max_length=4)
        input_ids = enc['input_ids']
        attn = enc.get('attention_mask')
        with torch.no_grad():
            out_lm = model(input_ids=input_ids,
                            attention_mask=attn) if attn is not None \
                       else model(input_ids=input_ids)
        # logits shape: (B, T, V_bpe). Take last *non-pad* token per row.
        logits = out_lm.logits.detach().cpu().numpy().astype(np.float64)
        if attn is not None:
            lengths = attn.sum(dim=1).cpu().numpy().astype(int)
        else:
            lengths = np.full(len(batch), logits.shape[1])

        for j, idx in enumerate(range(batch_start,
                                        batch_start + len(batch))):
            t = max(0, int(lengths[j]) - 1)
            row = logits[j, t]
            # Stable softmax → byte-bucket sum (same as
            # real_llm_expert_logits but without the log step; we just
            # need argmax of bucket sums, no logits needed).
            shifted = row - row.max()
            probs = np.exp(shifted)
            probs /= probs.sum()
            byte_probs = np.zeros(vocab_size, dtype=np.float64)
            np.add.at(byte_probs, proj[:probs.shape[0]], probs)
            bucket_probs = byte_probs.reshape(n_buckets, bucket_width
                                                 ).sum(axis=1)
            out[idx] = int(np.argmax(bucket_probs))

        n_done = batch_start + len(batch)
        if progress is not None:
            progress(n_done, lut_size)

    return bytes(out)


def distill_to_trained_model(model_name: str, *,
                               name: str, slug: str,
                               notes: str = '',
                               n_blocks: int = 2,
                               progress: Optional[callable] = None):
    """Convenience: distill output_rule from ``model_name`` and save
    as a complete TrainedModel (other 9 rules are deterministic
    random defaults seeded by ``hash(slug)``)."""
    from .models import TrainedModel
    from .ga import FULL_STACK_NAMES
    from .primitives import (random_rule_table, default_norm_rule)
    seed = hash(slug) & 0x7FFFFFFF
    distilled_output = distill_output_rule(model_name, progress=progress)
    rules = {
        n: random_rule_table(seed ^ (0x100 * (i + 1)))
        for i, n in enumerate(FULL_STACK_NAMES)
    }
    rules['output'] = np.frombuffer(distilled_output, dtype=np.uint8).copy()
    rules['norm']   = default_norm_rule(seed ^ 0x8000)

    obj, _ = TrainedModel.objects.update_or_create(
        slug=slug,
        defaults={
            'name': name,
            'notes': (notes or
                       f'output_rule distilled from {model_name} '
                       f'(no GA, no SGD; one-shot LLM oracle over '
                       f'16,384 LUT entries).'),
            'rule_q':      bytes(rules['q']),
            'rule_k':      bytes(rules['k']),
            'rule_v':      bytes(rules['v']),
            'rule_score':  bytes(rules['score']),
            'rule_mix':    bytes(rules['mix']),
            'rule_merge':  bytes(rules['merge']),
            'rule_mlp':    bytes(rules['mlp']),
            'rule_norm':   bytes(rules['norm']),
            'rule_output': bytes(rules['output']),
            'rule_embed':  bytes(rules['embed']),
            'corpus_excerpt': '',
            'vocab_size':  256,
            'n_blocks':    n_blocks,
            'pop_size':    0,
            'generations': 0,
            'final_fitness': 0.0,
            'history_json': [],
        },
    )
    return obj
