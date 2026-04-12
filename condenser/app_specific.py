"""App-specific rendering logic for the Condenser.

The generic CRUD generator produces the skeleton — list, add, delete.
This module adds the SOUL — the app-specific rendering that makes
each app unique. For Tiles, that's the SVG/canvas Wang tile renderer.
For Automaton, it's the hex grid animator. For Chronos, it's the
clock display.

Each app-specific renderer is a function that takes an AppIR and
returns additional JS code to inject into the condensed output.

The Wang tile insight applies here: each renderer is a "tile" that
connects the generic CRUD output (north edge) to the visual display
(south edge). If we have renderers for every app, the condensation
is complete.
"""


def get_app_renderer(app_name):
    """Return the app-specific renderer JS, or empty string."""
    renderers = {
        'tiles': _tiles_renderer,
        'automaton': _automaton_renderer,
        'chronos': _chronos_renderer,
        'nodes': _nodes_renderer,
    }
    fn = renderers.get(app_name)
    return fn() if fn else ''


def _tiles_renderer():
    """Wang tile SVG preview + canvas tiling for the Tiles app."""
    return '''
// --- App-specific: Tiles renderer ---
function renderTileSVG(tile, type, size) {
    size = size || 24;
    if (type === 'hex') {
        return '<svg width="' + size + '" height="' + Math.round(size*0.87) + '" viewBox="0 0 100 87">' +
            '<polygon points="25,0 75,0 50,43.5" fill="' + tile[0] + '"/>' +
            '<polygon points="75,0 100,43.5 50,43.5" fill="' + tile[1] + '"/>' +
            '<polygon points="100,43.5 75,87 50,43.5" fill="' + tile[2] + '"/>' +
            '<polygon points="75,87 25,87 50,43.5" fill="' + tile[3] + '"/>' +
            '<polygon points="25,87 0,43.5 50,43.5" fill="' + tile[4] + '"/>' +
            '<polygon points="0,43.5 25,0 50,43.5" fill="' + tile[5] + '"/></svg>';
    }
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 56 56">' +
        '<polygon points="0,0 56,0 28,28" fill="' + tile[0] + '"/>' +
        '<polygon points="56,0 56,56 28,28" fill="' + tile[1] + '"/>' +
        '<polygon points="56,56 0,56 28,28" fill="' + tile[2] + '"/>' +
        '<polygon points="0,56 0,0 28,28" fill="' + tile[3] + '"/></svg>';
}

// Override the tile list view to show SVG previews
var _orig_view_list_tile = typeof view_list_tile === 'function' ? view_list_tile : null;
if (_orig_view_list_tile) {
    view_list_tile = function() {
        _orig_view_list_tile();
        var el = document.getElementById('app');
        var items = list_tile();
        if (items.length) {
            var h = '<div style="display:flex;gap:2px;flex-wrap:wrap;margin:0.5rem 0">';
            var type = 'square';
            // Check if any tileset is hex
            var sets = list_tileset();
            if (sets.length && sets[0].tile_type === 'hex') type = 'hex';
            items.slice(0, 80).forEach(function(t) {
                var edges = type === 'hex' ?
                    [t.n_color, t.ne_color, t.se_color, t.s_color, t.sw_color, t.nw_color] :
                    [t.n_color, t.e_color, t.s_color, t.w_color];
                h += renderTileSVG(edges, type, 20);
            });
            h += '</div>';
            el.innerHTML += h;
        }
    };
}
'''


def _automaton_renderer():
    """Hex grid cellular automaton canvas for the Automaton app."""
    return '''
// --- App-specific: Automaton hex grid ---
function runAutomaton(sim) {
    if (!sim || !sim.grid_state || !sim.palette) return;
    var grid = sim.grid_state;
    var palette = sim.palette;
    var W = sim.width || 32, H = sim.height || 32;
    var PX = Math.max(6, Math.min(16, Math.floor(600 / W)));
    var sz = PX / 2, hh = Math.sqrt(3) * sz;

    var el = document.getElementById('app');
    el.innerHTML += '<h2>Simulation</h2>' +
        '<canvas id="sim-cv" style="border:1px solid #30363d"></canvas>' +
        '<div style="margin:0.3rem 0"><button onclick="simStep()">Step</button> ' +
        '<span id="sim-tick" style="color:#8b949e;font-size:0.72rem">tick 0</span></div>';

    var cv = document.getElementById('sim-cv');
    cv.width = Math.ceil(W * sz * 2 * 0.75 + sz * 0.5);
    cv.height = Math.ceil(H * hh + hh / 2 + 1);
    var ctx = cv.getContext('2d');
    var tick = 0;

    function draw() {
        ctx.fillStyle = '#0d1117';
        ctx.fillRect(0, 0, cv.width, cv.height);
        for (var r = 0; r < H; r++) for (var c = 0; c < W; c++) {
            var color = palette[grid[r][c]] || '#333';
            var cx = c * sz * 2 * 0.75 + sz;
            var cy = r * hh + hh / 2 + (c % 2 === 1 ? hh / 2 : 0);
            ctx.fillStyle = color;
            ctx.beginPath();
            for (var i = 0; i < 6; i++) {
                var a = Math.PI / 3 * i;
                var px = cx + sz * Math.cos(a), py = cy + sz * Math.sin(a);
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
            }
            ctx.closePath(); ctx.fill();
        }
    }

    window.simStep = function() {
        // Simple rule: count alive (non-0) neighbors
        var next = [];
        for (var r = 0; r < H; r++) { next[r] = [];
            for (var c = 0; c < W; c++) {
                var alive = 0, self = grid[r][c];
                // Count non-zero neighbors
                var even = c % 2 === 0;
                var nbs = [[r-1,c],[r+1,c],
                    [even?r-1:r,c+1],[even?r:r+1,c+1],
                    [even?r:r+1,c-1],[even?r-1:r,c-1]];
                nbs.forEach(function(nb) {
                    if (nb[0]>=0 && nb[0]<H && nb[1]>=0 && nb[1]<W && grid[nb[0]][nb[1]] > 0) alive++;
                });
                if (self === 0 && alive === 2) next[r][c] = 1 + (tick % 3);
                else if (self > 0 && (alive < 2 || alive > 3)) next[r][c] = 0;
                else next[r][c] = self;
            }
        }
        grid = next; tick++;
        document.getElementById('sim-tick').textContent = 'tick ' + tick;
        draw();
    };
    draw();
}
'''


