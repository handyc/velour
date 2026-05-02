"""Importers — pull rules from sibling apps into the Taxon library.

Each importer is idempotent on sha1 of the genome bytes: re-importing
the same rule updates name/source_ref but doesn't duplicate.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from django.utils.text import slugify

from automaton.packed import (
    PackedRuleset, hex_to_rgb, nearest_ansi256, parse_genome_bin,
)

from .hexnn import pack_hexnn
from .models import KIND_HEX_K4_PACKED, KIND_HEX_NN, Rule


def _unique_slug(base: str) -> str:
    """Pick a slug that doesn't collide with an existing Rule."""
    base = slugify(base)[:60] or 'rule'
    candidate = base
    n = 2
    while Rule.objects.filter(slug=candidate).exists():
        candidate = f'{base}-{n}'
        n += 1
    return candidate


def upsert(genome: bytes, palette_ansi: bytes, *,
           name: str = '', source: str = 'manual',
           source_ref: str = '', notes: str = '') -> Rule:
    """Insert or update a Rule by sha1(genome). Genome is the 4,096-byte
    PackedRuleset payload (NOT the 4,104-byte HXC4 file)."""
    if len(genome) != 4096:
        raise ValueError(f'expected 4096-byte K=4 genome, got {len(genome)}')
    if len(palette_ansi) != 4:
        raise ValueError(f'expected 4-byte ANSI palette, got {len(palette_ansi)}')

    sha = hashlib.sha1(genome).hexdigest()
    existing = Rule.objects.filter(sha1=sha).first()
    if existing:
        # Refresh light metadata; don't clobber a user-edited name.
        if not existing.name and name:
            existing.name = name
        if source_ref and source_ref not in (existing.source_ref or ''):
            existing.source_ref = (
                f'{existing.source_ref}; {source_ref}'
                if existing.source_ref else source_ref
            )
        existing.palette_ansi = palette_ansi
        existing.save()
        return existing

    rule = Rule(
        slug=_unique_slug(name or sha[:10]),
        name=name,
        notes=notes,
        kind=KIND_HEX_K4_PACKED,
        n_colors=4,
        genome=genome,
        palette_ansi=palette_ansi,
        sha1=sha,
        source=source,
        source_ref=source_ref,
    )
    rule.save()
    return rule


def import_hxc4_blob(blob: bytes, *, name: str = '',
                     source: str = 'manual',
                     source_ref: str = '') -> Rule:
    """Import a 4,104-byte HXC4 / genome.bin file."""
    palette, packed = parse_genome_bin(blob)
    return upsert(bytes(packed.data), palette,
                  name=name, source=source, source_ref=source_ref)


def import_automaton_simulation(sim) -> Rule:
    """Pull the packed ruleset for an automaton.Simulation."""
    rs = sim.ruleset
    if rs.n_colors != 4:
        raise ValueError(f'only K=4 RuleSets are importable (got K={rs.n_colors})')
    explicit = [
        {'s': er.self_color,
         'n': [er.n0_color, er.n1_color, er.n2_color, er.n3_color,
               er.n4_color, er.n5_color],
         'r': er.result_color}
        for er in rs.exact_rules.all().order_by('priority')
    ]
    packed = PackedRuleset.from_explicit(explicit, n_colors=4)

    sm = rs.source_metadata or {}
    saved = sm.get('palette_ansi256')
    if isinstance(saved, list) and len(saved) == 4:
        palette_bytes = bytes(int(x) & 0xFF for x in saved)
    else:
        from automaton.views import DEFAULT_PALETTE
        css = list(rs.palette) if rs.palette else list(DEFAULT_PALETTE)
        while len(css) < 4:
            css.append('#000000')
        palette_bytes = bytes(nearest_ansi256(hex_to_rgb(c)) for c in css[:4])

    return upsert(
        bytes(packed.data), palette_bytes,
        name=rs.name or sim.name,
        source='automaton',
        source_ref=f'sim={sim.slug}; ruleset={rs.slug}',
    )


