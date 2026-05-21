"""barding views — read & edit settings.json, list bundle-patch
wishes, surface the installed Claude Code version.

The app never invokes the `claude` binary.  Filesystem writes go
through `_atomic_write_json` which tmp-writes + renames so a crash
mid-write can't truncate a live settings.json.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from django.db.models import Avg, Count, Max
from django.shortcuts import get_object_or_404

from .models import (
    BundlePatchWish, SettingsScope,
    Harness, Technique, Observation, DistillationProposal,
)


CLAUDE_BIN_DEFAULT = os.path.expanduser('~/.local/bin/claude')

# Settings keys we expose as first-class form fields.  All four are
# verified present in the 2.1.141 binary via grep (2026-05-14).
SANCTIONED_BOOLS = [
    ('spinnerTipsEnabled',
        'Spinner tips ("Pondering…", "Ruminating…", "Marinating…").'),
    ('showThinkingSummaries',
        'Show summarised thinking before the answer.'),
    ('autoCompactEnabled',
        'Auto-compact the conversation when context fills up.'),
    ('promptSuggestionEnabled',
        'Show inline prompt suggestions.'),
]

# Customisations Claude Code does NOT officially support — surfaced
# honestly so the user isn't misled.  See BundlePatchWish for the
# manual recipe path.
UNSUPPORTED_NOTES = [
    ('Custom thinking verbs',
     'The verb list ("Pondering", "Ruminating", "Marinating", …) is a '
     'plain string array inside the ELF binary.  No setting overrides '
     'it.  Editing requires hex-patching the binary in place and is '
     'clobbered on every upgrade.'),
    ('Custom spinner glyph',
     'The animated spinner characters are baked into the binary as a '
     'cycling string.  Same caveat as verbs — patchable, but not '
     'persistent across upgrades.'),
    ('Permission allowlist via UI',
     'This MVP does not edit `permissions.allow` / `permissions.deny` '
     'arrays.  Use the raw-JSON textarea for now.'),
    ('Hook script editing',
     'Hooks under the `hooks` key in settings.json are listed read-only.  '
     'Edit the referenced shell scripts in your editor of choice.'),
]


def _atomic_write_json(path: str, data) -> None:
    """Write JSON to *path* by first writing path + '.tmp' then
    renaming.  If anything raises before the rename the original file
    is untouched.  os.replace is atomic on POSIX."""
    tmp = path + '.tmp'
    blob = json.dumps(data, indent=2, sort_keys=False) + '\n'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(blob)
    os.replace(tmp, path)


def _read_scope(scope: SettingsScope) -> tuple[dict | None, str]:
    """Return (parsed_dict, raw_text).  parsed_dict is None if the
    file is missing or unparseable; raw_text is '' if missing."""
    try:
        with open(scope.path, 'r', encoding='utf-8') as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, ''
    except OSError:
        return None, ''
    try:
        return json.loads(raw), raw
    except ValueError:
        return None, raw


def _installed_version() -> dict:
    """Resolve the Claude Code symlink and return basic facts."""
    bin_path = CLAUDE_BIN_DEFAULT
    info = {
        'bin_path': bin_path,
        'exists': os.path.exists(bin_path),
        'resolved': None,
        'version': None,
        'mtime': None,
        'size': None,
    }
    if not info['exists']:
        return info
    try:
        resolved = os.path.realpath(bin_path)
        info['resolved'] = resolved
        # Version string is the basename of the resolved path:
        # ~/.local/share/claude/versions/2.1.141 → "2.1.141".
        info['version'] = os.path.basename(resolved)
        st = os.stat(resolved)
        info['mtime'] = _dt.datetime.fromtimestamp(st.st_mtime).isoformat(
            timespec='seconds')
        info['size'] = st.st_size
    except OSError:
        pass
    return info


@login_required
def index(request):
    """Hub: comparative-study links on the left, Claude-Code operator
    tools on the right.  Counts come from the study models so the page
    doubles as an at-a-glance status of how much we've catalogued."""
    scopes = []
    for sc in SettingsScope.objects.filter(is_active=True):
        parsed, raw = _read_scope(sc)
        scopes.append({
            'obj': sc,
            'parsed': parsed,
            'raw': raw,
            'pretty': json.dumps(parsed, indent=2) if parsed is not None else raw,
            'exists': bool(raw) or parsed is not None,
            'parse_error': parsed is None and bool(raw),
        })
    study_counts = {
        'harnesses': Harness.objects.count(),
        'techniques': Technique.objects.count(),
        'observations': Observation.objects.count(),
        'distill_total': DistillationProposal.objects.count(),
        'distill_include': DistillationProposal.objects
                             .filter(decision='include').count(),
        'distill_simplified': DistillationProposal.objects
                                .filter(decision='simplified').count(),
        'distill_skip': DistillationProposal.objects
                          .filter(decision='skip').count(),
    }
    return render(request, 'barding/index.html', {
        'version': _installed_version(),
        'scopes': scopes,
        'sanctioned_bools': SANCTIONED_BOOLS,
        'unsupported_notes': UNSUPPORTED_NOTES,
        'wishes': BundlePatchWish.objects.all()[:50],
        'study_counts': study_counts,
    })