def _chronos_renderer():
    """Live clock display for the Chronos app."""
    return '''
// --- App-specific: Chronos live clocks ---
// Override the WatchedTimezone list view to show live clocks
var _orig_wt_list = typeof view_list_watchedtimezone === 'function' ? view_list_watchedtimezone : null;
if (_orig_wt_list) {
    view_list_watchedtimezone = function(q) {
        var items = list_watchedtimezone();
        if (q) items = items.filter(function(x) {
            return JSON.stringify(x).toLowerCase().indexOf(q.toLowerCase()) >= 0;
        });
        items.sort(function(a,b) { return (a.sort_order||0) - (b.sort_order||0); });
        var h = '<h2>World Clocks (' + items.length + ')</h2>';
        h += '<div style="display:flex;gap:0.3rem;margin:0.3rem 0">';
        h += '<input type="text" placeholder="search..." onkeyup="view_list_watchedtimezone(this.value)" style="width:10rem">';
        h += '<button class="primary" onclick="view_add_watchedtimezone()">Add</button></div>';
        h += '<div id="clocks" style="display:flex;flex-wrap:wrap;gap:0.3rem;margin:0.5rem 0"></div>';
        document.getElementById('app').innerHTML = h;

        function updateClocks() {
            var ch = '';
            items.forEach(function(tz) {
                try {
                    var t = new Date().toLocaleTimeString('en-GB', {
                        timeZone: tz.tz_name, hour:'2-digit', minute:'2-digit', second:'2-digit'
                    });
                    var d = new Date().toLocaleDateString('en-GB', {
                        timeZone: tz.tz_name, weekday:'short', day:'numeric', month:'short'
                    });
                    var style = tz.color ? 'color:' + tz.color : 'color:#c9d1d9';
                    ch += '<div style="background:#161b22;border-left:2px solid ' +
                        (tz.color || '#30363d') + ';border-radius:0 4px 4px 0;padding:0.25rem 0.5rem;min-width:120px">' +
                        '<div style="font-size:0.72rem;font-weight:500;' + style + '">' + tz.label + '</div>' +
                        '<div style="font-size:1rem;font-family:monospace;' + style + '">' + t + '</div>' +
                        '<div style="font-size:0.62rem;color:#6e7681">' + d + '</div>' +
                        '<div style="font-size:0.58rem;color:#484f58">' + tz.tz_name + '</div></div>';
                } catch(e) {}
            });
            var el = document.getElementById('clocks');
            if (el) el.innerHTML = ch;
        }
        updateClocks();
        if (window._clockInterval) clearInterval(window._clockInterval);
        window._clockInterval = setInterval(updateClocks, 1000);
    };
}
'''


def _nodes_renderer():
    """Fleet status display for the Nodes app."""
    return '''
// --- App-specific: Fleet status ---
var _orig_node_list = typeof view_list_node === 'function' ? view_list_node : null;
if (_orig_node_list) {
    view_list_node = function(q) {
        var items = list_node();
        if (q) items = items.filter(function(x) {
            return JSON.stringify(x).toLowerCase().indexOf(q.toLowerCase()) >= 0;
        });
        var h = '<h2>Fleet (' + items.length + ' nodes)</h2>';
        h += '<div style="display:flex;gap:0.3rem;margin:0.3rem 0">';
        h += '<input type="text" placeholder="search..." onkeyup="view_list_node(this.value)" style="width:10rem">';
        h += '<button class="primary" onclick="view_add_node()">Add</button></div>';
        h += '<div style="display:flex;flex-direction:column;gap:2px">';
        items.forEach(function(n) {
            var age = n.last_seen_at ? 'seen ' + n.last_seen_at.substring(11, 16) : 'never';
            h += '<div style="background:#161b22;border-left:3px solid ' +
                (n.enabled ? '#2ea043' : '#f85149') +
                ';border-radius:0 3px 3px 0;padding:0.3rem 0.5rem;display:flex;gap:0.5rem;align-items:center;font-size:0.78rem">';
            h += '<b style="color:#c9d1d9;min-width:4rem">' + n.nickname + '</b>';
            h += '<span style="color:#6e7681;font-family:monospace;font-size:0.7rem">' + n.slug + '</span>';
            if (n.last_ip) h += '<span style="color:#6e7681;font-family:monospace;font-size:0.7rem">' + n.last_ip + '</span>';
            if (n.firmware_version) h += '<span style="color:#6e7681;font-family:monospace;font-size:0.65rem">' + n.firmware_version + '</span>';
            if (n.hardware_profile) h += '<span style="background:rgba(88,166,255,0.12);color:#58a6ff;font-size:0.62rem;padding:0.1rem 0.3rem;border-radius:8px">' + n.hardware_profile + '</span>';
            h += '<span style="color:#8b949e;font-size:0.68rem;margin-left:auto">' + age + '</span>';
            h += '</div>';
        });
        h += '</div>';
        document.getElementById('app').innerHTML = h;
    };
}
'''
