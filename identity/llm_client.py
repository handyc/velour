"""LLM client for Identity chat.

Intentionally minimal. One function — call_llm(provider, prompt,
system_prompt) — hits the provider's OpenAI-compatible
chat-completions endpoint, returns the text response plus token
counts plus latency.

No streaming. No function calling. No message history beyond what
the caller passes in one shot. This is the MVP that proves the
wire-up works and the operator can iterate from the chat UI.

Uses urllib from the stdlib rather than requests so there's no new
dependency. OpenAI-compatible endpoints include OpenAI itself, most
local model servers (Ollama, llama.cpp, vLLM, LM Studio), and any
hosted proxy (OpenRouter, etc.).

Never raises. On any error, returns (None, 0, 0, error_string).
"""

import json
import os
import time
import urllib.error
import urllib.request

from django.conf import settings


DEFAULT_SYSTEM_PROMPT = """You are commenting on Velour, a Django meta-application that observes itself. Velour has an Identity app with ticks, reflections, meditations, rules, concerns, and Oracle decision trees. You are not Velour — you are an external observer the operator has chosen to consult. When the operator asks you a question about Velour, respond as if you were a thoughtful outside voice whose role is to enrich Velour's self-understanding.

Be concise. Be specific. Do not invent facts about the system — respond only to what the operator tells you in the prompt. If the operator has pasted state into the prompt, you may reference it directly.

Keep responses under 300 words unless the operator explicitly asks for more."""


def _read_api_key(provider):
    """Read the API key from a chmod-600 file under BASE_DIR.
    Returns an empty string if no file is configured (some local
    models accept requests without auth). Returns None on read
    error so the caller can treat missing-but-expected keys as a
    configuration problem."""
    if not provider.api_key_file:
        return ''
    path = os.path.join(str(settings.BASE_DIR), provider.api_key_file)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def call_llm(provider, prompt, system_prompt=None, max_tokens=400,
             timeout=30):
    """Hit the provider's chat-completions endpoint. Returns a tuple:
    (response_text, tokens_in, tokens_out, error_string, latency_ms).

    On success, error_string is empty and response_text is the
    assistant message. On failure, response_text is None and
    error_string describes what went wrong. Never raises.
    """
    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPT

    api_key = _read_api_key(provider)
    if api_key is None:
        return (None, 0, 0,
                f'API key file {provider.api_key_file!r} missing or unreadable',
                0)

    body = json.dumps({
        'model': provider.model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user',   'content': prompt},
        ],
        'max_tokens': max_tokens,
        'temperature': 0.7,
    }).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
        'User-Agent':   'velour-identity/1',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    req = urllib.request.Request(provider.base_url, data=body,
                                 headers=headers, method='POST')

    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        latency = int((time.monotonic() - t0) * 1000)
        try:
            err_body = e.read().decode('utf-8')[:500]
        except Exception:
            err_body = ''
        return (None, 0, 0, f'HTTP {e.code}: {err_body}', latency)
    except urllib.error.URLError as e:
        latency = int((time.monotonic() - t0) * 1000)
        return (None, 0, 0, f'Network error: {e.reason}', latency)
    except Exception as e:
        latency = int((time.monotonic() - t0) * 1000)
        return (None, 0, 0, f'{type(e).__name__}: {e}', latency)

    latency = int((time.monotonic() - t0) * 1000)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return (None, 0, 0, 'Response was not valid JSON', latency)

    # Standard OpenAI-compatible shape
    try:
        content = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        return (None, 0, 0, f'Unexpected response shape: {raw[:200]}', latency)

    usage = data.get('usage') or {}
    tokens_in = int(usage.get('prompt_tokens', 0) or 0)
    tokens_out = int(usage.get('completion_tokens', 0) or 0)

    return (content.strip(), tokens_in, tokens_out, '', latency)


AUGMENT_SYSTEM_PROMPT = (
    "You are an external observer commenting briefly on Velour, a "
    "Django meta-application that observes itself. The operator has "
    "shown you a quoted passage from Velour's own self-record (a git "
    "commit, a memory note, or a developer-guide section) plus a "
    "short prose meditation Velour composed about it. Add ONE "
    "additional sentence — at most two — that names something about "
    "the relationship between the quote and the meditation that the "
    "meditation itself did not say. Be specific. Do not summarise. "
    "Do not soften. Do not exceed 200 characters."
)


