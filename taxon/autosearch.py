"""Background AutoSearch loop — finds K=4 hex CA rules of a target
Wolfram class.

Threading model: each running search owns one daemon thread. The
thread updates ``rules_tried`` / ``rules_kept`` / ``last_heartbeat``
via ``QuerySet.update`` so the user-facing ``status`` field isn't
clobbered when the user clicks Stop. The thread also re-reads
``status`` from the DB at the top of each iteration; flipping to
``stopped`` / ``paused`` causes the loop to exit cleanly.

Survives Django auto-reload? No — daemon threads die with the parent.
Browsers detect this via the heartbeat timestamp going stale. The
``mark_orphans`` helper flips long-stale running rows to ``crashed``
and is called by the status view on every poll, so the UI converges.
"""
from __future__ import annotations

import datetime
import random
import threading
import time
import traceback

from django.db import close_old_connections
from django.db.models import F
from django.utils import timezone
from django.utils.text import slugify

from automaton.packed import PackedRuleset

from . import importers
from .classifier import classify
from .engine import simulate
from .metrics import run_all
from .models import AutoSearch, Classification, KIND_HEX_K4_PACKED, MetricRun, Rule


# How long a running row may go without a heartbeat before we mark it
# crashed. Generous enough that a slow tick doesn't trip the wire.
ORPHAN_GRACE_SECONDS = 60


def _bump(search_pk: int, **fields) -> None:
    """Atomic per-iteration field update — never touches `status`."""
    AutoSearch.objects.filter(pk=search_pk).update(**fields)


def _stash_match(search: AutoSearch, packed: PackedRuleset, mvals: dict,
                 cls: int, conf: float, basis: dict) -> Rule | None:
    """Persist a matching rule + its metrics + classification."""
    palette = bytes([0, 9, 11, 13])  # black / red / yellow / magenta default
    name = f'{search.slug} #{search.rules_kept + 1:03d} class-{cls}'
    rule = importers.upsert(
        bytes(packed.data), palette,
        name=name,
        source='evolve',
        source_ref=f'autosearch={search.slug}; class={cls}; conf={conf:.2f}',
    )
    for metric_name, val in mvals.items():
        MetricRun.objects.create(
            rule=rule, metric=metric_name, value=val,
            grid_w=search.grid, grid_h=search.grid,
            horizon=search.horizon, seed=search.seed,
        )
    Classification.objects.create(
        rule=rule, wolfram_class=cls, confidence=conf, basis_json=basis,
    )
    return rule


def _mint_candidate(search: AutoSearch, rng: random.Random) -> PackedRuleset:
    """Generate one candidate per the search's seed_strategy.

    For 'mutate' / 'hybrid' modes we pull a random existing Rule of the
    target class and mutate it. If none exist we fall back to random.
    """
    want_mutate = (
        search.seed_strategy == AutoSearch.SEED_MUTATE
        or (search.seed_strategy == AutoSearch.SEED_HYBRID and rng.random() < 0.5)
    )
    if want_mutate:
        match = (Rule.objects
                 .filter(kind=KIND_HEX_K4_PACKED,
                         classifications__wolfram_class=search.target_class)
                 .order_by('?')
                 .first())
        if match is not None:
            parent = PackedRuleset(n_colors=4, data=bytes(match.genome))
            return parent.mutate(rate=search.mutation_rate, rng=rng)
    return PackedRuleset.random(n_colors=4, rng=rng)


