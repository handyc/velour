"""Phase 2b — 4-expert MoE with CA-driven routing.

Builds on `llm_lora`: derives 4 expert LoRA adapters from CA
components 0..3 and a per-token routing matrix from a 5th component.
At decode step t the applied delta is a softmax-weighted sum of the
4 expert deltas; both parties holding the same pact compute the
same weights and so produce byte-identical greedy completions.

Distinction from Phase 2a: the perturbation now varies per token,
not just per generation. The router consumes one new "decision" per
decoded position, so the model never sees the same weight twice in
a single completion — yet two parties' weights match at every step.

This is still single-target (one weight matrix); a multi-target
extension is straightforward but orthogonal to the routing idea.
"""

from __future__ import annotations
from typing import List, Sequence, Tuple

import numpy as np
import torch

from . import keystream
from .llm_lora import (
    default_target_weight,
    derive_lora,
    find_weight,
    keystream_gaussians,
    load_backbone,
)
from .models import Pact


def derive_expert_loras(pact: Pact,
                        components: Sequence[int],
                        shape: Tuple[int, int],
                        rank: int,
                        generation: int = 0,
                        ) -> List[Tuple[torch.Tensor, torch.Tensor]]:
    """One ``(A, B)`` tuple per expert component, all at the same
    pact generation."""
    return [derive_lora(pact, c, generation, shape, rank) for c in components]


def derive_router_weights(pact: Pact,
                          routing_component: int,
                          generation: int,
                          n_tokens: int,
                          n_experts: int,
                          domain: bytes = keystream.DOMAIN_ROUTER,
                          ) -> np.ndarray:
    """``(n_tokens, n_experts)`` softmax weights per token, drawn
    deterministically from the routing component's keystream.

    Uses the router domain by default so router bytes don't overlap
    with expert-LoRA bytes when the router component is also an
    expert (needed when all 64 components are experts)."""
    if n_tokens <= 0 or n_experts <= 0:
        return np.empty((0, n_experts), dtype=np.float64)
    z = keystream_gaussians(pact, routing_component, generation,
                            n_tokens * n_experts, domain=domain)
    logits = z.reshape(n_tokens, n_experts)
    # Standard softmax with max-subtraction for numerical stability.
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def _mixed_delta(experts: List[Tuple[torch.Tensor, torch.Tensor]],
                 weights_row: np.ndarray) -> torch.Tensor:
    """``sum_i w_i · (B_i @ A_i)`` for a single token's gate row."""
    out = None
    for (A, B), w in zip(experts, weights_row):
        d = B @ A
        out = d.mul(float(w)) if out is None else out.add_(d, alpha=float(w))
    return out


def generate_moe(pact: Pact, prompt: str, *,
                 expert_components: Sequence[int] = (0, 1, 2, 3),
                 routing_component: int = 4,
                 generation: int = 0,
                 model_name: str = 'distilgpt2',
                 rank: int = 4,
                 scale: float = 0.1,
                 max_new_tokens: int = 40,
                 target_weight: str | None = None,
                 device: str | None = None) -> str:
    """Greedy-decode ``prompt`` with per-token softmax-mixed expert
    LoRA deltas. Returns the decoded string (prompt + tail).
    """
    if target_weight is None:
        target_weight = default_target_weight(model_name)
    tok, model = load_backbone(model_name, device=device)

    weight = find_weight(model, target_weight)
    shape = (weight.shape[0], weight.shape[1])
    experts = derive_expert_loras(pact, expert_components, shape, rank, generation)
    router = derive_router_weights(pact, routing_component, generation,
                                   max_new_tokens, len(expert_components))

    input_ids = tok(prompt, return_tensors='pt').input_ids
    if device is not None:
        input_ids = input_ids.to(device)

    weight_orig = weight.detach().clone()

    with torch.no_grad():
        for t in range(max_new_tokens):
            weight.data.copy_(weight_orig)
            delta = _mixed_delta(experts, router[t]).to(weight.dtype).to(weight.device)
            weight.data.add_(delta, alpha=scale)
            out = model(input_ids=input_ids)
            next_id = out.logits[:, -1, :].argmax(dim=-1, keepdim=True)
            input_ids = torch.cat([input_ids, next_id], dim=1)
            if tok.eos_token_id is not None and next_id.item() == tok.eos_token_id:
                break

    # Leave the model's weight as we found it.
    weight.data.copy_(weight_orig)
    return tok.decode(input_ids[0], skip_special_tokens=True)
