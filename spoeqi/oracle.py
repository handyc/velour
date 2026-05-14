"""Pact-derived prompt → external non-deterministic LLM.

The pact is a private randomness beacon. The deterministic
LoRA-perturbed CausalLM (Phase 2a) projects pact state into
coherent natural-language prompts that both parties compute
identically. Those prompts are then submitted to an external
non-deterministic LLM (GPT-4, Claude, a local Llama) over an
OpenAI-compatible HTTP endpoint; each party gets their own
private response.

The seal is preserved because the external response never flows
back into CA state. Both parties can ask, both can compare answers
later (via the envelope), and neither could have rigged the
question — because the question emerged from a process neither
controlled without breaking the pact's lockstep.
"""

from __future__ import annotations
from typing import Optional

from .llm_lora import generate as deterministic_generate
from .models import Pact


DEFAULT_SEED_PROMPT = (
    "Compose a single short, thoughtful question about meaning, "
    "consciousness, or change — the kind of question a person might "
    "pose to a thoughtful stranger. Just the question:"
)

DEFAULT_EXTERNAL_SYSTEM_PROMPT = (
    "Respond to the question below in under 200 words. Be direct, "
    "concrete, and personal. You may answer, reframe, or refuse — "
    "but commit to a stance."
)


def make_prompt(pact: Pact, *,
                seed_prompt: str = DEFAULT_SEED_PROMPT,
                component: int = 0,
                generation: int = 0,
                model_name: str = 'distilgpt2',
                scale: float = 0.1,
                rank: int = 4,
                max_new_tokens: int = 60,
                target_weight: Optional[str] = None) -> str:
    """Run the Phase 2a LoRA-perturbed greedy decode and return the
    full string (seed + deterministic completion). Both parties
    holding the same pact compute the same return value."""
    return deterministic_generate(
        pact=pact,
        prompt=seed_prompt,
        component=component,
        generation=generation,
        model_name=model_name,
        scale=scale,
        rank=rank,
        max_new_tokens=max_new_tokens,
        target_weight=target_weight,
    )


def ask_oracle(pact: Pact, *,
               provider_name: Optional[str] = None,
               external_system_prompt: Optional[str] = None,
               max_external_tokens: int = 400,
               **make_prompt_kwargs) -> dict:
    """Generate a pact-shared prompt and submit it to the named
    LLMProvider. Returns a dict with ``prompt``, ``response``,
    ``provider``, ``error``, and timing/token metadata.

    When ``provider_name`` is None the external call is skipped
    (echo mode) — useful to inspect what both parties would be
    asking before plumbing in credentials.
    """
    prompt = make_prompt(pact, **make_prompt_kwargs)

    result = {
        'prompt': prompt,
        'response': None,
        'provider': provider_name,
        'model': None,
        'tokens_in': 0,
        'tokens_out': 0,
        'error': None,
        'latency_ms': 0,
    }

    if provider_name is None:
        result['error'] = 'echo mode — no provider was queried'
        return result

    from identity.models import LLMProvider
    try:
        provider = LLMProvider.objects.get(name=provider_name)
    except LLMProvider.DoesNotExist:
        result['error'] = (
            f'no LLMProvider named {provider_name!r}; '
            f'add one via the identity admin or pick --provider echo')
        return result

    from identity.llm_client import call_llm
    sys_prompt = external_system_prompt or DEFAULT_EXTERNAL_SYSTEM_PROMPT
    text, tin, tout, err, latency = call_llm(
        provider, prompt,
        system_prompt=sys_prompt,
        max_tokens=max_external_tokens,
    )
    result.update({
        'response': text,
        'model': provider.model,
        'tokens_in': tin,
        'tokens_out': tout,
        'error': err or None,
        'latency_ms': latency,
    })
    return result
