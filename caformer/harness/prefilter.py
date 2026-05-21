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
    category: int                  # int code 0..3
    name: str                      # 'personality' | 'information' | …
    colour: str                    # hex, no leading #
    available: bool                # False if router not trained
    votes: list[int] | None = None # raw per-tick votes, for UI/debug


def classify(prompt: str) -> PrefilterResult:
    """Route ``prompt`` to a category.  Soft-fails to PERSONALITY when
    the router model isn't on disk yet — gives the harness a stable
    fallback during initial setup or for fresh deployments."""
    try:
        from caformer import router as router_mod
        rt = router_mod.get_router()
    except FileNotFoundError:
        return PrefilterResult(
            category=PERSONALITY,
            name=CATEGORY_NAMES[PERSONALITY],
            colour=CATEGORY_COLOURS[PERSONALITY],
            available=False)
    except Exception:                                # noqa: BLE001
        return PrefilterResult(
            category=PERSONALITY,
            name=CATEGORY_NAMES[PERSONALITY],
            colour=CATEGORY_COLOURS[PERSONALITY],
            available=False)
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
        votes=votes)
