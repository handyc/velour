"""External LLM fallback for the meta route's last-resort handoff.

This is the ONLY place the chat stack reaches outside the pure-CA
substrate.  Two paths, tried in this order:

  1. **Anthropic Claude API** — if ANTHROPIC_API_KEY is set in the
     environment.  Direct call to api.anthropic.com.

  2. **Free OpenAI-compatible proxy via alistaitsacle/free-llm-api-keys**
     — same mechanism officeagent uses: fetch the constantly-refreshed
     README of community-shared API keys, sample one from the OpenAI
     section, send the chat through the pekpik proxy.  No api key
     required on the operator's side.  Quality varies — these are
     free-tier tokens — but it's enough to verify the meta-route
     fallback path end-to-end.

Whichever path fires, the UI displays an explicit warning that pure-CA
mode has ended.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.request
import urllib.error


# ─── Direct Anthropic path ──────────────────────────────────────────

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_MODEL   = 'claude-opus-4-7'
ANTHROPIC_TIMEOUT = 30.0


class FallbackError(RuntimeError):
    """Raised when *no* external path succeeds.  Carries a short
    message suitable for showing in the chat UI."""


def _anthropic_call(prompt: str, *, max_tokens: int = 512) -> str:
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        raise FallbackError('ANTHROPIC_API_KEY not set')
    model = os.environ.get('ANTHROPIC_MODEL') or ANTHROPIC_MODEL
    body = json.dumps({
        'model':      model,
        'max_tokens': int(max_tokens),
        'messages':   [{'role': 'user', 'content': prompt}],
    }).encode('utf-8')
    req = urllib.request.Request(
        ANTHROPIC_API_URL, data=body,
        headers={
            'content-type':      'application/json',
            'x-api-key':         api_key,
            'anthropic-version': '2023-06-01',
        })
    try:
        with urllib.request.urlopen(req, timeout=ANTHROPIC_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise FallbackError(
            f'Anthropic HTTP {e.code}: '
            f'{e.read().decode("utf-8", "replace")[:200]}')
    except urllib.error.URLError as e:
        raise FallbackError(f'Anthropic network error: {e.reason}')
    content = data.get('content') or []
    parts = [c.get('text', '') for c in content if c.get('type') == 'text']
    if not parts:
        raise FallbackError(f'Anthropic: unexpected response shape')
    return '\n'.join(parts).strip()


# ─── Free-key proxy path (officeagent's mechanism) ──────────────────

FREE_KEYS_URL = ('https://raw.githubusercontent.com/'
                  'alistaitsacle/free-llm-api-keys/main/README.md')
PEKPIK_PROXY  = 'https://aiapiv2.pekpik.com/v1/chat/completions'
PROXY_MODEL_DEFAULT = 'gpt-4o-mini'
PROXY_TIMEOUT       = 30.0

_KEYS_CACHE: dict = {'fetched_at': 0.0, 'readme': ''}
_KEYS_TTL_S = 600.0


def _fetch_readme() -> str:
    now = time.time()
    if (now - _KEYS_CACHE['fetched_at']) < _KEYS_TTL_S and _KEYS_CACHE['readme']:
        return _KEYS_CACHE['readme']
    req = urllib.request.Request(
        FREE_KEYS_URL,
        headers={'user-agent': 'caformer-fallback/1.0'})
    with urllib.request.urlopen(req, timeout=10.0) as resp:
        text = resp.read().decode('utf-8', errors='replace')
    _KEYS_CACHE['fetched_at'] = now
    _KEYS_CACHE['readme']     = text
    return text


# A `### Provider` header line we want to match for the OpenAI section.
_OPENAI_TAGS = ('OpenAI', 'GPT', 'ChatGPT', 'OAI')
# Keys inside table cells: backtick-wrapped tokens length≥20, [A-Za-z0-9_.-].
_KEY_RE = re.compile(r'`([A-Za-z0-9_.\-]{20,})`')


def _parse_section_keys(readme: str, tags: tuple[str, ...]) -> list[tuple[str, str]]:
    """Walk the README; return list of (key, model_hint) for cells
    inside ### sections matching any of `tags`.  model_hint may be
    empty when the table column wasn't readable."""
    out: list[tuple[str, str]] = []
    in_section = False
    for line in readme.splitlines():
        stripped = line.lstrip()
        if stripped.startswith('### '):
            header = stripped[4:]
            in_section = any(tag in header for tag in tags)
            continue
        if not in_section:
            continue
        # markdown table rows look like: | `key` | model | status | …
        keys = _KEY_RE.findall(line)
        if not keys:
            continue
        # Best-effort: pull a model hint from the second pipe-delimited cell.
        model_hint = ''
        cells = [c.strip() for c in line.split('|')]
        if len(cells) >= 3:
            second = cells[2]
            # strip backticks around model name if any
            second = second.strip('`').strip()
            if second and len(second) < 80:
                model_hint = second
        for k in keys:
            out.append((k, model_hint))
    return out