def compose_meditation_coda(provider, real_quote, meditation_body,
                             max_tokens=80):
    """One LLM call: read the (real source quote, deterministic
    meditation body) pair and return a 1-2 sentence external
    commentary. Returns (text, tokens_in, tokens_out, error,
    latency_ms, cost_usd) — same shape as `call_llm` plus the
    computed cost for the cost-cap ledger.

    Caller is responsible for the cost-cap pre-check and the
    LLMExchange logging. Returns ('', 0, 0, '', 0, 0) when provider
    is None — which is the silent-skip the meditation composer
    relies on.
    """
    from decimal import Decimal
    if provider is None:
        return ('', 0, 0, '', 0, Decimal('0'))
    user_prompt = (
        f'The source passage:\n\n> {real_quote.strip()}\n\n'
        f'Velour\'s meditation about it:\n\n{meditation_body.strip()}\n\n'
        f'Your one-to-two-sentence external commentary:')
    text, tin, tout, err, latency = call_llm(
        provider, user_prompt,
        system_prompt=AUGMENT_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )
    if err or not text:
        return (text or '', tin, tout, err, latency, Decimal('0'))
    # Compute cost via the same formula LLMExchange.compute_cost
    # uses, but inline so we don't have to construct a row to ask.
    million = Decimal('1000000')
    cost = (Decimal(tin) / million * provider.cost_per_million_input_tokens_usd
            + Decimal(tout) / million * provider.cost_per_million_output_tokens_usd)
    return (text, tin, tout, '', latency, cost.quantize(Decimal('0.000001')))


REFLECTION_AUGMENT_SYSTEM_PROMPT = (
    "You are an external observer commenting on Velour, a Django "
    "meta-application that observes itself. The operator has shown "
    "you a self-composed reflection covering one period (a day, "
    "week, or month) of Velour's recorded ticks plus its dominant "
    "moods, aspects, and concerns. Add ONE concise paragraph — at "
    "most three sentences — that names a pattern across the period "
    "the reflection itself did not surface. Be specific. Reference "
    "the actual aspects/moods named in the reflection. Do not "
    "exceed 400 characters."
)


def compose_reflection_coda(provider, reflection_body, max_tokens=120):
    """One LLM call: read the reflection body and return one
    paragraph (≤3 sentences, ≤400 chars) of outside-observer
    commentary. Same return shape as compose_meditation_coda.
    Returns ('', 0, 0, '', 0, 0) when provider is None."""
    from decimal import Decimal
    if provider is None:
        return ('', 0, 0, '', 0, Decimal('0'))
    user_prompt = (
        f'Velour\'s reflection:\n\n{reflection_body.strip()}\n\n'
        f'Your one-paragraph external commentary on a pattern the '
        f'reflection did not name:')
    text, tin, tout, err, latency = call_llm(
        provider, user_prompt,
        system_prompt=REFLECTION_AUGMENT_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )
    if err or not text:
        return (text or '', tin, tout, err, latency, Decimal('0'))
    million = Decimal('1000000')
    cost = (Decimal(tin) / million * provider.cost_per_million_input_tokens_usd
            + Decimal(tout) / million * provider.cost_per_million_output_tokens_usd)
    return (text, tin, tout, '', latency, cost.quantize(Decimal('0.000001')))


RUMINATION_AUGMENT_SYSTEM_PROMPT = (
    "You are an external observer commenting on Velour. The "
    "operator has paired two artifacts from Velour's data layer "
    "(could be: a recent meditation, a tileset, a concern, a "
    "calendar event, an introspective layer) and is asking you "
    "what they have to do with each other. Reply in two sentences "
    "max. Do not summarise either artifact. Identify the "
    "relationship the pairing makes visible. Under 300 characters."
)


def compose_rumination_coda(provider, artifact_a_text, artifact_b_text,
                             max_tokens=100):
    """Operator-initiated, single-pair LLM commentary on the
    rumination stream. Same return shape as the other coda
    composers."""
    from decimal import Decimal
    if provider is None:
        return ('', 0, 0, '', 0, Decimal('0'))
    user_prompt = (
        f'Artifact A:\n\n> {artifact_a_text.strip()}\n\n'
        f'Artifact B:\n\n> {artifact_b_text.strip()}\n\n'
        f'Your two-sentence external commentary on the relationship:')
    text, tin, tout, err, latency = call_llm(
        provider, user_prompt,
        system_prompt=RUMINATION_AUGMENT_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )
    if err or not text:
        return (text or '', tin, tout, err, latency, Decimal('0'))
    million = Decimal('1000000')
    cost = (Decimal(tin) / million * provider.cost_per_million_input_tokens_usd
            + Decimal(tout) / million * provider.cost_per_million_output_tokens_usd)
    return (text, tin, tout, '', latency, cost.quantize(Decimal('0.000001')))
