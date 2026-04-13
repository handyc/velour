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
    """Full Wang tile renderer: SVG previews + canvas greedy tiling."""
    return '''
// --- App-specific: Tiles — full renderer with greedy tiling ---

function tileSVG(e, type, sz) {
    sz = sz || 20;
    if (type === 'hex') {
        return '<svg width="'+sz+'" height="'+Math.round(sz*0.87)+'" viewBox="0 0 100 87">' +
            '<polygon points="25,0 75,0 50,43.5" fill="'+e[0]+'"/>' +
            '<polygon points="75,0 100,43.5 50,43.5" fill="'+e[1]+'"/>' +
            '<polygon points="100,43.5 75,87 50,43.5" fill="'+e[2]+'"/>' +
            '<polygon points="75,87 25,87 50,43.5" fill="'+e[3]+'"/>' +
            '<polygon points="25,87 0,43.5 50,43.5" fill="'+e[4]+'"/>' +
            '<polygon points="0,43.5 25,0 50,43.5" fill="'+e[5]+'"/></svg>';
    }
    return '<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 56 56">' +
        '<polygon points="0,0 56,0 28,28" fill="'+e[0]+'"/>' +
        '<polygon points="56,0 56,56 28,28" fill="'+e[1]+'"/>' +
        '<polygon points="56,56 0,56 28,28" fill="'+e[2]+'"/>' +
        '<polygon points="0,56 0,0 28,28" fill="'+e[3]+'"/></svg>';
}

function getEdges(t, type) {
    if (type === 'hex') return [t.n_color,t.ne_color,t.se_color,t.s_color,t.sw_color,t.nw_color];
    return [t.n_color, t.e_color, t.s_color, t.w_color];
}

// Override tileset list: show SVG previews per set
var _orig_ts_list = typeof view_list_tileset === 'function' ? view_list_tileset : null;
if (_orig_ts_list) {
    view_list_tileset = function(q) {
        var sets = list_tileset();
        if (q) sets = sets.filter(function(x) {
            return JSON.stringify(x).toLowerCase().indexOf(q.toLowerCase()) >= 0;
        });
        var allTiles = list_tile();
        var h = '<h2>Tilesets (' + sets.length + ')</h2>';
        h += '<div style="display:flex;gap:0.3rem;margin:0.3rem 0">';
        h += '<input type="text" placeholder="search..." onkeyup="view_list_tileset(this.value)" style="width:10rem">';
        h += '<button class="primary" onclick="view_add_tileset()">Add</button></div>';
        h += '<div style="display:flex;flex-direction:column;gap:0.4rem">';
        sets.forEach(function(s) {
            var myTiles = allTiles.filter(function(t) { return t.tileset == s.id; });
            h += '<div style="background:#161b22;border-left:2px solid #bc8cff;border-radius:0 4px 4px 0;padding:0.4rem 0.6rem;cursor:pointer" onclick="viewTileset('+s.id+')">';
            h += '<div style="display:flex;justify-content:space-between;align-items:center">';
            h += '<b style="color:#c9d1d9;font-size:0.85rem">' + s.name + '</b>';
            h += '<span style="color:#6e7681;font-size:0.68rem">' + s.tile_type + ' · ' + myTiles.length + ' tiles</span></div>';
            if (myTiles.length) {
                h += '<div style="display:flex;gap:1px;flex-wrap:wrap;margin-top:0.3rem;max-height:40px;overflow:hidden">';
                myTiles.slice(0, 30).forEach(function(t) {
                    h += tileSVG(getEdges(t, s.tile_type), s.tile_type, 14);
                });
                h += '</div>';
            }
            h += '</div>';
        });
        h += '</div>';
        document.getElementById('app').innerHTML = h;
    };
}

// Tileset detail view with greedy tiling on canvas
window.viewTileset = function(setId) {
    var sets = list_tileset();
    var s = sets.find(function(x) { return x.id == setId; });
    if (!s) return;
    var allTiles = list_tile().filter(function(t) { return t.tileset == setId; });
    var isHex = s.tile_type === 'hex';
    var ne = isHex ? 6 : 4;
    var opp = isHex ? [3,4,5,0,1,2] : [2,3,0,1];

    var h = '<h2>' + s.name + '</h2>';
    h += '<p class="dim">' + s.tile_type + ' · ' + allTiles.length + ' tiles</p>';
    h += '<div style="display:flex;gap:1px;flex-wrap:wrap;margin:0.4rem 0">';
    allTiles.slice(0, 80).forEach(function(t) {
        h += tileSVG(getEdges(t, s.tile_type), s.tile_type, 22);
    });
    h += '</div>';
    h += '<div style="display:flex;gap:0.3rem;margin:0.4rem 0;align-items:center">';
    h += '<label style="font-size:0.72rem;color:#8b949e">W <input type="number" id="tw" value="20" min="4" max="48" style="width:3rem"></label>';
    h += '<label style="font-size:0.72rem;color:#8b949e">H <input type="number" id="th" value="20" min="4" max="48" style="width:3rem"></label>';
    h += '<button class="primary" onclick="doTiling('+setId+')">Generate tiling</button>';
    h += '<button onclick="view_list_tileset()">Back</button></div>';
    h += '<canvas id="tcv" style="border:1px solid #30363d;image-rendering:pixelated"></canvas>';
    h += '<div id="tstatus" class="dim"></div>';
    document.getElementById('app').innerHTML = h;
};

// Greedy Wang tiling on canvas
window.doTiling = function(setId) {
    var sets = list_tileset();
    var s = sets.find(function(x) { return x.id == setId; });
    if (!s) return;
    var tiles = list_tile().filter(function(t) { return t.tileset == setId; })
        .map(function(t) { return getEdges(t, s.tile_type); });
    if (!tiles.length) return;
    var isHex = s.tile_type === 'hex';
    var gw = parseInt(document.getElementById('tw').value) || 20;
    var gh = parseInt(document.getElementById('th').value) || 20;
    var px = 14;
    var opp = isHex ? [3,4,5,0,1,2] : [2,3,0,1];
    var cv = document.getElementById('tcv');
    var ctx = cv.getContext('2d');

    function hexNb(r,c,d) {
        var e = c%2===0;
        switch(d) {
            case 0: return [r-1,c]; case 3: return [r+1,c];
            case 1: return e?[r-1,c+1]:[r,c+1]; case 2: return e?[r,c+1]:[r+1,c+1];
            case 4: return e?[r,c-1]:[r+1,c-1]; case 5: return e?[r-1,c-1]:[r,c-1];
        }
    }

    if (isHex) {
        var sz=px/2, hh=Math.sqrt(3)*sz;
        cv.width=Math.ceil(gw*sz*2*0.75+sz*0.5);
        cv.height=Math.ceil(gh*hh+hh/2+1);
    } else { cv.width=gw*px; cv.height=gh*px; }
    ctx.fillStyle='#0d1117'; ctx.fillRect(0,0,cv.width,cv.height);

    var grid=[], filled=0, stuck=0;
    for (var r=0;r<gh;r++) { grid[r]=[];
        for (var c=0;c<gw;c++) {
            var cands=tiles.slice();
            if (isHex) {
                for (var d=0;d<6;d++) {
                    var nb=hexNb(r,c,d);
                    if(nb&&nb[0]>=0&&nb[0]<gh&&nb[1]>=0&&nb[1]<gw&&grid[nb[0]]&&grid[nb[0]][nb[1]]) {
                        var need=grid[nb[0]][nb[1]][opp[d]];
                        cands=cands.filter(function(t){return t[d]===need;});
                    }
                }
            } else {
                if(c>0&&grid[r][c-1]) cands=cands.filter(function(t){return t[3]===grid[r][c-1][1];});
                if(r>0&&grid[r-1][c]) cands=cands.filter(function(t){return t[0]===grid[r-1][c][2];});
            }
            if(!cands.length){grid[r][c]=null;stuck++;}
            else{grid[r][c]=cands[Math.floor(Math.random()*cands.length)];filled++;}
        }
    }

    if (isHex) {
        var sz=px/2, hh=Math.sqrt(3)*sz;
        var em=[[1,2],[0,1],[5,0],[4,5],[3,4],[2,3]];
        for(var r=0;r<gh;r++) for(var c=0;c<gw;c++) {
            var t=grid[r][c]; if(!t) continue;
            var cx=c*sz*2*0.75+sz, cy=r*hh+hh/2+(c%2===1?hh/2:0);
            var pts=[]; for(var i=0;i<6;i++){var a=Math.PI/3*i;pts.push([cx+sz*Math.cos(a),cy+sz*Math.sin(a)]);}
            for(var e=0;e<6;e++){ctx.fillStyle=t[e];ctx.beginPath();ctx.moveTo(pts[em[e][0]][0],pts[em[e][0]][1]);ctx.lineTo(pts[em[e][1]][0],pts[em[e][1]][1]);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();}
        }
    } else {
        var half=px/2;
        for(var r=0;r<gh;r++) for(var c=0;c<gw;c++) {
            var t=grid[r][c]; if(!t) continue;
            var x=c*px,y=r*px,cx=x+half,cy=y+half;
            ctx.fillStyle=t[0];ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+px,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
            ctx.fillStyle=t[1];ctx.beginPath();ctx.moveTo(x+px,y);ctx.lineTo(x+px,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
            ctx.fillStyle=t[2];ctx.beginPath();ctx.moveTo(x+px,y+px);ctx.lineTo(x,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
            ctx.fillStyle=t[3];ctx.beginPath();ctx.moveTo(x,y+px);ctx.lineTo(x,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
        }
    }
    document.getElementById('tstatus').textContent = gw+'x'+gh+' = '+(gw*gh)+' cells. '+filled+' filled, '+stuck+' stuck.';
};
'''