def import_automaton_ruleset(rs) -> Optional[Rule]:
    """Pull the packed ruleset for an automaton.RuleSet (no Simulation)."""
    if rs.n_colors != 4:
        return None
    explicit = [
        {'s': er.self_color,
         'n': [er.n0_color, er.n1_color, er.n2_color, er.n3_color,
               er.n4_color, er.n5_color],
         'r': er.result_color}
        for er in rs.exact_rules.all().order_by('priority')
    ]
    packed = PackedRuleset.from_explicit(explicit, n_colors=4)

    sm = rs.source_metadata or {}
    saved = sm.get('palette_ansi256')
    if isinstance(saved, list) and len(saved) == 4:
        palette_bytes = bytes(int(x) & 0xFF for x in saved)
    else:
        from automaton.views import DEFAULT_PALETTE
        css = list(rs.palette) if rs.palette else list(DEFAULT_PALETTE)
        while len(css) < 4:
            css.append('#000000')
        palette_bytes = bytes(nearest_ansi256(hex_to_rgb(c)) for c in css[:4])

    return upsert(
        bytes(packed.data), palette_bytes,
        name=rs.name,
        source='automaton',
        source_ref=f'ruleset={rs.slug}',
    )


def upsert_hexnn(K: int, keys: bytes, outs: bytes,
                 palette_ansi: bytes, *,
                 name: str = '', source: str = 'manual',
                 source_ref: str = '', notes: str = '') -> Rule:
    """Insert or update a HexNN-format Rule. Genome stored as taxon's
    HXNN binary blob (b'HXNN' + u32 K + u32 N + keys + outs).

    palette_ansi is K bytes of ANSI-256 indices; if shorter we pad
    with 0x10 (mid-range cube grey) so renders don't crash.
    """
    blob = pack_hexnn(K, keys, outs)
    if len(palette_ansi) < K:
        palette_ansi = palette_ansi + b'\x10' * (K - len(palette_ansi))
    elif len(palette_ansi) > K:
        palette_ansi = palette_ansi[:K]

    sha = hashlib.sha1(blob).hexdigest()
    existing = Rule.objects.filter(sha1=sha).first()
    if existing:
        if not existing.name and name:
            existing.name = name
        if source_ref and source_ref not in (existing.source_ref or ''):
            existing.source_ref = (
                f'{existing.source_ref}; {source_ref}'
                if existing.source_ref else source_ref
            )
        existing.palette_ansi = palette_ansi
        existing.save()
        return existing

    rule = Rule(
        slug=_unique_slug(name or sha[:10]),
        name=name,
        notes=notes,
        kind=KIND_HEX_NN,
        n_colors=K,
        genome=blob,
        palette_ansi=palette_ansi,
        sha1=sha,
        source=source,
        source_ref=source_ref,
    )
    rule.save()
    return rule


def import_strateta_population(payload: dict, *,
                                source: str = 'strateta',
                                source_ref: str = '') -> list[Rule]:
    """Import every entry of a strateta-population-v1 payload as Rules.

    The payload's ``library`` is a list of {keys, outputs, palette,
    grid, fitness} dicts; we only need keys + outputs + palette to
    build a HexNN Rule. ``palette`` is a list of CSS hex strings; we
    convert to ANSI-256 indices via nearest-match for storage.
    """
    if payload.get('format') != 'strateta-population-v1':
        raise ValueError(f'not a strateta-population-v1 payload (got {payload.get("format")!r})')
    K = int(payload['K'])
    library = payload['library']
    base_ref = source_ref or 'strateta-population'
    out: list[Rule] = []
    for i, lib in enumerate(library):
        keys = bytes(lib['keys'])
        outs = bytes(lib['outputs'])
        if len(keys) != len(outs) * 7:
            raise ValueError(f'entry {i}: keys length {len(keys)} != outs*7 = {len(outs) * 7}')
        palette_css = lib.get('palette') or []
        palette_ansi = bytearray()
        for h in palette_css:
            try:
                r = int(h[1:3], 16); g = int(h[3:5], 16); b = int(h[5:7], 16)
                palette_ansi.append(nearest_ansi256((r, g, b)))
            except Exception:
                palette_ansi.append(0x10)
        rule = upsert_hexnn(
            K, keys, outs, bytes(palette_ansi),
            name=f'strateta entry {i:03d}',
            source=source,
            source_ref=f'{base_ref}; entry={i}',
        )
        out.append(rule)
    return out


def import_huntrule(hunt_rule) -> Rule:
    """Pull a helix.HuntRule (4,096-byte BinaryField table)."""
    table = bytes(hunt_rule.table)
    # HuntRule has no palette of its own — use the s3lab default.
    palette = bytes([0, 9, 11, 13])  # black, red, yellow, magenta
    prov = (hunt_rule.provenance_json or {})
    sref = f'huntrule={hunt_rule.slug}'
    if 'origin' in prov:
        sref += f'; origin={prov["origin"]}'
    return upsert(
        table, palette,
        name=hunt_rule.slug,
        source='helix',
        source_ref=sref,
    )
