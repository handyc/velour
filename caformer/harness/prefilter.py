"""Prefilter — classify the incoming prompt into one of the four
router categories before the harness chooses a strategy.

We reuse the existing CA-based 4-way router (caformer.router) which
classifies on a hand-labelled 80-example corpus and currently runs
at ~71 % accuracy.  This is the "magic" the user asked for: even a
cheap classifier turns the harness from a single response shape into
something that picks register based on intent.

The prefilter returns a ``PrefilterResult`` with the integer category
+ a human label + a confidence flag.  If the router isn't trained
yet, we degrade gracefully to PERSONALITY (the safest fallback for a
chat surface) with available=False so the UI can show "router off".
"""
from __future__ import annotations

from dataclasses import dataclass

from caformer.router_corpus import (CATEGORY_NAMES, CATEGORY_COLOURS,
                                            PERSONALITY)


@dataclass
class PrefilterResult:
    category: int                  # int code 0..3 (path-projected)
    name: str                      # 'personality' | 'information' | …
    colour: str                    # hex, no leading #
    available: bool                # False if router/stack not trained
    mode: str = 'router'           # which prefilter ran
    votes: list[int] | None = None # router majority-vote breakdown
    path: tuple[int, ...] | None = None  # boardstack4 4-colour path


def _fallback() -> PrefilterResult:
    return PrefilterResult(
        category=PERSONALITY,
        name=CATEGORY_NAMES[PERSONALITY],
        colour=CATEGORY_COLOURS[PERSONALITY],
        available=False,
        mode='fallback')


def _classify_router(prompt: str) -> PrefilterResult:
    try:
        from caformer import router as router_mod
        rt = router_mod.get_router()
    except (FileNotFoundError, Exception):           # noqa: BLE001
        return _fallback()
    cat = rt.route(prompt)
    try:
        votes = rt.route_votes(prompt)
    except Exception:                                # noqa: BLE001
        votes = None
    return PrefilterResult(
        category=cat,
        name=CATEGORY_NAMES.get(cat, '?'),
        colour=CATEGORY_COLOURS.get(cat, 'ffffff'),
        available=True,
        mode='router',
        votes=votes)


def _classify_boardstack4(prompt: str) -> PrefilterResult:
    try:
        from caformer import boardstack4 as bs4
        stack = bs4.get_stack()
    except (FileNotFoundError, Exception):           # noqa: BLE001
        # Fall back to the single-LUT router when boardstack4 isn't
        # trained yet — keeps the harness usable on a fresh deploy.
        result = _classify_router(prompt)
        if result.available:
            result.mode = 'router (boardstack4 missing)'
        return result
    path = stack.cascade(prompt)
    cat = bs4.path_to_category(path)
    return PrefilterResult(
        category=cat,
        name=CATEGORY_NAMES.get(cat, '?'),
        colour=CATEGORY_COLOURS.get(cat, 'ffffff'),
        available=True,
        mode='boardstack4',
        path=path)


def classify(prompt: str, mode: str = 'router') -> PrefilterResult:
    """Route ``prompt`` to a category.  ``mode`` picks the prefilter:

      - 'router'      — the original single-LUT trained classifier
      - 'boardstack4' — the 4-board sequential cascade (returns the
                         4-colour path in addition to the projected
                         category)

    Soft-fails to PERSONALITY when neither artifact is on disk."""
    mode = (mode or 'router').strip().lower()
    if mode == 'boardstack4':
        return _classify_boardstack4(prompt)
    return _classify_router(prompt)
