"""nanogpt_reference.py — definitive checklist of one transformer forward pass.

Source: nanoGPT / GPT-2 architecture as documented in Karpathy's
nanoGPT (github.com/karpathy/nanoGPT) and the original GPT-2 paper.
Used by caformer to align each CA-based primitive against the *exact*
operation it's replacing.

Notation:
    B  = batch size               (typically 1 for inference)
    T  = sequence length / tokens (≤ block_size)
    V  = vocab size               (50257 for GPT-2)
    C  = n_embd / d_model         (768 for nanoGPT-small / GPT-2 small)
    H  = n_head                   (12 for nanoGPT-small)
    A  = head_dim = C / H         (64 for nanoGPT-small)
    L  = n_layer                  (3 for nanoGPT, 12 for GPT-2 small)

A "transformer block" wraps everything inside the L loop — there are L
copies of the block, each with its own weights.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Step:
    """One named operation in the forward pass."""
    n:          int     # serial number in the pipeline
    op:         str     # short name
    formula:    str     # mathematical operation
    in_shape:   str     # input tensor shape
    out_shape:  str     # output tensor shape
    notes:      str = ''


# ─── Embedding ────────────────────────────────────────────────────
EMBED_STEPS: List[Step] = [
    Step(1, 'token_embed',
         'x = wte[input_ids]',
         '(B, T)', '(B, T, C)',
         'wte: (V, C); learned token-embedding table'),
    Step(2, 'pos_embed',
         'p = wpe[position_ids]',
         '(B, T)', '(B, T, C)',
         'wpe: (block_size, C); learned positional table'),
    Step(3, 'embed_sum',
         'h = x + p',
         '(B, T, C)', '(B, T, C)',
         'positional info gets added — not concatenated'),
]


# ─── Per-block (repeated L times) ─────────────────────────────────
# nanoGPT uses *pre-norm* (LN before each sublayer), as in GPT-2.
# Schema per block, with `h` flowing through:
BLOCK_STEPS: List[Step] = [
    Step(4, 'ln_1',
         'h_n = LayerNorm_1(h)',
         '(B, T, C)', '(B, T, C)',
         'pre-norm: γ⊙(h-μ)/σ+β; γ,β ∈ (C,)'),
    # Attention sub-block ────────────
    Step(5, 'qkv_proj',
         '[Q, K, V] = h_n · W_qkv  (one fused linear)',
         '(B, T, C)', '(B, T, 3C)',
         'W_qkv: (C, 3C) — fused for efficiency'),
    Step(6, 'split_heads',
         'reshape Q, K, V → (B, H, T, A); A = C/H',
         '(B, T, 3C)', '3 × (B, H, T, A)',
         'each head sees a C/H slice; transpose so head dim is outer'),
    Step(7, 'scaled_dot_product',
         'attn = Q · Kᵀ / √A',
         '(B, H, T, A)', '(B, H, T, T)',
         'scale by √head_dim to keep softmax temperature steady'),
    Step(8, 'causal_mask',
         'attn[i, j] = -∞  if j > i',
         '(B, H, T, T)', '(B, H, T, T)',
         'lower-triangular mask — token i can only see ≤ i'),
    Step(9, 'softmax_attn',
         'attn = softmax(attn, dim=-1)',
         '(B, H, T, T)', '(B, H, T, T)',
         'rowwise softmax across the source-token axis'),
    Step(10, 'attend_values',
         'y = attn · V',
         '(B, H, T, T) + (B, H, T, A)', '(B, H, T, A)',
         'weighted sum of V rows per query'),
    Step(11, 'merge_heads',
         'y = y.transpose(1,2).contiguous().view(B,T,C)',
         '(B, H, T, A)', '(B, T, C)',
         'concat heads back to a single channel dim'),
    Step(12, 'out_proj',
         'y = y · W_o',
         '(B, T, C)', '(B, T, C)',
         'W_o: (C, C); the "output projection" of attention'),
    Step(13, 'residual_attn',
         'h = h + y',
         '(B, T, C)', '(B, T, C)',
         'first residual: pre-LN block input + attn output'),
    # MLP sub-block ────────────
    Step(14, 'ln_2',
         'h_n = LayerNorm_2(h)',
         '(B, T, C)', '(B, T, C)',
         'second pre-norm, before the MLP'),
    Step(15, 'mlp_up',
         'a = h_n · W_1 + b_1',
         '(B, T, C)', '(B, T, 4C)',
         'W_1: (C, 4C); the "up-projection" — 4× expansion'),
    Step(16, 'mlp_act',
         'a = GELU(a)',
         '(B, T, 4C)', '(B, T, 4C)',
         'gaussian-error linear unit; smoother than ReLU'),
    Step(17, 'mlp_down',
         'm = a · W_2 + b_2',
         '(B, T, 4C)', '(B, T, C)',
         'W_2: (4C, C); the "down-projection" back to C'),
    Step(18, 'residual_mlp',
         'h = h + m',
         '(B, T, C)', '(B, T, C)',
         'second residual: post-attn h + mlp output'),
]


# ─── After all L blocks ───────────────────────────────────────────
HEAD_STEPS: List[Step] = [
    Step(19, 'ln_f',
         'h = LayerNorm_f(h)',
         '(B, T, C)', '(B, T, C)',
         'final layer-norm, only once after the last block'),
    Step(20, 'lm_head',
         'logits = h · wteᵀ   (weight-tied with embedding)',
         '(B, T, C)', '(B, T, V)',
         'tied embeddings: same matrix as wte, transposed'),
    # Sampling (only the last position is used at inference time)
    Step(21, 'last_logit',
         'l = logits[:, -1, :]',
         '(B, T, V)', '(B, V)',
         'autoregressive: only the next token matters'),
    Step(22, 'temperature',
         'l = l / temperature',
         '(B, V)', '(B, V)',
         'higher T = flatter distribution; sharpens as T→0'),
    Step(23, 'softmax_logits',
         'p = softmax(l, dim=-1)',
         '(B, V)', '(B, V)',
         'final probability distribution'),
    Step(24, 'sample',
         'next_token = multinomial(p) or argmax(p)',
         '(B, V)', '(B, 1)',
         'argmax = greedy / temperature 0; multinomial = sampling'),
]


# ─── Model-size catalogue ─────────────────────────────────────────
@dataclass(frozen=True)
class ModelSize:
    name:       str
    n_layer:    int      # number of transformer blocks
    n_head:     int
    n_embd:     int
    block_size: int      # max sequence length
    vocab:      int
    params:     str      # rough param count
    notes:      str = ''


MODEL_SIZES: List[ModelSize] = [
    ModelSize('nanoGPT (smallest viable)',  3,  3,   48, 256, 50257,
               '~0.5M', 'Karpathy gpt-nano size; useful as a smoke target'),
    ModelSize('GPT-2 small',                12, 12,  768, 1024, 50257,
               '~124M', 'baseline transformer everyone clones'),
    ModelSize('GPT-2 medium',               24, 16, 1024, 1024, 50257,
               '~350M'),
    ModelSize('GPT-2 large',                36, 20, 1280, 1024, 50257,
               '~774M'),
    ModelSize('GPT-2 XL',                   48, 25, 1600, 1024, 50257,
               '~1.5B', 'last GPT-2 size; ~6 GB fp16 weights'),
    ModelSize('GPT-3 (full)',               96, 96, 12288, 2048, 50257,
               '~175B', 'OpenAI scale; we will not reach this in CAs'),
    ModelSize('GPT-3.5 / GPT-4 family',    None, None, None, None, None,
               '~unknown',
               'closed weights; instruction-tuned; mixture-of-experts in some variants'),
]