def _run_loop(search_pk: int) -> None:
    """The actual search. Runs in a daemon thread."""
    try:
        # Fresh connection — daemon threads inherit the parent's
        # connection but it may be in a bad state. Close + reopen lazy.
        close_old_connections()
        AutoSearch.objects.filter(pk=search_pk).update(
            status=AutoSearch.STATUS_RUNNING,
            started_at=timezone.now(),
            last_heartbeat=timezone.now(),
        )
        search = AutoSearch.objects.get(pk=search_pk)
        deadline = time.monotonic() + max(1, search.max_seconds)
        rng = random.Random(search.seed or None)

        while time.monotonic() < deadline:
            search.refresh_from_db()
            if search.status in (AutoSearch.STATUS_STOPPED,
                                  AutoSearch.STATUS_PAUSED):
                break
            if search.rules_kept >= search.max_found:
                break

            try:
                candidate = _mint_candidate(search, rng)
                traj, hashes = simulate(
                    candidate, search.grid, search.grid,
                    search.horizon, rng.randrange(1, 1 << 31),
                )
                results = run_all(traj, hashes, candidate)
                mvals = {n: v for n, (v, _) in results.items()}
                cls, conf, basis = classify(mvals, horizon=search.horizon)
                kept = (cls == search.target_class
                        and conf >= search.target_min_confidence)
                if kept:
                    rule = _stash_match(search, candidate, mvals, cls, conf, basis)
                    log = (f'kept {rule.slug} (conf {conf:.2f}, '
                           f'λ={mvals.get("langton_lambda", 0):.2f}, '
                           f'act={mvals.get("activity_rate", 0):.2f})')
                else:
                    log = (f'skipped class={cls} conf={conf:.2f}')
                _bump(
                    search_pk,
                    rules_tried=F('rules_tried') + 1,
                    rules_kept=F('rules_kept') + (1 if kept else 0),
                    last_heartbeat=timezone.now(),
                    last_log=log,
                )
            except Exception as e:
                _bump(
                    search_pk,
                    rules_tried=F('rules_tried') + 1,
                    last_heartbeat=timezone.now(),
                    last_log=f'iteration error: {type(e).__name__}: {e}',
                )

        # Loop exited — either deadline, stop, pause, or max_found hit.
        # Don't trample if the user already set 'stopped'.
        AutoSearch.objects.filter(
            pk=search_pk,
            status__in=(AutoSearch.STATUS_RUNNING, AutoSearch.STATUS_QUEUED),
        ).update(
            status=AutoSearch.STATUS_FINISHED,
            finished_at=timezone.now(),
            last_heartbeat=timezone.now(),
        )
    except Exception:
        AutoSearch.objects.filter(pk=search_pk).update(
            status=AutoSearch.STATUS_CRASHED,
            finished_at=timezone.now(),
            last_log=traceback.format_exc()[-2000:],
        )
    finally:
        close_old_connections()


def launch(search: AutoSearch) -> threading.Thread:
    """Start a daemon thread for this search. Idempotent — if the
    search is already running, returns None."""
    if search.status == AutoSearch.STATUS_RUNNING:
        return None
    t = threading.Thread(
        target=_run_loop,
        args=(search.pk,),
        name=f'taxon-autosearch-{search.slug}',
        daemon=True,
    )
    t.start()
    return t


def request_stop(search: AutoSearch) -> None:
    """Flip status so the runner thread exits at the top of its next
    iteration. Safe to call from a view."""
    AutoSearch.objects.filter(pk=search.pk).update(
        status=AutoSearch.STATUS_STOPPED,
        finished_at=timezone.now(),
    )


def mark_orphans() -> int:
    """Flip 'running' rows whose heartbeat is older than the grace
    window to 'crashed'. Catches searches whose process died (server
    restart). Returns the number of rows touched.
    """
    cutoff = timezone.now() - datetime.timedelta(seconds=ORPHAN_GRACE_SECONDS)
    return (AutoSearch.objects
            .filter(status=AutoSearch.STATUS_RUNNING)
            .filter(last_heartbeat__lt=cutoff)
            .update(status=AutoSearch.STATUS_CRASHED,
                    finished_at=timezone.now()))


def make_slug(target_class: int) -> str:
    """A unique-enough slug — local timestamp + class. The unique
    constraint on AutoSearch.slug catches collisions and we retry."""
    base = f'class-{target_class}-{timezone.now().strftime("%Y%m%d-%H%M%S")}'
    candidate = slugify(base)[:60]
    n = 2
    while AutoSearch.objects.filter(slug=candidate).exists():
        candidate = f'{slugify(base)[:55]}-{n}'
        n += 1
    return candidate
