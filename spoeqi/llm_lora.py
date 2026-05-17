"""Phase 2a — CA-keystream-driven LoRA perturbation.

Turns a Pact's deterministic SHA-256-chained byte stream into a
deterministic low-rank delta applied to one weight matrix of a
CausalLM, so two parties holding the same pact get bit-identical
generations from the same prompt.

Construction:
- Pull 4·n raw bytes from ``keystream.tap(pact, c, g, 4·n)``.
- Group as little-endian u32 → uniform floats in [0, 1).
- Box-Muller (sin/cos form) → standard-normal floats.
- Slice into A ∈ ℝ^(r, cols) and B ∈ ℝ^(rows, r); the LoRA delta is
  ΔW = scale · B @ A, shape (rows, cols) matching the target weight
  regardless of whether the layer is ``nn.Linear`` or HF's ``Conv1D``.
- Add the delta to the target weight in place; greedy-decode.

In-process determinism is verified by running the generation twice
and comparing. Cross-machine determinism additionally requires
identical hardware, library versions, and BLAS — that's a Phase 3
problem; this PoC proves the protocol shape.
"""

from __future__ import annotations
import math
from typing import Tuple

import numpy as np
import torch

from . import keystream
from .models import Pact


def keystream_uniforms(pact: Pact, component: int, generation: int,
                       n: int,
                       domain: bytes = keystream.DOMAIN_DEFAULT) -> np.ndarray:
    """`n` uniform floats in [0, 1) drawn from the pact's keystream.

    Consumes 4 bytes per float (one little-endian u32 each). The
    endianness is fixed so a JS-side reproduction can match by
    using ``DataView.getUint32(offset, true)``.
    """
    if n <= 0:
        return np.empty(0, dtype=np.float64)
    raw = keystream.tap(pact, component, generation, 4 * n, domain=domain)
    u32 = np.frombuffer(raw, dtype='<u4')
    return u32.astype(np.float64) / float(1 << 32)


def keystream_gaussians(pact: Pact, component: int, generation: int,
                        n: int,
                        domain: bytes = keystream.DOMAIN_DEFAULT) -> np.ndarray:
    """`n` floats from Box-Muller: pair (u1, u2) uniforms → pair
    (cos, sin) standard normals."""
    if n <= 0:
        return np.empty(0, dtype=np.float64)
    pairs = (n + 1) // 2
    u = keystream_uniforms(pact, component, generation, 2 * pairs, domain=domain)
    # u1 == 0 would blow up log(); the smallest non-zero u32 maps to
    # 2^-32 ≈ 2.3e-10, so the clip only matters if a u32 sample is 0.
    u1 = np.clip(u[0::2], 1e-300, None)
    u2 = u[1::2]
    r = np.sqrt(-2.0 * np.log(u1))
    theta = 2.0 * math.pi * u2
    z = np.empty(2 * pairs, dtype=np.float64)
    z[0::2] = r * np.cos(theta)
    z[1::2] = r * np.sin(theta)
    return z[:n]


def derive_lora(pact: Pact, component: int, generation: int,
                shape: Tuple[int, int],
                rank: int) -> Tuple[torch.Tensor, torch.Tensor]:
    """Derive (A, B) so that ΔW = B @ A has the target shape.

    Returns ``A`` of shape ``(rank, cols)`` and ``B`` of shape
    ``(rows, rank)`` as float32 tensors. All randomness comes from
    the pact's deterministic keystream.
    """
    rows, cols = shape
    n_total = rank * cols + rows * rank
    z = keystream_gaussians(pact, component, generation, n_total).astype(np.float32)
    A = torch.from_numpy(z[:rank * cols].reshape(rank, cols).copy())
    B = torch.from_numpy(z[rank * cols:].reshape(rows, rank).copy())
    return A, B


def apply_lora_inplace(weight: torch.Tensor, A: torch.Tensor,
                       B: torch.Tensor, scale: float) -> None:
    """``weight += scale * (B @ A)`` in place, no gradient tracking."""
    with torch.no_grad():
        delta = (B @ A).to(weight.dtype).to(weight.device)
        weight.data.add_(delta, alpha=scale)


# Last-block attention output projection for each model we know about.
# Picked because it's a plain 2D Linear/Conv1D weight that strongly
# affects token logits without being tied to the embedding (which
# would cascade into both input and output). Override with --target.
#
# `karpathy/minGPT-*` entries route through the vendored minGPT class
# (spoeqi.vendor.mingpt_model) instead of HF AutoModelForCausalLM —
# same GPT-2 weights, transparent hackable architecture.  Useful when
# you want to *see* what's being perturbed instead of trusting an HF
# black box.
DEFAULT_TARGETS = {
    'distilgpt2':                                      'transformer.h.5.attn.c_proj.weight',
    'gpt2':                                            'transformer.h.11.attn.c_proj.weight',
    'EleutherAI/pythia-70m':                           'gpt_neox.layers.5.attention.dense.weight',
    'EleutherAI/pythia-160m':                          'gpt_neox.layers.11.attention.dense.weight',
    'TinyLlama/TinyLlama-1.1B-Chat-v1.0':              'model.layers.21.self_attn.o_proj.weight',
    'TinyLlama/TinyLlama-1.1B-intermediate-step-1431k-3T':
                                                       'model.layers.21.self_attn.o_proj.weight',
    'karpathy/minGPT-gpt2':                            'transformer.h.11.attn.c_proj.weight',
    'karpathy/minGPT-gpt2-medium':                     'transformer.h.23.attn.c_proj.weight',
    'karpathy/minGPT-gpt2-large':                      'transformer.h.35.attn.c_proj.weight',
    'karpathy/minGPT-gpt2-xl':                         'transformer.h.47.attn.c_proj.weight',
}


