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
