"""Hierarchical PICM descent — walks the 4-deep K=4 tree of PICMNode
rows to land a prompt at a specific leaf (or a partial-depth node
when no deeper child matches).

Compared with the flat per-agent PICMVocab, the tree gives:
  - 4-level filtering (up to 4^4 = 256 leaves)
  - O(4) lookups per descent (one level at a time)
  - Hand-curatable token lists at each node
  - Leaves point to QRPair labels + TemplatePattern tags for
    *specialised* dispatch subsets

Descent algorithm (simplified single-vocab variant — see the design
discussion 2026-05-21): at each level, find this node's children;
score each child by # of relevance_tokens matched against the
prompt; pick the highest-scoring child; descend.  If no children
match, stop.  Iteration cap = 4 (the tree's max depth).

The boardstack4 cascade runs in parallel; both produce a 4-colour
path.  The harness compares them: agreement = strong signal,
disagreement = potential meta-flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import picm as _picm


MAX_DEPTH = 4


@dataclass
class TreeDescent:
    path: str = ''                         # e.g. '1.0.2' or '' if no descent
    label_chain: list[str] = field(default_factory=list)
    matches_per_level: list[list[str]] = field(default_factory=list)
    leaf_node_id: int | None = None        # PICMNode.pk if leaf reached
    final_node_id: int | None = None       # deepest node walked
    depth: int = 0                         # how many levels we descended
    stopped_reason: str = ''               # 'leaf' | 'no_children' | 'no_match' | 'max_depth'

    def path_tuple(self) -> tuple[int, ...]:
        """The descent path as a tuple of K=4 colours, e.g. (1, 0, 2)."""
        if not self.path:
            return ()
        return tuple(int(c) for c in self.path.split('.'))

    def path_label(self) -> str:
        """Render the path as a dash-joined string for UI display."""
        t = self.path_tuple()
        if not t:
            return '∅'
        return '-'.join(str(c) for c in t)


def _children_of(prefix: str) -> Iterable:
    """Yield PICMNode rows whose tree_path is exactly one level below
    ``prefix``.  Empty prefix → top-level nodes ('0', '1', '2', '3')."""
    from caformer.models import PICMNode

    if prefix:
        # children are '{prefix}.0'..'{prefix}.3'
        candidate_paths = [f'{prefix}.{i}' for i in range(4)]
    else:
        candidate_paths = [str(i) for i in range(4)]
    return list(PICMNode.objects.filter(tree_path__in=candidate_paths))


def descend(prompt: str, max_depth: int = MAX_DEPTH) -> TreeDescent:
    """Walk the PICM tree against ``prompt``.

    At each level, score every candidate child by the number of
    relevance_tokens matched in the prompt; pick the highest scoring.
    Halt when: a leaf is reached, no children exist, or no child
    matches anything.

    Returns a TreeDescent with the path, label_chain, matches per
    level, and reason for stopping."""
    out = TreeDescent()
    if not prompt or not prompt.strip():
        out.stopped_reason = 'empty_prompt'
        return out

    prefix = ''
    for _depth in range(max_depth):
        kids = _children_of(prefix)
        if not kids:
            out.stopped_reason = 'no_children'
            break
        best = None
        best_score = 0
        best_matches: list[str] = []
        for k in kids:
            matches = _picm.match_keywords(prompt, k.relevance_tokens or [])
            score = len(matches)
            if score > best_score:
                best = k
                best_score = score
                best_matches = [t for (_i, t) in matches]
        if best is None or best_score == 0:
            out.stopped_reason = 'no_match'
            break
        prefix = best.tree_path
        out.path = prefix
        out.label_chain.append(best.label)
        out.matches_per_level.append(best_matches)
        out.final_node_id = best.pk
        out.depth += 1
        if best.is_leaf:
            out.leaf_node_id = best.pk
            out.stopped_reason = 'leaf'
            break
    else:
        out.stopped_reason = 'max_depth'
    return out


def compare_paths(tree_path: tuple[int, ...],
                       boardstack_path: tuple[int, ...]
                       ) -> dict:
    """Side-by-side compare of the tree's descent path with
    boardstack4's CA cascade path.  Returns:

      - agree_per_level: list of bool, one per overlapping level
      - n_agree: count of levels where they agree
      - n_compared: number of levels actually compared (min of both)
      - all_agree: True iff every compared level agrees
    """
    tp = tuple(tree_path or ())
    bp = tuple(boardstack_path or ())
    n = min(len(tp), len(bp))
    agree = [bool(tp[i] == bp[i]) for i in range(n)]
    return {
        'agree_per_level': agree,
        'n_agree':    sum(1 for a in agree if a),
        'n_compared': n,
        'all_agree':  bool(agree) and all(agree),
    }


def leaf_dispatch(descent: TreeDescent, prompt: str) -> dict | None:
    """Run the leaf's narrowed dispatch — consult only QRPairs with
    matching qrpair_label and Templates whose notes contain the
    template_tag.  Returns a reply dict or None when nothing matches.

    Tries QRPair first (byte-exact preferred), then templates."""
    if descent.leaf_node_id is None:
        return None
    from caformer.models import PICMNode, QRPair, TemplatePattern
    from django.db.models import Q
    from . import templates as _tpl

    try:
        leaf = PICMNode.objects.get(pk=descent.leaf_node_id)
    except PICMNode.DoesNotExist:
        return None

    # QRPair narrowed lookup.
    if leaf.qrpair_label:
        pair = (QRPair.objects.filter(
            prompt=prompt, label=leaf.qrpair_label).filter(
            Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True) |
            Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True) |
            Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True)).first())
        if pair is not None:
            from .agents import _cell8_dispatch as _dispatch  # reuse
            r = _dispatch(prompt)
            if r.get('reply'):
                return {
                    'reply':      r['reply'],
                    'kind':       'qrpair',
                    'label':      leaf.qrpair_label,
                    'confidence': max(0.9, leaf.confidence),
                    'detail':     r.get('sub_label', ''),
                }

    # Template narrowed lookup.
    if leaf.template_tag:
        tag = leaf.template_tag.lower()
        candidates = TemplatePattern.objects.filter(
            is_active=True,
            notes__icontains=tag,
        ).order_by('priority', '-updated_at')
        for row in candidates:
            try:
                cp = _tpl.compile_pattern(row.pattern)
            except ValueError:
                continue
            slots = _tpl.match(cp, prompt)
            if slots is None:
                continue
            return {
                'reply':      _tpl.fill(row.output, slots),
                'kind':       'template',
                'tag':        leaf.template_tag,
                'pattern':    row.pattern,
                'slots':      slots,
                'confidence': max(row.confidence, leaf.confidence * 0.9),
            }
    return None
