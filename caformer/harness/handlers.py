"""Named live-data handlers for the caformer harness.

Each handler is a small Python function that returns a string —
the value the harness should substitute when a template names this
handler (via TemplatePattern.handler_name or a ``[handler:name]``
marker in the template output).

**Security model.**  Handlers are *registered Python code* in this
file's HANDLERS dict.  Templates can only invoke handlers by name
from this registry — never arbitrary callables or eval'd strings.
The DB stores only the handler's name, not Python code.

Adding a new handler:
  1. Define a callable in this module taking ``(slots: dict[str, str])
     -> str``.  ``slots`` carries the template's matched [X]
     captures so handlers can use the user's input.  Most handlers
     ignore slots.
  2. Register it in HANDLERS.  The name becomes the wiring key.

Handlers should soft-fail (return a short explanation string) when
the underlying data source is unavailable, so a misconfigured
Velour install doesn't 500 the chat.
"""
from __future__ import annotations

import datetime as _dt
import subprocess
from typing import Callable


# ─── Handlers ──────────────────────────────────────────────────────


def _h_mood(slots: dict[str, str]) -> str:
    """Current Velour identity mood from the Tick stream (new) or
    Mood log (legacy fallback)."""
    try:
        from identity.models import Tick
        t = Tick.objects.order_by('-at').first()
        if t is not None and t.mood:
            return f'{t.mood} ({t.mood_intensity:.2f})'
    except Exception:                                # noqa: BLE001
        pass
    try:
        from identity.models import Mood
        m = Mood.objects.order_by('-timestamp').first()
        if m is not None:
            return f'{m.mood} ({m.intensity:.2f})'
    except Exception:                                # noqa: BLE001
        pass
    return '(mood unavailable)'


def _h_now(slots: dict[str, str]) -> str:
    """Server local time, HH:MM."""
    return _dt.datetime.now().strftime('%H:%M')


def _h_today(slots: dict[str, str]) -> str:
    """Server local date, YYYY-MM-DD."""
    return _dt.date.today().isoformat()


def _h_qrpair_count(slots: dict[str, str]) -> str:
    """How many QRPairs are trained, and how many are byte-exact."""
    try:
        from caformer.models import QRPair
        from django.db.models import Q
        total = QRPair.objects.count()
        exact = QRPair.objects.filter(
            Q(best_exact=True) | Q(board128_exact=True)
            | Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True)
            | Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True)
            | Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True)
        ).count()
        return f'{exact} byte-exact / {total} total'
    except Exception:                                # noqa: BLE001
        return '(QRPair count unavailable)'


def _h_git_branch(slots: dict[str, str]) -> str:
    """Current git branch of the Velour checkout."""
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=2.0, check=False)
        if r.returncode == 0:
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return '(branch unknown)'


def _h_harness_profiles(slots: dict[str, str]) -> str:
    """List of HarnessProfile slugs in the DB."""
    try:
        from caformer.models import HarnessProfile
        slugs = list(HarnessProfile.objects.values_list('slug', flat=True))
        if not slugs:
            return '(no HarnessProfile rows)'
        return ', '.join(slugs)
    except Exception:                                # noqa: BLE001
        return '(HarnessProfile lookup failed)'


def _h_recent_chat(slots: dict[str, str]) -> str:
    """One-line summary of the most recent caformer chat turn."""
    try:
        from caformer.models import ChatTurn
        last = ChatTurn.objects.order_by('-created_at').first()
        if last is None:
            return '(no recent chats)'
        snippet = (last.prompt or '')[:60]
        return f'last chat: {snippet!r} ({last.created_at:%H:%M})'
    except Exception:                                # noqa: BLE001
        return '(chat history unavailable)'


def _h_latest_dream(slots: dict[str, str]) -> str:
    """The most recent DMN dream string from the caformer dream pool."""
    try:
        from caformer.models import ChatTurn
        last = ChatTurn.objects.filter(
            prompt__icontains='DMN').order_by('-created_at').first()
        if last is None:
            return '(no dreams yet)'
        return last.reply[:120] if last.reply else '(empty dream)'
    except Exception:                                # noqa: BLE001
        return '(dream lookup failed)'


def _h_cond_act(slots: dict[str, str]) -> str:
    """Conditional execution.  Used by templates of the shape:

        pattern = 'if [cond] then [act]'
        output  = (anything; replaced by this handler)
        handler_name = 'cond_act'

    cond is parsed for one of: '<source> is <value>',
    '<source> is not <value>', '<source> = <value>', '<source>
    equals <value>'.  <source> must be the NAME of another
    registered handler.  We invoke that handler and check whether
    <value> appears (case-insensitive substring) in its result.

    On true → return ``act`` text.  On false → a short trace
    string showing actual vs expected.  On parse failure → an
    explicit error so authoring mistakes surface."""
    cond = (slots.get('cond') or '').strip().lower()
    act  = (slots.get('act')  or '').strip()
    if not cond or not act:
        return '(if-then template missing cond or act slot)'

    is_not = False
    separator: str | None = None
    for sep in (' is not ', ' is ', ' equals ', ' = '):
        if sep in cond:
            separator = sep
            is_not = (sep == ' is not ')
            break
    if separator is None:
        return f'(could not parse condition: {cond!r})'
    left, _, right = cond.partition(separator)
    left = left.strip()
    right = right.strip().strip('"').strip("'").lower()
    # Friendly aliases for handler names so users can say 'branch'
    # instead of 'git_branch' or 'time' instead of 'now'.
    HANDLER_ALIASES = {
        'branch':   'git_branch',
        'time':     'now',
        'date':     'today',
        'profiles': 'harness_profiles',
        'corpus':   'qrpair_count',
        'pairs':    'qrpair_count',
        'chat':     'recent_chat',
        'dream':    'latest_dream',
        'feeling':  'mood',
    }
    if left in HANDLER_ALIASES:
        left = HANDLER_ALIASES[left]
    if left not in HANDLERS:
        return f'(unknown cond source: {left!r}; '\
               f'try one of {sorted(HANDLERS.keys())})'
    actual = invoke(left, {}).lower()
    matched = right in actual
    if is_not:
        matched = not matched
    if matched:
        return act
    return f'(condition false: {left}={actual!r}, expected {right!r})'


# ─── Registry ──────────────────────────────────────────────────────


HANDLERS: dict[str, Callable[[dict], str]] = {
    'mood':             _h_mood,
    'now':              _h_now,
    'today':            _h_today,
    'qrpair_count':     _h_qrpair_count,
    'git_branch':       _h_git_branch,
    'harness_profiles': _h_harness_profiles,
    'recent_chat':      _h_recent_chat,
    'latest_dream':     _h_latest_dream,
    'cond_act':         _h_cond_act,
}


def invoke(name: str, slots: dict[str, str] | None = None) -> str:
    """Call a registered handler by name.  Returns a string; on
    unknown name returns a visible error string so authoring
    mistakes surface in the UI rather than 500-ing."""
    fn = HANDLERS.get(name)
    if fn is None:
        return f'[unknown handler: {name}]'
    try:
        return fn(slots or {})
    except Exception as e:                           # noqa: BLE001
        return f'[handler {name} failed: {type(e).__name__}: {e}]'


def names() -> list[str]:
    """Sorted list of available handler names."""
    return sorted(HANDLERS.keys())
