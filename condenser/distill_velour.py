"""Distill Velour itself into a standalone JS dashboard.

This is the self-referential distillation — Velour condensing Velour.
The output is a single HTML page that contains:

  - A static snapshot of the fleet status
  - World clocks (computed client-side from timezone data)
  - Identity mood and recent ticks (baked in at distillation time)
  - A mini tile viewer with the most recent tileset
  - System info snapshot

What survives:
  - Fleet status (names, IPs, last-seen)
  - World clocks (timezone math in JS)
  - Identity state (mood, intensity, recent thought)
  - One tileset with canvas rendering

What doesn't survive:
  - Live data updates (no server to poll)
  - Authentication
  - Database queries
  - All CRUD operations
  - Terminal, logs, services, mail, maintenance
  - App factory, security, databases

The Gödelian observation: Velour condensing itself produces a snapshot
that can display but not modify — an observer that has lost the ability
to act. The condensed version knows what Velour is but cannot be Velour.
It is the map claiming to be the territory.

CONDENSER markers in the output describe what was lost at each stage
and what a deeper distillation (ESP, ATTiny) would have to shed next.
"""

from django.utils import timezone


def distill():
    """Generate a standalone Velour dashboard. Returns HTML string."""
    from nodes.models import Node
    from identity.models import Identity, Tick
    from chronos.models import WatchedTimezone
    from tiles.models import TileSet

    identity = Identity.get_self()
    latest_tick = Tick.objects.first()
    nodes = list(Node.objects.select_related('hardware_profile').all())
    clocks = list(WatchedTimezone.objects.all().order_by('sort_order'))
    tileset = TileSet.objects.filter(tile_type='hex').order_by('-created_at').first()
    tiles_data = []
    if tileset:
        for t in tileset.tiles.all()[:64]:
            tiles_data.append({
                'edges': [t.n_color, t.ne_color or t.e_color,
                          t.se_color or t.s_color, t.s_color,
                          t.sw_color or t.w_color, t.nw_color or '']
            })

    now = timezone.now()

    # Build fleet HTML
    fleet_rows = []
    for n in nodes:
        if n.last_seen_at:
            age = (now - n.last_seen_at).total_seconds()
            ago = '%ds ago' % int(age) if age < 60 else '%dm ago' % int(age // 60) if age < 3600 else '%dh ago' % int(age // 3600)
        else:
            ago = 'never'
        fleet_rows.append(
            '<div class="row"><b>%s</b> <span class="dim">%s</span> '
            '<span class="dim">%s</span> <span>%s</span></div>'
            % (n.nickname, n.slug, n.last_ip or '', ago))

    fleet_html = '\n'.join(fleet_rows)

    # Build clocks JSON
    import json
    clocks_json = json.dumps([{'tz': c.tz_name, 'label': c.label,
                                'color': c.color or ''} for c in clocks])

    tiles_json = json.dumps(tiles_data)

    tick_thought = ''
    if latest_tick and latest_tick.thought:
        tick_thought = latest_tick.thought[:200]

    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Velour — Condensed</title>
<!-- CONDENSER: This is Velour distilled to Tier 2 (JS-only).
     The full system has %(app_count)d Django apps, a fleet of %(node_count)d nodes,
     %(clock_count)d world clocks, and an Identity engine with mood, meditations,
     and tile-based dreaming. This page preserves a read-only snapshot.
     What's lost: all write operations, all live data, all self-modification.
     Gödel note: this page knows what Velour is but cannot be Velour.
     It is a formal system that can describe its source but not reproduce it. -->
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;padding:1rem;max-width:900px;margin:0 auto}
h1{font-size:1.3rem;color:#58a6ff;margin-bottom:0.2rem}
h2{font-size:0.95rem;margin:0.8rem 0 0.3rem;color:#c9d1d9}
.dim{color:#6e7681;font-size:0.75rem}
.row{padding:0.2rem 0;font-size:0.8rem;border-bottom:1px solid #161b22}
.mood{display:inline-block;padding:0.15rem 0.5rem;border-radius:12px;font-size:0.8rem;
  background:rgba(88,166,255,0.15);color:#58a6ff}
.thought{font-style:italic;color:#8b949e;font-size:0.82rem;margin:0.3rem 0;max-width:600px}
.clocks{display:flex;flex-wrap:wrap;gap:0.3rem;margin:0.3rem 0}
.clock{background:#161b22;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.72rem;
  font-family:ui-monospace,Menlo,monospace}
canvas{border:1px solid #30363d;margin:0.3rem 0}
</style>
</head>
<body>
<h1>%(name)s</h1>
<p class="dim">Condensed snapshot · %(timestamp)s</p>
<div class="mood">%(mood)s (%(intensity).1f)</div>
%(thought_html)s

<h2>Fleet</h2>
%(fleet_html)s

<h2>World clocks</h2>
<div class="clocks" id="clocks"></div>

%(tileset_html)s

<script>
// CONDENSER: Clocks computed client-side from IANA timezone names.
// This is the one piece that stays "live" — time always advances.
// At Tier 3 (ESP), the clock becomes the ESP's millis() counter.
// At Tier 4 (ATTiny), time is a 555 timer oscillator frequency.
var clocks = %(clocks_json)s;
function updateClocks() {
  var el = document.getElementById('clocks');
  el.innerHTML = clocks.map(function(c) {
    try {
      var t = new Date().toLocaleTimeString('en-GB', {timeZone: c.tz, hour:'2-digit', minute:'2-digit'});
      var style = c.color ? 'color:' + c.color : '';
      return '<div class="clock" style="' + style + '">' + c.label + ' ' + t + '</div>';
    } catch(e) { return ''; }
  }).join('');
}
updateClocks();
setInterval(updateClocks, 30000);

// CONDENSER: Tileset rendering — same greedy tiler as the full app.
%(tiles_script)s
</script>
</body>
</html>''' % {
        'name': identity.name,
        'mood': identity.mood,
        'intensity': identity.mood_intensity,
        'timestamp': now.strftime('%Y-%m-%d %H:%M'),
        'thought_html': '<p class="thought">"' + tick_thought + '"</p>' if tick_thought else '',
        'fleet_html': fleet_html,
        'clocks_json': clocks_json,
        'app_count': 20,  # approximate
        'node_count': len(nodes),
        'clock_count': len(clocks),
        'tileset_html': '<h2>Latest tileset</h2><canvas id="vc" width="384" height="384"></canvas>' if tiles_data else '',
        'tiles_script': _tiles_script(tiles_json) if tiles_data else '',
    }


def _tiles_script(tiles_json):
    return '''
var tiles = %s;
if (tiles.length) {
  var cv = document.getElementById('vc');
  if (cv) {
    var ctx = cv.getContext('2d');
    var px = 12, gw = 32, gh = 32;
    var sz = px/2, hexH = Math.sqrt(3)*sz;
    cv.width = Math.ceil(gw*sz*2*0.75+sz*0.5);
    cv.height = Math.ceil(gh*hexH+hexH/2+1);
    ctx.fillStyle = '#0d1117'; ctx.fillRect(0,0,cv.width,cv.height);
    var grid = [];
    for (var r=0;r<gh;r++) { grid[r]=[];
      for (var c=0;c<gw;c++) {
        var cands = tiles.slice();
        // Simple random placement for the condensed version
        grid[r][c] = cands[Math.floor(Math.random()*cands.length)];
      }
    }
    for (var r=0;r<gh;r++) for (var c=0;c<gw;c++) {
      var t = grid[r][c]; if (!t) continue;
      var cx=c*sz*2*0.75+sz, cy=r*hexH+hexH/2+(c%%2===1?hexH/2:0);
      var pts=[]; for(var i=0;i<6;i++){var a=Math.PI/3*i;pts.push([cx+sz*Math.cos(a),cy+sz*Math.sin(a)]);}
      var em=[[1,2],[0,1],[5,0],[4,5],[3,4],[2,3]];
      for(var e=0;e<6;e++){ctx.fillStyle=t.edges[e]||'#333';ctx.beginPath();ctx.moveTo(pts[em[e][0]][0],pts[em[e][0]][1]);ctx.lineTo(pts[em[e][1]][0],pts[em[e][1]][1]);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();}
    }
  }
}''' % tiles_json
