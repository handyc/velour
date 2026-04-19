"""Save/load helpers for named Room layout snapshots.

A Layout captures the (x, y, rotation) of every Placement at a moment in
time. Applying a Layout writes those positions back. The GA and the
"evolve" endpoint use `save_auto_snapshot()` to preserve the pre-evolve
state so an evolve is recoverable.
"""
from __future__ import annotations

from typing import List, Optional

from .fitness import score_room
from .models import Layout, Placement, Room


MAX_AUTO_SNAPSHOTS = 5


def _snapshot_from_room(room: Room) -> List[dict]:
    return [
        {
            'placement_id': p.id,
            'x_cm':         p.x_cm,
            'y_cm':         p.y_cm,
            'rotation_deg': p.rotation_deg,
        }
        for p in room.placements.all()
    ]


def save_layout(room: Room, name: str, *, auto: bool = False) -> Layout:
    """Create a Layout row capturing the room's current placements.
    When auto=True, old auto snapshots are trimmed to MAX_AUTO_SNAPSHOTS
    so we don't accumulate one-per-evolve forever."""
    score = score_room(room)
    layout = Layout.objects.create(
        room=room,
        name=name[:120],
        snapshot=_snapshot_from_room(room),
        is_auto=auto,
        score_total=score.get('total'),
    )
    if auto:
        extras = list(
            Layout.objects
            .filter(room=room, is_auto=True)
            .order_by('-created_at')[MAX_AUTO_SNAPSHOTS:]
        )
        for old in extras:
            old.delete()
    return layout


def save_auto_snapshot(room: Room, label_prefix: str = 'before evolve') -> Layout:
    from django.utils import timezone as djtz
    stamp = djtz.localtime().strftime('%Y-%m-%d %H:%M:%S')
    return save_layout(room, f'{label_prefix} {stamp}', auto=True)


def load_layout(layout: Layout) -> List[dict]:
    """Apply the snapshot's positions back onto Placement rows that still
    exist. Returns the list of updates the UI should patch in place."""
    by_id = {
        entry['placement_id']: entry
        for entry in (layout.snapshot or [])
        if 'placement_id' in entry
    }
    touched: List[dict] = []
    placements = Placement.objects.filter(
        room=layout.room, id__in=by_id.keys(),
    ).select_related('piece')
    for p in placements:
        e = by_id[p.id]
        p.x_cm = int(e.get('x_cm', p.x_cm))
        p.y_cm = int(e.get('y_cm', p.y_cm))
        p.rotation_deg = int(e.get('rotation_deg', p.rotation_deg)) % 360
        # Clamp to room in case the room was resized after the snapshot.
        w, h = p.footprint_cm
        p.x_cm = max(0, min(p.x_cm, layout.room.width_cm - w))
        p.y_cm = max(0, min(p.y_cm, layout.room.length_cm - h))
        p.save(update_fields=['x_cm', 'y_cm', 'rotation_deg'])
        fw, fh = p.footprint_cm
        touched.append({
            'id':    p.id,
            'x':     p.x_cm,
            'y':     p.y_cm,
            'rot':   p.rotation_deg,
            'w':     fw,
            'h':     fh,
            'label': p.label or p.piece.name,
        })
    return touched


def list_layouts(room: Room, include_auto: bool = True) -> List[dict]:
    qs = room.layouts.all()
    if not include_auto:
        qs = qs.filter(is_auto=False)
    return [
        {
            'id':          lay.id,
            'name':        lay.name,
            'is_auto':     lay.is_auto,
            'score_total': lay.score_total,
            'created_at':  lay.created_at.isoformat(),
            'size':        len(lay.snapshot or []),
        }
        for lay in qs
    ]