# ─── Comparative-study views ───────────────────────────────────────

@login_required
def harness_list(request):
    rows = []
    for h in Harness.objects.all():
        rows.append({
            'obj': h,
            'observation_count': h.observations.count(),
            'technique_count': h.observations.values('technique').distinct().count(),
            'last_seen': h.observations.aggregate(m=Max('observed_at'))['m'],
        })
    return render(request, 'barding/harness_list.html', {'rows': rows})


@login_required
def harness_detail(request, slug):
    h = get_object_or_404(Harness, slug=slug)
    obs = (h.observations.select_related('technique')
                          .order_by('technique__category',
                                    '-technique__magic_weight'))
    by_cat = {}
    for o in obs:
        by_cat.setdefault(o.technique.get_category_display(), []).append(o)
    extras = None
    if h.slug == 'claude-code-cli':
        # The Claude-Code-specific deep-observation set lives in the
        # original barding models — link out so users can jump.
        extras = {
            'version': _installed_version(),
            'scope_count': SettingsScope.objects.filter(is_active=True).count(),
            'wish_count': BundlePatchWish.objects.count(),
        }
    return render(request, 'barding/harness_detail.html', {
        'harness': h,
        'by_category': by_cat,
        'observation_count': obs.count(),
        'extras': extras,
    })


@login_required
def technique_list(request):
    by_cat = {}
    for t in Technique.objects.all():
        by_cat.setdefault(t.get_category_display(), []).append({
            'obj': t,
            'observation_count': t.observations.count(),
            'harness_count': t.observations.values('harness').distinct().count(),
            'has_proposal': hasattr(t, 'distill'),
        })
    # Preserve canonical category order from the choices.
    from .models import TECHNIQUE_CATEGORIES
    display_order = [label for _key, label in TECHNIQUE_CATEGORIES]
    ordered = [(label, by_cat[label]) for label in display_order
               if label in by_cat]
    return render(request, 'barding/technique_list.html', {
        'by_category': ordered,
    })


@login_required
def technique_detail(request, slug):
    t = get_object_or_404(Technique, slug=slug)
    obs = (t.observations.select_related('harness')
                          .order_by('-confidence', 'harness__name'))
    proposal = getattr(t, 'distill', None)
    return render(request, 'barding/technique_detail.html', {
        'technique': t,
        'observations': obs,
        'proposal': proposal,
    })


@login_required
def compare_grid(request):
    """Harness × Technique grid.  Each cell shows the max-confidence
    observation we have for that pair (or blank if none).  Techniques
    are grouped by category and sorted by magic_weight; harnesses are
    sorted by name."""
    harnesses = list(Harness.objects.all())
    techniques = list(Technique.objects.all())
    # Build a (technique_id, harness_id) → best observation map in one
    # query to avoid N×M lookups.
    cells = {}
    for o in Observation.objects.all().only(
            'harness_id', 'technique_id', 'confidence', 'source_kind'):
        key = (o.technique_id, o.harness_id)
        prev = cells.get(key)
        if prev is None or o.confidence > prev['confidence']:
            cells[key] = {
                'confidence': o.confidence,
                'source_kind': o.source_kind,
            }
    # Group techniques by category for the row blocks.
    from .models import TECHNIQUE_CATEGORIES
    cat_order = [label for _key, label in TECHNIQUE_CATEGORIES]
    by_cat = {}
    for t in techniques:
        by_cat.setdefault(t.get_category_display(), []).append(t)
    groups = []
    for cat in cat_order:
        if cat not in by_cat:
            continue
        rows = []
        for t in by_cat[cat]:
            row = {'technique': t, 'cells': []}
            for h in harnesses:
                row['cells'].append(cells.get((t.id, h.id)))
            rows.append(row)
        groups.append((cat, rows))
    return render(request, 'barding/compare_grid.html', {
        'harnesses': harnesses,
        'groups': groups,
    })