def _openai_proxy_call(prompt: str, *, max_tokens: int = 512) -> str:
    """Fetch a free OpenAI-compatible key, call pekpik proxy."""
    try:
        readme = _fetch_readme()
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        raise FallbackError(f'free-keys fetch failed: {e}')

    candidates = _parse_section_keys(readme, _OPENAI_TAGS)
    if not candidates:
        raise FallbackError('no OpenAI-section keys in free-keys README')

    random.shuffle(candidates)
    last_err = 'no candidates tried'
    for key, hint in candidates[:5]:   # try up to 5 keys before giving up
        model = hint or PROXY_MODEL_DEFAULT
        body = json.dumps({
            'model':       model,
            'messages':    [{'role': 'user', 'content': prompt}],
            'max_tokens':  int(max_tokens),
        }).encode('utf-8')
        req = urllib.request.Request(
            PEKPIK_PROXY, data=body,
            headers={
                'content-type':  'application/json',
                'authorization': f'Bearer {key}',
                'user-agent':    'caformer-fallback/1.0',
            })
        try:
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            choices = data.get('choices') or []
            if choices and 'message' in choices[0]:
                msg = choices[0]['message'].get('content', '')
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
            last_err = f'unexpected shape from {model}'
        except urllib.error.HTTPError as e:
            last_err = f'HTTP {e.code} ({model})'
            continue
        except urllib.error.URLError as e:
            last_err = f'network: {e.reason}'
            continue
    raise FallbackError(f'pekpik proxy exhausted ({last_err})')


# ─── Public entry point ─────────────────────────────────────────────

def ask(prompt: str, *, prefer: str = 'auto', max_tokens: int = 512) -> dict:
    """Returns {'text': str, 'provider': str, 'model': str} or raises
    FallbackError if no path succeeds.

    `prefer`:
       'anthropic'  — only try the Anthropic key path
       'free'       — only try the free-key proxy path
       'auto'       — Anthropic first (if key set), fall back to free
    """
    errors = []
    if prefer in ('auto', 'anthropic') and os.environ.get('ANTHROPIC_API_KEY'):
        try:
            return {'text': _anthropic_call(prompt, max_tokens=max_tokens),
                      'provider': 'anthropic',
                      'model': os.environ.get('ANTHROPIC_MODEL') or ANTHROPIC_MODEL}
        except FallbackError as e:
            errors.append(f'anthropic: {e}')
    if prefer in ('auto', 'free'):
        try:
            text = _openai_proxy_call(prompt, max_tokens=max_tokens)
            return {'text': text,
                      'provider': 'pekpik-proxy',
                      'model': '(varies, see free-llm-api-keys README)'}
        except FallbackError as e:
            errors.append(f'free-key: {e}')
    raise FallbackError('; '.join(errors) or 'no path attempted')


# Back-compat shim — the previous code called ask_anthropic() directly.
def ask_anthropic(prompt: str) -> str:
    return ask(prompt)['text']