def _automaton_renderer():
    """Full hex cellular automaton with rule-based evolution."""
    return '''
// --- App-specific: Automaton — hex cellular automaton with rules ---

// Override ruleset list to show rules inline
var _orig_rs_list = typeof view_list_ruleset === 'function' ? view_list_ruleset : null;
if (_orig_rs_list) {
    view_list_ruleset = function(q) {
        var sets = list_ruleset();
        var allRules = typeof list_rule === 'function' ? list_rule() : [];
        if (q) sets = sets.filter(function(x) {
            return JSON.stringify(x).toLowerCase().indexOf(q.toLowerCase()) >= 0;
        });
        var h = '<h2>Rulesets (' + sets.length + ')</h2>';
        h += '<div style="display:flex;gap:0.3rem;margin:0.3rem 0">';
        h += '<input type="text" placeholder="search..." onkeyup="view_list_ruleset(this.value)" style="width:10rem">';
        h += '<button class="primary" onclick="view_add_ruleset()">Add</button>';
        h += '<button onclick="autoGenRules()">Auto-generate Life rules</button></div>';
        sets.forEach(function(rs) {
            var rules = allRules.filter(function(r) { return r.ruleset == rs.id; });
            h += '<div style="background:#161b22;border-left:2px solid #2ea043;border-radius:0 4px 4px 0;padding:0.4rem 0.6rem;margin:0.3rem 0">';
            h += '<div style="display:flex;justify-content:space-between">';
            h += '<b style="color:#c9d1d9">' + rs.name + '</b>';
            h += '<span class="dim">' + rs.n_colors + ' colors · ' + rules.length + ' rules</span></div>';
            h += '<div style="margin-top:0.2rem;font-size:0.7rem;color:#8b949e;font-family:monospace">';
            rules.slice(0,6).forEach(function(r) {
                var sc = r.self_color >= 0 ? 'c'+r.self_color : '*';
                h += sc + ' + ' + r.min_count + '-' + r.max_count + '×c' + r.neighbor_color + ' → c' + r.result_color + '<br>';
            });
            if (rules.length > 6) h += '... +' + (rules.length-6) + ' more';
            h += '</div>';
            h += '<button style="margin-top:0.3rem" onclick="runSim('+rs.id+')">Run simulation</button>';
            h += '</div>';
        });
        document.getElementById('app').innerHTML = h;
    };
}

// Auto-generate Conway-style 4-color hex rules
window.autoGenRules = function() {
    var rs = {name: 'Hex Life ' + Math.floor(Math.random()*900+100), n_colors: 4,
              source: 'operator', description: '4-color Conway-style hex rules'};
    rs = create_ruleset(rs);
    var rules = [
        {ruleset:rs.id, priority:1, self_color:0, neighbor_color:1, min_count:2, max_count:2, result_color:1, notes:'birth c1'},
        {ruleset:rs.id, priority:2, self_color:0, neighbor_color:2, min_count:2, max_count:2, result_color:2, notes:'birth c2'},
        {ruleset:rs.id, priority:3, self_color:0, neighbor_color:3, min_count:2, max_count:2, result_color:3, notes:'birth c3'},
        {ruleset:rs.id, priority:10, self_color:1, neighbor_color:1, min_count:2, max_count:3, result_color:1, notes:'survive c1'},
        {ruleset:rs.id, priority:11, self_color:2, neighbor_color:2, min_count:2, max_count:3, result_color:2, notes:'survive c2'},
        {ruleset:rs.id, priority:12, self_color:3, neighbor_color:3, min_count:2, max_count:3, result_color:3, notes:'survive c3'},
        {ruleset:rs.id, priority:20, self_color:1, neighbor_color:2, min_count:3, max_count:6, result_color:2, notes:'convert c1→c2'},
        {ruleset:rs.id, priority:21, self_color:2, neighbor_color:3, min_count:3, max_count:6, result_color:3, notes:'convert c2→c3'},
        {ruleset:rs.id, priority:22, self_color:3, neighbor_color:1, min_count:3, max_count:6, result_color:1, notes:'convert c3→c1'},
        {ruleset:rs.id, priority:90, self_color:-1, neighbor_color:0, min_count:5, max_count:6, result_color:0, notes:'isolation death'},
    ];
    rules.forEach(function(r) { create_rule(r); });
    view_list_ruleset();
};

// Run a simulation from a ruleset
window.runSim = function(rsId) {
    var allRules = typeof list_rule === 'function' ? list_rule() : [];
    var rules = allRules.filter(function(r) { return r.ruleset == rsId; })
        .sort(function(a,b) { return (a.priority||0) - (b.priority||0); });
    var rs = list_ruleset().find(function(x) { return x.id == rsId; });
    var NC = rs ? rs.n_colors || 4 : 4;
    var W = 32, H = 32, PX = 10;
    var palette = ['#0d1117','#58a6ff','#f85149','#2ea043'];
    var grid = [];
    for (var r=0;r<H;r++) { grid[r]=[]; for(var c=0;c<W;c++) grid[r][c]=Math.floor(Math.random()*NC); }

    var sz=PX/2, hh=Math.sqrt(3)*sz;
    var h = '<h2>Simulation: ' + (rs?rs.name:'') + '</h2>';
    h += '<div style="display:flex;gap:0.4rem;margin:0.3rem 0;align-items:center">';
    h += '<button id="abtn" onclick="aToggle()">▶ Play</button>';
    h += '<button onclick="aStep()">Step</button>';
    h += '<button onclick="aRandom()">Randomize</button>';
    h += '<input type="range" id="aspeed" min="1" max="30" value="8" style="width:80px">';
    h += '<span class="dim" id="atick">tick 0</span>';
    h += '<span class="dim" id="apop"></span>';
    h += '<button onclick="view_list_ruleset()" style="margin-left:auto">Back</button></div>';
    h += '<canvas id="acv" style="border:1px solid #30363d"></canvas>';
    document.getElementById('app').innerHTML = h;

    var cv=document.getElementById('acv'), ctx=cv.getContext('2d');
    cv.width=Math.ceil(W*sz*2*0.75+sz*0.5); cv.height=Math.ceil(H*hh+hh/2+1);
    var tick=0, playing=false, timer=null;

    function hexNbs(r,c) {
        var e=c%2===0;
        return [[r-1,c],[r+1,c],[e?r-1:r,c+1],[e?r:r+1,c+1],[e?r:r+1,c-1],[e?r-1:r,c-1]]
            .filter(function(p){return p[0]>=0&&p[0]<H&&p[1]>=0&&p[1]<W;});
    }

    function draw() {
        ctx.fillStyle='#0d1117'; ctx.fillRect(0,0,cv.width,cv.height);
        for(var r=0;r<H;r++) for(var c=0;c<W;c++) {
            var cx=c*sz*2*0.75+sz, cy=r*hh+hh/2+(c%2===1?hh/2:0);
            ctx.fillStyle=palette[grid[r][c]]||'#333';
            ctx.beginPath();
            for(var i=0;i<6;i++){var a=Math.PI/3*i;var px=cx+sz*Math.cos(a),py=cy+sz*Math.sin(a);i===0?ctx.moveTo(px,py):ctx.lineTo(px,py);}
            ctx.closePath(); ctx.fill();
        }
    }

    window.aStep = function() {
        var next=[], counts=new Array(NC).fill(0);
        for(var r=0;r<H;r++){next[r]=[];for(var c=0;c<W;c++){
            var self=grid[r][c], nbs=hexNbs(r,c), nc=new Array(NC).fill(0);
            nbs.forEach(function(nb){nc[grid[nb[0]][nb[1]]]++;});
            var result=self;
            for(var i=0;i<rules.length;i++){
                var ru=rules[i];
                if(ru.self_color>=0&&ru.self_color!==self) continue;
                var cnt=nc[ru.neighbor_color]||0;
                if(cnt>=ru.min_count&&cnt<=ru.max_count){result=ru.result_color;break;}
            }
            next[r][c]=result; counts[result]++;
        }}
        grid=next; tick++;
        document.getElementById('atick').textContent='tick '+tick;
        document.getElementById('apop').textContent=counts.map(function(n,i){return 'c'+i+':'+n;}).join(' ');
        draw();
    };

    window.aRandom = function() {
        for(var r=0;r<H;r++) for(var c=0;c<W;c++) grid[r][c]=Math.floor(Math.random()*NC);
        tick=0; draw(); document.getElementById('atick').textContent='tick 0';
    };

    window.aToggle = function() {
        playing=!playing;
        document.getElementById('abtn').textContent=playing?'⏸ Pause':'▶ Play';
        if(playing) aLoop(); else if(timer){clearTimeout(timer);timer=null;}
    };

    function aLoop() {
        if(!playing) return;
        aStep();
        var spd=parseInt(document.getElementById('aspeed').value)||8;
        timer=setTimeout(aLoop, Math.max(16,1000/spd));
    }
    draw();
};
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
