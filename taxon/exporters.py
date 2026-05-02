"""Exporters — push a Taxon Rule into a sibling app's native form.

Inverse of importers.py. Phase 1 supports automaton (creates a RuleSet
+ Simulation so the link lands on a running canvas).
"""
from __future__ import annotations

import random

from django.db import transaction
from django.utils.crypto import get_random_string

from automaton.models import ExactRule, RuleSet, Simulation
from automaton.packed import PackedRuleset, ansi256_to_hex


def to_automaton(rule, *, name: str = '') -> Simulation:
    """Create an automaton Simulation from a Taxon Rule.

    Mirrors the side-effects of automaton.views.import_from_s3lab —
    same blob_sha1 dedupe, same starter Simulation. If a RuleSet with
    the same sha1 already exists, returns its most recent Simulation
    (or creates one if none exists yet).
    """
    if rule.kind != 'hex_k4_packed' or rule.n_colors != 4:
        raise ValueError(f'only K=4 packed rules are exportable to automaton '
                         f'(rule {rule.slug} is {rule.kind} K={rule.n_colors})')

    palette = bytes(rule.palette_ansi)
    packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
    sha1 = rule.sha1

    existing = RuleSet.objects.filter(
        source_metadata__blob_sha1=sha1,
    ).first()
    if existing:
        sim = existing.simulations.order_by('-created_at').first()
        if sim:
            return sim
        # RuleSet exists but has no Simulation; build one now so the
        # caller has somewhere to land.
        return _create_starter_sim(existing)

    if not name:
        name = f'taxon {get_random_string(6).lower()}'
    while RuleSet.objects.filter(name=name).exists():
        name = f'taxon {get_random_string(6).lower()}'

    explicit = packed.to_explicit(skip_identity=True)
    n_explicit = len(explicit)
    palette_css = [ansi256_to_hex(idx) for idx in palette]

    with transaction.atomic():
        ruleset = RuleSet.objects.create(
            name=name,
            description=(
                f'Imported from Taxon (rule {rule.slug}, sha1 {sha1[:10]}…). '
                f'{n_explicit} non-identity patterns out of '
                f'{4**7:,} possible 7-tuples.'
            ),
            n_colors=4,
            source='operator',
            palette=palette_css,
            source_metadata={
                'origin':           'imported',
                'source':           'taxon',
                'taxon_slug':       rule.slug,
                'blob_sha1':        sha1,
                'palette_hex':      palette.hex(),
                'palette_ansi256':  list(palette),
                'palette_css':      palette_css,
                'n_explicit':       n_explicit,
            },
        )
        ExactRule.objects.bulk_create([
            ExactRule(
                ruleset=ruleset,
                self_color=er['s'],
                n0_color=er['n'][0], n1_color=er['n'][1],
                n2_color=er['n'][2], n3_color=er['n'][3],
                n4_color=er['n'][4], n5_color=er['n'][5],
                result_color=er['r'],
                priority=i,
            )
            for i, er in enumerate(explicit)
        ])
        return _create_starter_sim(ruleset)


def _create_starter_sim(ruleset) -> Simulation:
    sm = ruleset.source_metadata or {}
    palette_css = sm.get('palette_css') or list(ruleset.palette) or []
    sim_w, sim_h = 16, 16
    grid = [[random.randint(0, ruleset.n_colors - 1) for _ in range(sim_w)]
            for _ in range(sim_h)]
    return Simulation.objects.create(
        name=ruleset.name,
        ruleset=ruleset,
        width=sim_w, height=sim_h,
        palette=palette_css,
        grid_state=grid,
    )
