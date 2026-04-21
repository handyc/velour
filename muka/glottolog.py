"""Glottolog languoid lookup — shipped offline.

`konso/data/glottolog_languages.csv` is a trimmed extract of the Glottolog
5.3 languoid dump: 8618 rows at `level=language`, with columns

    g,n,iso,fam,ma,lat,lon

(glottocode, name, ISO 639-3, top-family-name, macroarea, latitude, longitude).

The extract is built once and committed; see the commit that added
this module for the build script. Glottolog releases slowly (roughly
once a year) so a periodic refresh is reasonable but not urgent.

This module reads the CSV lazily, caches it in memory, and offers:

  all_rows()             → list[dict]
  find_by_glottocode(g)  → dict | None
  search(query, limit)   → list[dict] ranked by match quality
  random_unseen(exclude) → dict | None (excludes glottocodes already used)
"""

from __future__ import annotations

import csv
import os
import random
from functools import lru_cache

from django.conf import settings

_CSV_PATH = os.path.join(
    str(settings.BASE_DIR), 'muka', 'data', 'glottolog_languages.csv')


@lru_cache(maxsize=1)
def all_rows():
    if not os.path.isfile(_CSV_PATH):
        return []
    with open(_CSV_PATH, newline='') as f:
        return list(csv.DictReader(f))


def find_by_glottocode(code):
    code = (code or '').strip().lower()
    if not code:
        return None
    for r in all_rows():
        if r['g'] == code:
            return r
    return None


def search(query, limit=15):
    """Case-insensitive fuzzy-ish name search plus glottocode + ISO match.
    Ranks: exact glottocode > exact ISO > name startswith > name contains.
    """
    q = (query or '').strip().lower()
    if not q:
        return []
    rows = all_rows()
    bucket_glot, bucket_iso, bucket_start, bucket_has = [], [], [], []
    for r in rows:
        name_l = r['n'].lower()
        if r['g'] == q:
            bucket_glot.append(r)
        elif r['iso'].lower() == q:
            bucket_iso.append(r)
        elif name_l.startswith(q):
            bucket_start.append(r)
        elif q in name_l:
            bucket_has.append(r)
    bucket_start.sort(key=lambda r: r['n'])
    bucket_has.sort(key=lambda r: r['n'])
    out = bucket_glot + bucket_iso + bucket_start + bucket_has
    return out[:limit]


def random_unseen(exclude_codes):
    """Pick one row whose glottocode is not in `exclude_codes`."""
    rows = all_rows()
    if not rows:
        return None
    exclude = set(c for c in exclude_codes if c)
    pool = [r for r in rows if r['g'] not in exclude]
    if not pool:
        return None
    return random.choice(pool)
