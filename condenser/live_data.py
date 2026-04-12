"""Extract live data from Velour's database to seed condensed apps.

When a condensed app is served via /condenser/live/<app>/, it starts
with real data from Velour instead of an empty page. The data is
baked into the HTML as a JS block that populates localStorage on
first load (only if localStorage is empty — preserves user changes).
"""

import json

from django.utils import timezone


def extract(app_label):
    """Return JS code that seeds localStorage with live Velour data."""
    extractors = {
        'tiles': _extract_tiles,
        'chronos': _extract_chronos,
        'nodes': _extract_nodes,
        'automaton': _extract_automaton,
        'identity': _extract_identity,
    }
    fn = extractors.get(app_label)
    if not fn:
        return ''
    try:
        data = fn()
    except Exception:
        return ''
    if not data:
        return ''

    lines = ['// --- Live data from Velour (seeded on first load) ---']
    for key, items in data.items():
        lines.append('if (!DB.%s.length) {' % key)
        lines.append('  DB.%s = %s;' % (key, json.dumps(items, default=str)))
        lines.append('  dbSave("%s");' % key)
        lines.append('}')
    return '\n'.join(lines)


def _extract_tiles():
    from tiles.models import TileSet, Tile
    sets = []
    for ts in TileSet.objects.all()[:20]:
        sets.append({
            'id': ts.pk, 'name': ts.name, 'slug': ts.slug,
            'tile_type': ts.tile_type, 'description': ts.description[:200],
            'palette': ts.palette, 'source': ts.source,
            'created_at': str(ts.created_at),
        })
    tiles = []
    for t in Tile.objects.all()[:100]:  # cap to keep output reasonable
        tiles.append({
            'id': t.pk, 'tileset': t.tileset_id, 'name': t.name,
            'n_color': t.n_color, 'e_color': t.e_color,
            's_color': t.s_color, 'w_color': t.w_color,
            'ne_color': t.ne_color, 'se_color': t.se_color,
            'sw_color': t.sw_color, 'nw_color': t.nw_color,
            'sort_order': t.sort_order,
        })
    return {'tileset': sets, 'tile': tiles}


def _extract_chronos():
    from chronos.models import WatchedTimezone, ClockPrefs
    tzs = []
    for tz in WatchedTimezone.objects.all().order_by('sort_order'):
        tzs.append({
            'id': tz.pk, 'label': tz.label, 'tz_name': tz.tz_name,
            'sort_order': tz.sort_order, 'color': tz.color or '',
            'notes': tz.notes or '',
        })
    prefs = []
    try:
        p = ClockPrefs.load()
        prefs.append({
            'id': p.pk, 'home_tz': p.home_tz, 'format_24h': p.format_24h,
        })
    except Exception:
        pass
    return {'watchedtimezone': tzs, 'clockprefs': prefs}


def _extract_nodes():
    from nodes.models import Node
    nodes = []
    for n in Node.objects.select_related('hardware_profile').all():
        nodes.append({
            'id': n.pk, 'nickname': n.nickname, 'slug': n.slug,
            'last_ip': n.last_ip or '',
            'firmware_version': n.firmware_version or '',
            'enabled': n.enabled,
            'last_seen_at': str(n.last_seen_at) if n.last_seen_at else '',
            'hardware_profile': n.hardware_profile.name if n.hardware_profile else '',
        })
    return {'node': nodes}


def _extract_automaton():
    from automaton.models import RuleSet, Rule, Simulation
    rulesets = []
    for rs in RuleSet.objects.all()[:10]:
        rulesets.append({
            'id': rs.pk, 'name': rs.name, 'n_colors': rs.n_colors,
            'source': rs.source, 'description': rs.description[:200],
        })
    rules = []
    for r in Rule.objects.all()[:100]:
        rules.append({
            'id': r.pk, 'ruleset': r.ruleset_id, 'priority': r.priority,
            'self_color': r.self_color, 'neighbor_color': r.neighbor_color,
            'min_count': r.min_count, 'max_count': r.max_count,
            'result_color': r.result_color, 'notes': r.notes,
        })
    return {'ruleset': rulesets, 'rule': rules}


def _extract_identity():
    from identity.models import Identity, Tick, Concern
    now = timezone.now()
    identity = Identity.get_self()
    ticks = []
    for t in Tick.objects.all()[:20]:
        ticks.append({
            'id': t.pk, 'mood': t.mood, 'mood_intensity': t.mood_intensity,
            'thought': (t.thought or '')[:200],
            'at': str(t.at),
        })
    concerns = []
    for c in Concern.objects.filter(closed_at=None)[:10]:
        concerns.append({
            'id': c.pk, 'aspect': c.aspect, 'trigger': c.trigger,
        })
    ident = [{
        'id': 1, 'name': identity.name, 'mood': identity.mood,
        'mood_intensity': identity.mood_intensity,
        'tagline': identity.tagline,
    }]
    return {'identity': ident, 'tick': ticks, 'concern': concerns}
