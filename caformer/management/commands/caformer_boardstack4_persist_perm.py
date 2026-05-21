"""Recompute + persist the boardstack4 cascade's path-permutation.

Mirrors caformer_byterouter_persist_perm but for boardstack4.  Walks
the router corpus through the cascade, derives a many-to-one mapping
from 4-colour path → K=4 category via greedy max-count assignment,
saves as permutation.json alongside boardstack4_meta.json.

Lets a high-fitness-but-low-mode-projection cascade (e.g. v3 at
fit=0.8375 but mode_acc=42.5%) recover its real category signal.

  manage.py caformer_boardstack4_persist_perm --in-dir .artifacts/boardstack4_v3
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Compute + persist a boardstack4 path-permutation against the router corpus.'

    def add_arguments(self, parser):
        parser.add_argument('--in-dir', type=str,
                              default='.artifacts/boardstack4_v3')

    def handle(self, *, in_dir, **opts):
        from caformer.boardstack4 import BoardStack4
        from caformer.router_corpus import CORPUS, CATEGORY_NAMES, by_category

        src = Path(settings.BASE_DIR) / in_dir
        if not (src / 'boardstack4_meta.json').exists():
            self.stdout.write(self.style.ERROR(
                f'no boardstack4_meta.json at {src}'))
            return
        self.stdout.write(f'loading from {src} …')
        stack = BoardStack4(src)
        self.stdout.write(
            f'  side={stack.side} ticks={stack.ticks}')

        # Walk corpus → path bag.
        bag: dict[tuple[int, ...], list[int]] = {}
        for prompt, target in CORPUS:
            path = stack.cascade(prompt)
            b = bag.get(path)
            if b is None:
                b = [0, 0, 0, 0]
                bag[path] = b
            b[int(target) & 3] += 1
        self.stdout.write(f'  {len(bag)} distinct cascade paths across '
                          f'{len(CORPUS)} prompts')

        # Greedy: each path → its dominant category.
        mapping: dict[tuple[int, ...], int] = {}
        n_correct = 0
        for path, counts in bag.items():
            best_cat = 0
            best_count = counts[0]
            for t in range(1, 4):
                if counts[t] > best_count:
                    best_count = counts[t]
                    best_cat = t
            mapping[path] = best_cat
            n_correct += best_count
        acc = n_correct / max(1, len(CORPUS))
        self.stdout.write(
            f'  best-permutation accuracy: '
            f'{n_correct}/{len(CORPUS)} ({acc:.3f})')

        # Per-category breakdown.
        for cat, names in by_category().items():
            n = 0
            ok = 0
            for prompt, target in CORPUS:
                if target != cat: continue
                n += 1
                path = stack.cascade(prompt)
                if mapping.get(path) == cat: ok += 1
            self.stdout.write(
                f'    {CATEGORY_NAMES[cat]:12}: {ok:>2}/{n:<2} '
                f'({100*ok/max(1,n):5.1f}%)')

        # Persist.  JSON keys must be strings; convert tuple → 'a-b-c-d'.
        out = src / 'permutation.json'
        out.write_text(json.dumps({
            '-'.join(str(c) for c in k): int(v)
            for k, v in mapping.items()
        }, indent=2))
        self.stdout.write(self.style.SUCCESS(
            f'permutation written to {out}'))

        # Clear cache so the next get_stack() picks it up.
        from caformer import boardstack4 as _bs4
        _bs4._CACHE.clear()