MINGPT_PREFIX = 'karpathy/minGPT-'


def is_mingpt_name(model_name: str) -> bool:
    return model_name.startswith(MINGPT_PREFIX)


class _MinGPTOut:
    """Tiny stand-in for transformers' CausalLMOutput — only exposes
    the ``.logits`` attribute that spoeqi's MoE generator reads."""
    def __init__(self, logits):
        self.logits = logits


class _MinGPTHFAdapter(torch.nn.Module):
    """Wraps Karpathy's minGPT GPT to look like a HuggingFace
    AutoModelForCausalLM for the slice of API spoeqi uses:

        out = self(input_ids=tensor)        # → out.logits
        ids = self.generate(input_ids=...)  # → tensor of token ids

    The wrapped GPT is exposed at `self.transformer` so dotted target
    paths (e.g. `transformer.h.11.attn.c_proj.weight`) resolve through
    `find_weight` exactly like the HF case.
    """

    def __init__(self, gpt):
        super().__init__()
        self.gpt = gpt
        self.transformer = gpt.transformer

    def forward(self, input_ids=None, **_kw):
        logits, _loss = self.gpt(input_ids)
        return _MinGPTOut(logits)

    def generate(self, input_ids=None, max_new_tokens=40,
                 do_sample=False, temperature=1.0,
                 pad_token_id=None, **_kw):
        # minGPT.generate ignores pad_token_id — its loop is plain
        # autoregressive sampling, no padding semantics.
        return self.gpt.generate(
            input_ids, max_new_tokens,
            do_sample=do_sample, temperature=temperature,
        )


def load_backbone(model_name: str, *, device: str | None = None):
    """Load a (tokenizer, model) pair for ``model_name``.

    Routes ``karpathy/minGPT-*`` names through the vendored minGPT;
    everything else goes through transformers' AutoModelForCausalLM.
    The returned model exposes the same minimal surface in both cases
    so generate() / generate_moe() can stay backbone-agnostic.
    """
    from transformers import AutoTokenizer
    if is_mingpt_name(model_name):
        sub = model_name[len(MINGPT_PREFIX):]   # 'gpt2', 'gpt2-medium', ...
        from .vendor.mingpt_model import GPT
        # minGPT mirrors HF's GPT-2 BPE vocab exactly, so the gpt2
        # tokenizer is the right partner regardless of size.
        tok = AutoTokenizer.from_pretrained('gpt2')
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        gpt = GPT.from_pretrained(sub)
        model = _MinGPTHFAdapter(gpt)
    else:
        from transformers import AutoModelForCausalLM
        tok = AutoTokenizer.from_pretrained(model_name)
        if tok.pad_token_id is None:
            tok.pad_token = tok.eos_token
        model = AutoModelForCausalLM.from_pretrained(model_name)
    if device is not None:
        model = model.to(device)
    model.eval()
    return tok, model


def default_target_weight(model_name: str) -> str:
    """Best-guess `target_weight` for a model name. Exact match in
    DEFAULT_TARGETS, then a few prefix rules. Raises if it can't
    pick — the user should then pass `--target` explicitly."""
    if model_name in DEFAULT_TARGETS:
        return DEFAULT_TARGETS[model_name]
    if model_name.startswith('TinyLlama/'):
        return 'model.layers.21.self_attn.o_proj.weight'
    if model_name.startswith('EleutherAI/pythia-'):
        # Pythia layer counts: 70m→6, 160m→12, 410m→24, 1b→16, 1.4b→24.
        # No safe guess without loading the config; defer to the user.
        pass
    raise ValueError(
        f'no default target_weight known for {model_name!r}; '
        f'pass --target / target_weight= explicitly')


def list_known_models() -> list[str]:
    """Backbones registered for use in evolution chains.  Returned in
    a stable order so UI dropdowns / CLI --help renders are reproducible."""
    return list(DEFAULT_TARGETS.keys())


def find_weight(model: torch.nn.Module, dotted_name: str) -> torch.Tensor:
    """Resolve a dotted attribute path to a Tensor parameter."""
    obj = model
    for part in dotted_name.split('.'):
        obj = getattr(obj, part)
    if not isinstance(obj, torch.Tensor):
        raise TypeError(
            f'{dotted_name!r} resolved to {type(obj).__name__}, not a Tensor')
    return obj


def generate(pact: Pact, prompt: str, *,
             component: int = 0,
             generation: int = 0,
             model_name: str = 'distilgpt2',
             rank: int = 4,
             scale: float = 1e-3,
             max_new_tokens: int = 40,
             target_weight: str | None = None,
             device: str | None = None) -> str:
    """Load ``model_name``, perturb ``target_weight`` with a CA-derived
    LoRA, greedy-decode ``prompt``. Returns the decoded string.

    ``target_weight=None`` looks up a sensible per-model default via
    ``default_target_weight``; pass an explicit dotted path to override.
    """
    if target_weight is None:
        target_weight = default_target_weight(model_name)
    tok, model = load_backbone(model_name, device=device)
    weight = find_weight(model, target_weight)
    A, B = derive_lora(pact, component, generation,
                       (weight.shape[0], weight.shape[1]), rank)
    if scale != 0.0:
        apply_lora_inplace(weight, A, B, scale)
    inputs = tok(prompt, return_tensors='pt')
    if device is not None:
        inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=max_new_tokens,
            pad_token_id=tok.eos_token_id,
        )
    return tok.decode(out[0], skip_special_tokens=True)