@login_required
def distill_plan(request):
    """The actionable output of the study: per-technique decisions for
    the caformer harness, ranked by priority and magic_weight."""
    proposals = (DistillationProposal.objects
                   .select_related('technique')
                   .order_by('priority', '-technique__magic_weight'))
    # Techniques without a proposal — surface as "needs decision".
    unassigned = (Technique.objects
                    .filter(distill__isnull=True)
                    .order_by('-magic_weight'))
    summary = {
        'include': proposals.filter(decision='include').count(),
        'simplified': proposals.filter(decision='simplified').count(),
        'skip': proposals.filter(decision='skip').count(),
        'research': proposals.filter(decision='research').count(),
        'unassigned': unassigned.count(),
    }
    budget_total = sum((p.byte_budget or 0) for p in proposals
                       if p.decision in ('include', 'simplified'))
    return render(request, 'barding/distill_plan.html', {
        'proposals': proposals,
        'unassigned': unassigned,
        'summary': summary,
        'budget_total': budget_total,
    })


@login_required
def edit_scope(request, scope_id):
    scope = get_object_or_404(SettingsScope, pk=scope_id)
    parsed, raw = _read_scope(scope)
    errors = []

    if request.method == 'POST':
        # Two submission paths:
        #   raw_json — replace whole file from textarea
        #   form     — toggle sanctioned booleans + write back
        mode = request.POST.get('mode', 'form')
        if mode == 'raw_json':
            new_raw = request.POST.get('raw_json', '')
            try:
                new_data = json.loads(new_raw) if new_raw.strip() else {}
            except ValueError as exc:
                errors.append(f'JSON parse error: {exc}')
            else:
                try:
                    _atomic_write_json(scope.path, new_data)
                    messages.success(request, f'Wrote {scope.path}.')
                    return redirect('barding:edit_scope', scope_id=scope.id)
                except OSError as exc:
                    errors.append(f'Write failed: {exc}')
        else:
            # form mode — start from current parsed contents (or {}) and
            # overlay the checkbox values, then atomic-write.
            data = dict(parsed) if isinstance(parsed, dict) else {}
            for key, _label in SANCTIONED_BOOLS:
                data[key] = (request.POST.get(key) == 'on')
            try:
                _atomic_write_json(scope.path, data)
                messages.success(request, f'Wrote {scope.path}.')
                return redirect('barding:edit_scope', scope_id=scope.id)
            except OSError as exc:
                errors.append(f'Write failed: {exc}')

    # Render with current state (re-read after a failed write so the
    # textarea reflects on-disk).
    parsed, raw = _read_scope(scope)
    pretty = json.dumps(parsed, indent=2) if parsed is not None else raw
    # Render the sanctioned booleans as a list of (key, label, checked)
    # triples so the template can iterate without a custom dict filter.
    bool_rows = []
    pd = parsed if isinstance(parsed, dict) else {}
    for key, label in SANCTIONED_BOOLS:
        bool_rows.append((key, label, bool(pd.get(key, False))))

    # Surface hooks + permissions read-only for orientation.
    hooks = pd.get('hooks')
    permissions = pd.get('permissions')
    hooks_json = json.dumps(hooks, indent=2) if hooks is not None else None
    permissions_json = (json.dumps(permissions, indent=2)
                        if permissions is not None else None)

    return render(request, 'barding/edit_scope.html', {
        'scope': scope,
        'pretty': pretty,
        'raw': raw,
        'parsed_ok': parsed is not None,
        'exists': bool(raw) or parsed is not None,
        'bool_rows': bool_rows,
        'hooks_json': hooks_json,
        'permissions_json': permissions_json,
        'errors': errors,
    })


