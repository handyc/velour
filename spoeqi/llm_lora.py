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
                       n: int) -> np.ndarray:
    """`n` uniform floats in [0, 1) drawn from the pact's keystream.

    Consumes 4 bytes per float (one little-endian u32 each). The
    endianness is fixed so a JS-side reproduction can match by
    using ``DataView.getUint32(offset, true)``.
    """
    if n <= 0:
        return np.empty(0, dtype=np.float64)
    raw = keystream.tap(pact, component, generation, 4 * n)
    u32 = np.frombuffer(raw, dtype='<u4')
    return u32.astype(np.float64) / float(1 << 32)


def keystream_gaussians(pact: Pact, component: int, generation: int,
                        n: int) -> np.ndarray:
    """`n` floats from Box-Muller: pair (u1, u2) uniforms → pair
    (cos, sin) standard normals."""
    if n <= 0:
        return np.empty(0, dtype=np.float64)
    pairs = (n + 1) // 2
    u = keystream_uniforms(pact, component, generation, 2 * pairs)
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
             target_weight: str = 'transformer.h.5.attn.c_proj.weight',
             device: str | None = None) -> str:
    """Load ``model_name``, perturb ``target_weight`` with a CA-derived
    LoRA, greedy-decode ``prompt``. Returns the decoded string.

    ``target_weight`` defaults to distilgpt2's last-block attention
    output projection. Override for other architectures (e.g.
    ``'lm_head.weight'`` or a specific MLP).
    """
    from transformers import AutoTokenizer, AutoModelForCausalLM
    tok = AutoTokenizer.from_pretrained(model_name)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name)
    if device is not None:
        model = model.to(device)
    model.eval()
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
