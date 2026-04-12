"""Distill the Tiles app into a standalone JS page.

Takes the full Django Tiles app and produces a single HTML file
that runs entirely in the browser with no server dependency.
"""


def distill():
    """Generate a standalone Tiles HTML page. Returns the HTML string."""

    return r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tiles — Condensed</title>
<!-- CONDENSER: Tier 2 (JS-only) distillation of Velour's Tiles app.
     Lost: Django ORM, Identity mood integration, Attic artwork pipeline, auth.
     Preserved: Wang tiles (square+hex, 2-4 colors), greedy tiling, canvas, PNG. -->
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;padding:0.8rem;font-size:0.85rem}
h1{font-size:1.1rem;color:#58a6ff;margin-bottom:0.3rem}
h2{font-size:0.9rem;margin:0.5rem 0 0.2rem}
.ctrl{display:flex;gap:0.4rem;flex-wrap:wrap;align-items:center;margin:0.4rem 0}
label{font-size:0.72rem;color:#8b949e}
select,input[type=number],input[type=text],input[type=color]{
  background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;
  padding:0.2rem 0.3rem;font-size:0.78rem}
input[type=color]{width:28px;height:22px;padding:0;border:1px solid #30363d;cursor:pointer}
input[type=number]{width:3rem}
input[type=text]{width:7rem}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;
  padding:0.2rem 0.5rem;font-size:0.75rem;cursor:pointer}
button:hover{background:#30363d}
button.go{background:#238636;border-color:#2ea043}
.preview{display:flex;gap:1px;flex-wrap:wrap;margin:0.3rem 0;max-height:200px;overflow-y:auto}
canvas{border:1px solid #30363d;margin:0.3rem 0;display:block;image-rendering:pixelated}
.sets{display:flex;flex-direction:column;gap:2px;margin:0.3rem 0;max-height:150px;overflow-y:auto}
.sr{background:#161b22;border-left:2px solid #bc8cff;border-radius:0 3px 3px 0;
  padding:0.2rem 0.4rem;font-size:0.72rem;cursor:pointer;display:flex;justify-content:space-between;align-items:center}
.sr:hover{background:#1c2028}
.sr.sel{border-left-color:#58a6ff}
.sr .n{color:#c9d1d9;font-weight:500}
.sr .m{color:#6e7681;font-size:0.65rem}
#status{color:#8b949e;font-size:0.68rem;font-family:monospace;margin:0.2rem 0}
</style>
</head>
<body>
<h1>Tiles — Condensed</h1>
<p style="color:#6e7681;font-size:0.72rem">Wang tiles in the browser. No server. Saved in localStorage.</p>

<div class="ctrl">
  <label>Type<select id="tt"><option value="square">Square</option><option value="hex">Hex</option></select></label>
  <label>Colors<input type="number" id="nc" value="2" min="2" max="4"></label>
  <label><input type="color" id="c0" value="#58a6ff"></label>
  <label><input type="color" id="c1" value="#f85149"></label>
  <label><input type="color" id="c2" value="#2ea043"></label>
  <label><input type="color" id="c3" value="#d29922"></label>
  <label>Name<input type="text" id="sn" placeholder="my set"></label>
  <button class="go" onclick="createSet()">Create</button>
  <button onclick="genComplete()">Complete set</button>
</div>

<h2>Tilesets <span style="color:#6e7681;font-size:0.68rem" id="setcount"></span></h2>
<div class="sets" id="slist"></div>

<h2>Tiles</h2>
<div class="preview" id="tprev"></div>

<h2>Tiling</h2>
<div class="ctrl">
  <label>W<input type="number" id="gw" value="20" min="1" max="64"></label>
  <label>H<input type="number" id="gh" value="20" min="1" max="64"></label>
  <label>Px<input type="number" id="px" value="14" min="4" max="40"></label>
  <button class="go" onclick="tile()">Generate</button>
  <button onclick="savePNG()">PNG</button>
</div>
<canvas id="cv"></canvas>
<div id="status"></div>

<script>
var K='condenser_tiles_v2',S=JSON.parse(localStorage.getItem(K)||'[]'),ci=-1;
function sv(){localStorage.setItem(K,JSON.stringify(S))}
function gc(){var n=+$('nc').value||2,c=[];for(var i=0;i<Math.min(n,4);i++)c.push($('c'+i).value);return c}
function $(id){return document.getElementById(id)}

function createSet(){
  var t=$('tt').value,c=gc(),n=$('sn').value.trim()||t+' '+c.length+'c';
  S.push({n:n,t:t,c:c,tiles:[]});ci=S.length-1;sv();draw();
}

function genComplete(){
  if(ci<0)createSet();
  var s=S[ci];s.tiles=[];
  var nc=s.c.length,ne=s.t==='hex'?6:4;
  var total=Math.pow(nc,ne),limit=Math.min(total,256);
  for(var i=0;i<limit;i++){
    var e=[],v=i;
    for(var j=0;j<ne;j++){e.push(s.c[v%nc]);v=Math.floor(v/nc)}
    s.tiles.push(e);
  }
  sv();draw();
}

function selSet(i){ci=i;draw()}
function delSet(i){S.splice(i,1);if(ci>=S.length)ci=S.length-1;sv();draw()}

function drawSets(){
  var el=$('slist');
  $('setcount').textContent=S.length+' sets';
  if(!S.length){el.innerHTML='<span style="color:#6e7681;font-size:0.7rem">None yet</span>';return}
  el.innerHTML=S.map(function(s,i){
    return '<div class="sr'+(i===ci?' sel':'')+'" onclick="selSet('+i+')">'+
      '<span class="n">'+s.n+'</span>'+
      '<span class="m">'+s.t+' '+s.tiles.length+'t '+s.c.length+'c '+
      '<button onclick="event.stopPropagation();delSet('+i+')" style="font-size:0.6rem;padding:0 0.2rem">×</button></span></div>';
  }).join('');
}

function drawPrev(){
  var el=$('tprev');
  if(ci<0||!S[ci]){el.innerHTML='';return}
  var s=S[ci],sz=s.t==='hex'?20:18;
  el.innerHTML=s.tiles.slice(0,80).map(function(e){
    if(s.t==='hex'){
      return '<svg width="'+sz+'" height="'+Math.round(sz*0.87)+'" viewBox="0 0 100 87">'+
        '<polygon points="25,0 75,0 50,43.5" fill="'+e[0]+'"/>'+
        '<polygon points="75,0 100,43.5 50,43.5" fill="'+e[1]+'"/>'+
        '<polygon points="100,43.5 75,87 50,43.5" fill="'+e[2]+'"/>'+
        '<polygon points="75,87 25,87 50,43.5" fill="'+e[3]+'"/>'+
        '<polygon points="25,87 0,43.5 50,43.5" fill="'+e[4]+'"/>'+
        '<polygon points="0,43.5 25,0 50,43.5" fill="'+e[5]+'"/></svg>';
    }
    return '<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 56 56">'+
      '<polygon points="0,0 56,0 28,28" fill="'+e[0]+'"/>'+
      '<polygon points="56,0 56,56 28,28" fill="'+e[1]+'"/>'+
      '<polygon points="56,56 0,56 28,28" fill="'+e[2]+'"/>'+
      '<polygon points="0,56 0,0 28,28" fill="'+e[3]+'"/></svg>';
  }).join('');
}

// CONDENSER: Greedy tiling — the core algorithm that survives all tiers.
function tile(){
  if(ci<0||!S[ci]||!S[ci].tiles.length)return;
  var s=S[ci],gw=+$('gw').value||20,gh=+$('gh').value||20,px=+$('px').value||14;
  var cv=$('cv'),ctx=cv.getContext('2d'),hex=s.t==='hex';

  if(hex){
    var sz=px/2,hh=Math.sqrt(3)*sz;
    cv.width=Math.ceil(gw*sz*2*0.75+sz*0.5);
    cv.height=Math.ceil(gh*hh+hh/2+1);
  }else{
    cv.width=gw*px;cv.height=gh*px;
  }
  ctx.fillStyle='#0d1117';ctx.fillRect(0,0,cv.width,cv.height);

  // Edge index mapping for matching
  // Square: 0=N,1=E,2=S,3=W. Match: my[3]=left[1], my[0]=up[2]
  // Hex: 0=N,1=NE,2=SE,3=S,4=SW,5=NW
  //   Opposite: 0↔3, 1↔4, 2↔5
  var opp=hex?[3,4,5,0,1,2]:[2,3,0,1];

  function hexNb(r,c,d){
    var e=c%2===0;
    switch(d){
      case 0:return[r-1,c];     // N
      case 3:return[r+1,c];     // S
      case 1:return e?[r-1,c+1]:[r,c+1];   // NE
      case 2:return e?[r,c+1]:[r+1,c+1];   // SE
      case 4:return e?[r,c-1]:[r+1,c-1];   // SW
      case 5:return e?[r-1,c-1]:[r,c-1];   // NW
    }
  }

  var grid=[],filled=0,stuck=0;
  for(var r=0;r<gh;r++){grid[r]=[];
    for(var c=0;c<gw;c++){
      var cands=s.tiles.slice();
      if(hex){
        for(var d=0;d<6;d++){
          var nb=hexNb(r,c,d);
          if(nb&&nb[0]>=0&&nb[0]<gh&&nb[1]>=0&&nb[1]<gw&&grid[nb[0]]&&grid[nb[0]][nb[1]]){
            var need=grid[nb[0]][nb[1]][opp[d]];
            cands=cands.filter(function(t){return t[d]===need});
          }
        }
      }else{
        if(c>0&&grid[r][c-1])cands=cands.filter(function(t){return t[3]===grid[r][c-1][1]});
        if(r>0&&grid[r-1][c])cands=cands.filter(function(t){return t[0]===grid[r-1][c][2]});
      }
      if(!cands.length){grid[r][c]=null;stuck++}
      else{grid[r][c]=cands[Math.floor(Math.random()*cands.length)];filled++}
    }
  }

  // Render
  if(hex){
    var sz=px/2,hh=Math.sqrt(3)*sz;
    var em=[[1,2],[0,1],[5,0],[4,5],[3,4],[2,3]]; // edge→corner pairs
    for(var r=0;r<gh;r++)for(var c=0;c<gw;c++){
      var t=grid[r][c];if(!t)continue;
      var cx=c*sz*2*0.75+sz,cy=r*hh+hh/2+(c%2===1?hh/2:0);
      var pts=[];for(var i=0;i<6;i++){var a=Math.PI/3*i;pts.push([cx+sz*Math.cos(a),cy+sz*Math.sin(a)])}
      for(var e=0;e<6;e++){
        ctx.fillStyle=t[e];ctx.beginPath();
        ctx.moveTo(pts[em[e][0]][0],pts[em[e][0]][1]);
        ctx.lineTo(pts[em[e][1]][0],pts[em[e][1]][1]);
        ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      }
    }
  }else{
    var h=px/2;
    for(var r=0;r<gh;r++)for(var c=0;c<gw;c++){
      var t=grid[r][c];if(!t)continue;
      var x=c*px,y=r*px,cx=x+h,cy=y+h;
      ctx.fillStyle=t[0];ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+px,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t[1];ctx.beginPath();ctx.moveTo(x+px,y);ctx.lineTo(x+px,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t[2];ctx.beginPath();ctx.moveTo(x+px,y+px);ctx.lineTo(x,y+px);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
      ctx.fillStyle=t[3];ctx.beginPath();ctx.moveTo(x,y+px);ctx.lineTo(x,y);ctx.lineTo(cx,cy);ctx.closePath();ctx.fill();
    }
  }
  $('status').textContent=gw+'×'+gh+'='+gw*gh+' cells. '+filled+' filled, '+stuck+' stuck.';
}

function savePNG(){
  var a=document.createElement('a');a.download='tiling.png';
  a.href=$('cv').toDataURL('image/png');a.click();
}

function draw(){drawSets();drawPrev()}
draw();
</script>
</body>
</html>'''