@login_required
def bundle_patches(request):
    if request.method == 'POST':
        action = request.POST.get('action', 'create')
        if action == 'create':
            kind = request.POST.get('kind', 'verb')
            target = (request.POST.get('target') or '').strip()
            replacement = (request.POST.get('replacement') or '').strip()
            notes = (request.POST.get('notes') or '').strip()
            if target and replacement:
                BundlePatchWish.objects.create(
                    kind=kind, target=target,
                    replacement=replacement, notes=notes)
                messages.success(request,
                    f'Wish recorded: {target!r} → {replacement!r}.')
            else:
                messages.error(request, 'Both target and replacement required.')
        elif action == 'toggle':
            wish = get_object_or_404(BundlePatchWish, pk=request.POST.get('id'))
            wish.applied = not wish.applied
            wish.save(update_fields=['applied', 'updated_at'])
        elif action == 'delete':
            wish = get_object_or_404(BundlePatchWish, pk=request.POST.get('id'))
            wish.delete()
            messages.info(request, 'Wish removed.')
        return redirect('barding:bundle_patches')

    version = _installed_version()
    binary_path = version.get('resolved') or CLAUDE_BIN_DEFAULT
    wishes = []
    for w in BundlePatchWish.objects.all():
        wishes.append({
            'obj': w,
            'recipe': w.sed_recipe(binary_path),
            'length_ok': w.length_ok,
        })
    return render(request, 'barding/bundle_patches.html', {
        'wishes': wishes,
        'version': version,
        'patch_kinds': BundlePatchWish._meta.get_field('kind').choices,
    })


@login_required
def version_status(request):
    return render(request, 'barding/_version_partial.html', {
        'version': _installed_version(),
    })


# ─── Binary inspector ───────────────────────────────────────────────

@login_required
def binary_index(request):
    """Summary page: where the binary is, how big it is, what shape it
    has (ELF class / machine / sections / dynamic libs / build ID).
    Read-only; never mutates the file."""
    from . import binary as _bin

    error = None
    summary = None
    elf = None
    try:
        summary = _bin.file_summary()
        elf = _bin.elf_summary()
    except FileNotFoundError as e:
        error = str(e)
    except Exception as e:                              # noqa: BLE001
        error = f'{type(e).__name__}: {e}'

    hits = None
    needle = (request.GET.get('q') or '').strip()
    if needle and not error:
        try:
            hits = _bin.search_bytes(needle, max_hits=24)
        except ValueError as e:
            error = str(e)

    return render(request, 'barding/binary_index.html', {
        'error':   error,
        'summary': summary,
        'elf':     elf,
        'needle':  needle,
        'hits':    hits,
    })


@login_required
def binary_hex(request):
    """Paged hex view of the binary.  Querystring: offset (int, hex
    or decimal), length (int, bytes per page, 256..65536)."""
    from . import binary as _bin

    def _parse_int(s, default):
        s = (s or '').strip()
        if not s: return default
        try:
            return int(s, 16) if s.lower().startswith('0x') else int(s)
        except ValueError:
            return default

    error = None
    summary = None
    rows = None
    offset = _parse_int(request.GET.get('offset'), 0)
    length = _parse_int(request.GET.get('length'), _bin.DEFAULT_PAGE_BYTES)
    length = max(64, min(length, 65536))
    try:
        summary = _bin.file_summary()
        rows = _bin.hex_page(offset, length)
    except FileNotFoundError as e:
        error = str(e)
    except ValueError as e:
        error = str(e)
    except Exception as e:                              # noqa: BLE001
        error = f'{type(e).__name__}: {e}'

    file_size = summary.size_bytes if summary else 0
    prev_offset = max(0, offset - length)
    next_offset = min(max(0, file_size - 1), offset + length)
    return render(request, 'barding/binary_hex.html', {
        'error':       error,
        'summary':     summary,
        'rows':        rows,
        'offset':      offset,
        'length':      length,
        'prev_offset': prev_offset,
        'next_offset': next_offset,
        'offset_hex':  f'0x{offset:08x}',
    })
