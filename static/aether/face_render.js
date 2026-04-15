/* ====================================================================
 * FACE RENDER — procedural kawaii face engine
 *
 * Shared between /aether/faces/ (forge) and /aether/faces/library/.
 * Every face is a JSON genome; rendering is pure canvas 2D, layered.
 * Exposes under window.FaceRender.
 * ==================================================================== */
(function () {
'use strict';

/* ---------- deterministic RNG (mulberry32) ---------- */
function mulberry32(a) {
  return function() {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = a;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
function rngPick(rng, arr) { return arr[Math.floor(rng() * arr.length)]; }
function rngRange(rng, a, b) { return a + (b - a) * rng(); }

/* ---------- palette helpers ---------- */
function parseHex(h) {
  h = h.replace('#','');
  return [parseInt(h.slice(0,2),16), parseInt(h.slice(2,4),16), parseInt(h.slice(4,6),16)];
}
function hslToHex(h, s, l) {
  s /= 100; l /= 100;
  const k = n => (n + h/30) % 12;
  const a = s * Math.min(l, 1-l);
  const f = n => {
    const c = l - a * Math.max(-1, Math.min(k(n)-3, Math.min(9-k(n), 1)));
    return Math.round(255*c).toString(16).padStart(2,'0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}
function lightenHex(hex, amt) {
  const [r,g,b] = parseHex(hex.replace('#',''));
  const f = v => Math.round(Math.max(0, Math.min(255, v + amt*2.55))).toString(16).padStart(2,'0');
  return `#${f(r)}${f(g)}${f(b)}`;
}
function darkenHex(hex, amt) { return lightenHex(hex, -amt); }
function lerpColor(a, b, t) {
  const pa = parseHex(a.replace('#','')), pb = parseHex(b.replace('#',''));
  const r = Math.round(pa[0] + (pb[0]-pa[0])*t);
  const g = Math.round(pa[1] + (pb[1]-pa[1])*t);
  const bl = Math.round(pa[2] + (pb[2]-pa[2])*t);
  return `rgb(${r},${g},${bl})`;
}

/* ---------- trait vocabularies ---------- */
const FACE_SHAPES  = ['round','oval','heart','square','long'];
const EYE_SHAPES   = ['round','almond','cat','sleepy','wide','droopy'];
const BROW_SHAPES  = ['arch','flat','angry','sad','thin','bushy'];
const NOSE_SHAPES  = ['button','long','hook','flat','wide'];
const MOUTH_SHAPES = ['smile','neutral','pout','grin','frown','o','smirk'];
const HAIR_STYLES  = ['short','long','bun','twintails','bob','wild','bald','mohawk','ponytail','fringe','afro'];
const HAT_KINDS    = ['','','','','beret','crown','wizard','top_hat','beanie','headband','flower','halo','bow','cat_ears'];
const EAR_STYLES   = ['normal','pointed','big','small','elf'];
const TATTOO_KINDS = ['','','','','','tear','rune','dots','line','star','heart'];
const SCAR_KINDS   = ['','','','cheek','brow','lip','nose','eye'];
const EYEPATCH_SIDE = ['left','right'];

/* ---------- L-system animation alphabet ---------- */
function randomAnimProgram(rng) {
  const axiomParts = [];
  const len = 4 + Math.floor(rng()*4);
  for (let i=0;i<len;i++) axiomParts.push(rngPick(rng, ['I','J','K','.','i']));
  return {
    axiom: axiomParts.join(''),
    rules: { I: genRule(rng), J: genRule(rng), K: genRule(rng) },
    iters: 2 + Math.floor(rng()*2),
    tempo: 1.2 + rng()*1.4,
  };
}
function genRule(rng) {
  const pool = '.ib.BW.wLR..SsFPpTEeHCY..Ii.';
  const len = 5 + Math.floor(rng()*8);
  let out = '';
  for (let i=0;i<len;i++) {
    if (rng() < 0.12) out += rngPick(rng, ['I','J','K']);
    else out += pool[Math.floor(rng()*pool.length)];
  }
  return out;
}
function expandLSystem(prog) {
  let s = prog.axiom;
  for (let it=0; it<(prog.iters||2); it++) {
    let next = '';
    for (const c of s) next += (prog.rules && prog.rules[c] !== undefined ? prog.rules[c] : c);
    s = next;
    if (s.length > 4000) break;
  }
  return s;
}

/* ---------- genome construction ---------- */
function randomGenome(seed) {
  const rng = mulberry32(seed);

  const skinH = rngRange(rng, 10, 35);
  const skinS = rngRange(rng, 30, 65);
  const skinL = rngRange(rng, 55, 85);
  const skin  = hslToHex(skinH, skinS, skinL);
  const skinShade = hslToHex(skinH, skinS, Math.max(30, skinL-15));
  const skinHL = hslToHex(skinH, skinS*0.7, Math.min(95, skinL+10));

  const hairH = rng() < 0.15 ? rngRange(rng, 0, 360) : rngRange(rng, 0, 60);
  const hairL = rngRange(rng, 12, 75);
  const hair  = hslToHex(hairH, rngRange(rng, 30, 85), hairL);
  const hairShade = hslToHex(hairH, 60, Math.max(5, hairL-18));

  const irisH = rngRange(rng, 0, 360);
  const iris  = hslToHex(irisH, rngRange(rng, 30, 85), rngRange(rng, 25, 55));

  const lipH = rngRange(rng, 340, 380) % 360;
  const lip  = hslToHex(lipH, rngRange(rng, 40, 80), rngRange(rng, 40, 65));

  return {
    seed, lineage: 0,
    palette: {
      skin, skinShade, skinHL,
      hair, hairShade,
      iris, lip,
      tattooCol: hslToHex(rngRange(rng, 0, 360), 60, 30),
      hatCol:    hslToHex(rngRange(rng, 0, 360), rngRange(rng, 30, 85), rngRange(rng, 25, 60)),
      blush:     hslToHex((lipH+10)%360, 70, 70),
    },
    traits: {
      face_shape:  rngPick(rng, FACE_SHAPES),
      face_w:      rngRange(rng, 0.82, 1.12),
      face_h:      rngRange(rng, 0.90, 1.18),
      eye_shape:   rngPick(rng, EYE_SHAPES),
      eye_size:    rngRange(rng, 0.85, 1.35),
      eye_spacing: rngRange(rng, 0.88, 1.12),
      eye_tilt:    rngRange(rng, -12, 12),
      iris_size:   rngRange(rng, 0.65, 1.05),
      pupil_size:  rngRange(rng, 0.32, 0.55),
      eyelash:     Math.floor(rng()*5),
      eyebag:      rng(),
      brow_shape:  rngPick(rng, BROW_SHAPES),
      brow_thick:  rngRange(rng, 0.5, 1.6),
      brow_tilt:   rngRange(rng, -15, 15),
      brow_y:      rngRange(rng, -3, 3),
      nose_shape:  rngPick(rng, NOSE_SHAPES),
      nose_size:   rngRange(rng, 0.7, 1.3),
      mouth_shape: rngPick(rng, MOUTH_SHAPES),
      mouth_width: rngRange(rng, 0.7, 1.25),
      lip_full:    rngRange(rng, 0.4, 1.4),
      teeth_show:  rng() < 0.35 ? rngRange(rng, 0.1, 0.6) : 0,
      teeth_count: 2 + Math.floor(rng()*6),
      ear_style:   rngPick(rng, EAR_STYLES),
      ear_size:    rngRange(rng, 0.8, 1.25),
      hair_style:  rngPick(rng, HAIR_STYLES),
      hair_volume: rngRange(rng, 0.6, 1.6),
      fringe:      rng(),
      hat_kind:    rngPick(rng, HAT_KINDS),
      earrings:    rng() < 0.3 ? 1 + Math.floor(rng()*2) : 0,
      nose_ring:   rng() < 0.08 ? 1 : 0,
      septum:      rng() < 0.05 ? 1 : 0,
      forehead_gem:rng() < 0.06 ? 1 : 0,
      neck_chain:  rng() < 0.15 ? 1 : 0,
      tattoo_kind: rngPick(rng, TATTOO_KINDS),
      tattoo_x:    rngRange(rng, 0.15, 0.85),
      tattoo_y:    rngRange(rng, 0.25, 0.85),
      wrinkle:     Math.floor(rng() * (rng()<0.3?7:2)),
      wart:        rng() < 0.15 ? 1 + Math.floor(rng()*3) : 0,
      wart_x:      rngRange(rng, 0.2, 0.8),
      wart_y:      rngRange(rng, 0.3, 0.75),
      scar_kind:   rngPick(rng, SCAR_KINDS),
      eyepatch:    rng() < 0.04 ? rngPick(rng, EYEPATCH_SIDE) : '',
      freckles:    rng() < 0.25 ? rngRange(rng, 0.2, 1.0) : 0,
      blush:       rng() < 0.55 ? rngRange(rng, 0.2, 1.0) : 0,
      makeup_eye:  rng() < 0.30 ? rngRange(rng, 0.3, 1.0) : 0,
      makeup_lip:  rng() < 0.35 ? rngRange(rng, 0.3, 1.0) : 0,
    },
    anim: randomAnimProgram(rng),
  };
}

/* ---------- mutation / breeding ---------- */
function mutateGenome(parent, childSeed, strength) {
  strength = strength == null ? 0.5 : strength;
  const rng = mulberry32(childSeed);
  const g = JSON.parse(JSON.stringify(parent));
  g.seed = childSeed;
  g.lineage = (parent.lineage || 0) + 1;

  const mut = (key, fn) => { if (rng() < strength) g.traits[key] = fn(g.traits[key]); };
  const nudge = (v, d) => v + (rng()*2-1)*d;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  if (rng()<strength*0.3)  g.traits.face_shape  = rngPick(rng, FACE_SHAPES);
  if (rng()<strength*0.4)  g.traits.eye_shape   = rngPick(rng, EYE_SHAPES);
  if (rng()<strength*0.3)  g.traits.brow_shape  = rngPick(rng, BROW_SHAPES);
  if (rng()<strength*0.3)  g.traits.nose_shape  = rngPick(rng, NOSE_SHAPES);
  if (rng()<strength*0.4)  g.traits.mouth_shape = rngPick(rng, MOUTH_SHAPES);
  if (rng()<strength*0.25) g.traits.hair_style  = rngPick(rng, HAIR_STYLES);
  if (rng()<strength*0.20) g.traits.hat_kind    = rngPick(rng, HAT_KINDS);
  if (rng()<strength*0.15) g.traits.ear_style   = rngPick(rng, EAR_STYLES);
  if (rng()<strength*0.15) g.traits.tattoo_kind = rngPick(rng, TATTOO_KINDS);
  if (rng()<strength*0.10) g.traits.scar_kind   = rngPick(rng, SCAR_KINDS);
  if (rng()<strength*0.05) {
    g.traits.eyepatch = rng() < 0.15 ? rngPick(rng, EYEPATCH_SIDE) : '';
  }

  mut('face_w',      v => clamp(nudge(v, 0.08), 0.75, 1.2));
  mut('face_h',      v => clamp(nudge(v, 0.08), 0.85, 1.25));
  mut('eye_size',    v => clamp(nudge(v, 0.15), 0.7, 1.5));
  mut('eye_spacing', v => clamp(nudge(v, 0.06), 0.82, 1.18));
  mut('eye_tilt',    v => clamp(nudge(v, 4), -18, 18));
  mut('iris_size',   v => clamp(nudge(v, 0.10), 0.5, 1.15));
  mut('pupil_size',  v => clamp(nudge(v, 0.05), 0.25, 0.6));
  mut('brow_thick',  v => clamp(nudge(v, 0.20), 0.3, 1.8));
  mut('brow_tilt',   v => clamp(nudge(v, 4), -20, 20));
  mut('brow_y',      v => clamp(nudge(v, 1.2), -6, 6));
  mut('nose_size',   v => clamp(nudge(v, 0.12), 0.55, 1.45));
  mut('mouth_width', v => clamp(nudge(v, 0.10), 0.6, 1.35));
  mut('lip_full',    v => clamp(nudge(v, 0.15), 0.3, 1.6));
  mut('ear_size',    v => clamp(nudge(v, 0.08), 0.7, 1.35));
  mut('hair_volume', v => clamp(nudge(v, 0.15), 0.4, 1.8));
  mut('fringe',      v => clamp(nudge(v, 0.15), 0, 1));
  mut('blush',       v => clamp(nudge(v, 0.2), 0, 1.2));
  mut('freckles',    v => clamp(nudge(v, 0.2), 0, 1.2));
  mut('makeup_eye',  v => clamp(nudge(v, 0.2), 0, 1.2));
  mut('makeup_lip',  v => clamp(nudge(v, 0.2), 0, 1.2));
  mut('tattoo_x',    v => clamp(nudge(v, 0.08), 0.1, 0.9));
  mut('tattoo_y',    v => clamp(nudge(v, 0.08), 0.2, 0.9));

  if (rng()<strength*0.3)  g.traits.eyelash    = clamp((g.traits.eyelash|0) + (rng()<0.5?-1:1), 0, 5);
  if (rng()<strength*0.2)  g.traits.wrinkle    = clamp((g.traits.wrinkle|0) + (rng()<0.5?-1:1), 0, 8);
  if (rng()<strength*0.15) g.traits.wart       = clamp((g.traits.wart|0) + (rng()<0.5?-1:1), 0, 3);
  if (rng()<strength*0.3)  g.traits.teeth_show = clamp(nudge(g.traits.teeth_show, 0.2), 0, 1);

  const shift = (hex, dH, dS, dL) => {
    const [r,gr,b] = parseHex(hex.replace('#',''));
    const max = Math.max(r,gr,b), min = Math.min(r,gr,b);
    let h, s, l = (max+min)/2/255;
    if (max===min) { h=0; s=0; } else {
      const d = (max-min)/255;
      s = l>0.5 ? d/(2-max/255-min/255) : d/(max/255+min/255);
      switch(max){
        case r:  h = ((gr-b)/255/d + (gr<b?6:0)); break;
        case gr: h = ((b-r)/255/d + 2); break;
        default: h = ((r-gr)/255/d + 4);
      }
      h *= 60;
    }
    return hslToHex((h+dH+360)%360, clamp(s*100+dS,5,95), clamp(l*100+dL,5,95));
  };
  if (rng()<strength*0.4) g.palette.hair = shift(g.palette.hair, (rng()*2-1)*20, (rng()*2-1)*10, (rng()*2-1)*8);
  if (rng()<strength*0.2) g.palette.skin = shift(g.palette.skin, (rng()*2-1)*3, (rng()*2-1)*6, (rng()*2-1)*5);
  if (rng()<strength*0.5) g.palette.iris = shift(g.palette.iris, (rng()*2-1)*40, (rng()*2-1)*15, (rng()*2-1)*12);
  if (rng()<strength*0.3) g.palette.lip  = shift(g.palette.lip, (rng()*2-1)*10, (rng()*2-1)*8, (rng()*2-1)*8);
  if (rng()<strength*0.3) g.palette.hatCol = shift(g.palette.hatCol, (rng()*2-1)*40, 0, 0);

  if (rng()<strength*0.7) {
    const keys = Object.keys(g.anim.rules);
    const k = rngPick(rng, keys);
    if (rng()<0.4) g.anim.rules[k] = genRule(rng);
    else {
      const arr = g.anim.rules[k].split('');
      if (arr.length) {
        const idx = Math.floor(rng()*arr.length);
        const pool = '.ib.BW.wLR..SsFPpTEeHCY..Ii.';
        arr[idx] = pool[Math.floor(rng()*pool.length)];
        g.anim.rules[k] = arr.join('');
      }
    }
  }
  if (rng()<strength*0.3) g.anim.tempo = clamp(nudge(g.anim.tempo, 0.4), 0.6, 3.2);
  if (rng()<strength*0.2) g.anim.iters = clamp(g.anim.iters + (rng()<0.5?-1:1), 1, 4);
  return g;
}

/* ---------- animation runtime ---------- */
function makeAnimState(genome) {
  return {
    tape: expandLSystem(genome.anim),
    pos: 0,
    lastAdvance: 0,
    envelopes: [],
  };
}

const ENVELOPE_TABLE = {
  '.': [], ' ': [],
  'i': [['idle', 0, 0.25]], 'I': [['idle', 0, 0.25]],
  'J': [['idle', 0, 0.25]], 'K': [['idle', 0, 0.25]],
  'b': [['blink', 1.0, 0.18]],
  'B': [['blink', 1.0, 0.12], ['blink', 1.0, 0.12]],
  'W': [['winkL', 1.0, 0.45]],
  'w': [['winkR', 1.0, 0.45]],
  'L': [['look_x', -1.0, 0.9]],
  'R': [['look_x',  1.0, 0.9]],
  'U': [['look_y', -0.6, 0.7]],
  'D': [['look_y',  0.6, 0.7]],
  'S': [['smile',   1.0, 1.0]],
  's': [['smile',   0.5, 0.8]],
  'F': [['smile',  -0.8, 0.9]],
  'P': [['pupil',   1.0, 0.7]],
  'p': [['pupil',  -0.7, 0.7]],
  'T': [['brow_twitch', 1.0, 0.25]],
  'E': [['brow_raise',  1.0, 0.9]],
  'e': [['brow_raise', -0.7, 0.8]],
  'H': [['head_tilt',  1.0, 1.3]],
  'h': [['head_tilt', -1.0, 1.3]],
  'C': [['blush',      1.0, 1.6]],
  'Y': [['blink', 1.0, 1.1], ['smile', -0.3, 1.1]],
};

function advanceAnim(anim, dt, genome, tNow) {
  if (!anim.tape.length) return;
  anim.lastAdvance += dt;
  const stepDur = 1.0 / (genome.anim.tempo || 1.5);
  while (anim.lastAdvance >= stepDur) {
    anim.lastAdvance -= stepDur;
    const ch = anim.tape[anim.pos % anim.tape.length];
    anim.pos++;
    const envs = ENVELOPE_TABLE[ch];
    if (envs) {
      for (let i=0;i<envs.length;i++) {
        const [key, delta, dur] = envs[i];
        anim.envelopes.push({ key, delta, dur, startT: tNow + i*dur*0.55 });
      }
    }
  }
  anim.envelopes = anim.envelopes.filter(e => (tNow - e.startT) < e.dur);
}

function sampleAnim(anim, tNow) {
  const out = { blink:0, winkL:0, winkR:0, look_x:0, look_y:0, smile:0,
                pupil:0, brow_twitch:0, brow_raise:0, head_tilt:0, blush:0, idle:0 };
  for (const e of anim.envelopes) {
    const age = tNow - e.startT;
    if (age < 0 || age > e.dur) continue;
    const u = age / e.dur;
    const w = 0.5 - 0.5 * Math.cos(u * Math.PI * 2);
    out[e.key] = (out[e.key] || 0) + e.delta * w;
  }
  return out;
}

/* ---------- rendering ---------- */
function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x+r, y);
  ctx.arcTo(x+w, y, x+w, y+h, r);
  ctx.arcTo(x+w, y+h, x, y+h, r);
  ctx.arcTo(x, y+h, x, y, r);
  ctx.arcTo(x, y, x+w, y, r);
}

function renderFace(ctx, W, H, genome, anim, tNow, headParallax, options) {
  ctx.save();
  ctx.clearRect(0, 0, W, H);

  const t = genome.traits;
  const p = genome.palette;
  const samp = sampleAnim(anim, tNow);

  if (!(options && options.transparentBg)) {
    const bg = ctx.createRadialGradient(W/2, H*0.55, W*0.2, W/2, H*0.55, W*0.9);
    bg.addColorStop(0, '#1a2030');
    bg.addColorStop(1, '#0a0e14');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);
  }

  const tilt = samp.head_tilt * 0.08;
  const cx = W/2;
  const cy = H*0.52;
  ctx.translate(cx, cy);
  ctx.rotate(tilt);
  ctx.translate(-cx, -cy);

  const px = headParallax.x;
  const py = headParallax.y;
  const pushLayer = (depth) => ({ x: px * depth * 6, y: py * depth * 4 });

  /* neck */
  {
    const off = pushLayer(-0.7);
    const neckW = W * 0.22 * t.face_w;
    ctx.fillStyle = p.skinShade;
    ctx.beginPath();
    ctx.moveTo(cx - neckW + off.x, cy + H*0.28 + off.y);
    ctx.lineTo(cx + neckW + off.x, cy + H*0.28 + off.y);
    ctx.lineTo(cx + neckW*0.9 + off.x, H + off.y);
    ctx.lineTo(cx - neckW*0.9 + off.x, H + off.y);
    ctx.closePath();
    ctx.fill();
    if (t.neck_chain) {
      ctx.strokeStyle = '#e8c96a';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cx + off.x, cy + H*0.30 + off.y, neckW*0.85, Math.PI*0.15, Math.PI - Math.PI*0.15);
      ctx.stroke();
    }
  }

  /* ears */
  {
    const off = pushLayer(-0.3);
    const earSize = W * 0.07 * t.ear_size * t.face_w;
    const earX = W * 0.32 * t.face_w;
    for (let i=0;i<2;i++) {
      const sx = cx + (i===0 ? -earX : earX) + off.x;
      const sy = cy + H*0.03 + off.y;
      ctx.fillStyle = p.skin;
      ctx.beginPath();
      if (t.ear_style === 'pointed' || t.ear_style === 'elf') {
        ctx.moveTo(sx, sy - earSize*1.6);
        ctx.quadraticCurveTo(sx + (i===0?-1:1)*earSize*0.8, sy, sx, sy + earSize);
        ctx.quadraticCurveTo(sx + (i===0?-1:1)*earSize*0.2, sy + earSize*0.1, sx, sy - earSize*1.6);
      } else {
        ctx.ellipse(sx, sy, earSize*0.7, earSize, 0, 0, Math.PI*2);
      }
      ctx.fill();
      ctx.fillStyle = p.skinShade;
      ctx.beginPath();
      ctx.ellipse(sx, sy, earSize*0.35, earSize*0.55, 0, 0, Math.PI*2);
      ctx.fill();
      if (t.earrings >= 1) {
        ctx.fillStyle = '#e8c96a';
        ctx.beginPath();
        ctx.arc(sx, sy + earSize*1.1, 3, 0, Math.PI*2);
        ctx.fill();
      }
      if (t.earrings >= 2) {
        ctx.strokeStyle = '#e8c96a';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(sx, sy + earSize*1.3, 5, 0, Math.PI*2);
        ctx.stroke();
      }
    }
  }

  if (t.hair_style !== 'bald') drawHairBack(ctx, W, H, cx, cy, t, p, pushLayer(-0.2));

  /* face shape (skin) */
  {
    const off = pushLayer(0.0);
    const fw = W * 0.22 * t.face_w;
    const fh = H * 0.28 * t.face_h;
    const shape = t.face_shape;
    ctx.fillStyle = p.skin;
    ctx.beginPath();
    if (shape === 'round') {
      ctx.ellipse(cx + off.x, cy + off.y, fw, fh, 0, 0, Math.PI*2);
    } else if (shape === 'heart') {
      const x = cx+off.x, y = cy+off.y;
      ctx.moveTo(x, y - fh);
      ctx.bezierCurveTo(x - fw*1.2, y - fh, x - fw*1.1, y + fh*0.3, x, y + fh);
      ctx.bezierCurveTo(x + fw*1.1, y + fh*0.3, x + fw*1.2, y - fh, x, y - fh);
    } else if (shape === 'square') {
      roundRect(ctx, cx + off.x - fw, cy + off.y - fh, fw*2, fh*2, fw*0.35);
    } else if (shape === 'long') {
      ctx.ellipse(cx + off.x, cy + off.y + fh*0.1, fw*0.85, fh*1.15, 0, 0, Math.PI*2);
    } else {
      ctx.ellipse(cx + off.x, cy + off.y + fh*0.05, fw*0.95, fh*1.08, 0, 0, Math.PI*2);
    }
    ctx.fill();
    const sg = ctx.createLinearGradient(cx-fw, cy, cx+fw, cy);
    sg.addColorStop(0, 'rgba(0,0,0,0.18)');
    sg.addColorStop(0.55, 'rgba(0,0,0,0.0)');
    ctx.fillStyle = sg;
    ctx.fill();
  }

  {
    const off = pushLayer(0.05);
    if (t.freckles > 0) drawFreckles(ctx, cx+off.x, cy+off.y, W, H, t, genome.seed);
    if (t.wrinkle > 0) drawWrinkles(ctx, cx+off.x, cy+off.y, W, H, t);
    if (t.wart > 0) drawWarts(ctx, cx+off.x, cy+off.y, W, H, t, genome.seed);
    if (t.tattoo_kind) drawTattoo(ctx, cx+off.x, cy+off.y, W, H, t, p);
    if (t.scar_kind) drawScar(ctx, cx+off.x, cy+off.y, W, H, t);
  }

  {
    const off = pushLayer(0.10);
    const blushN = (t.blush || 0) + Math.max(0, samp.blush)*0.8;
    if (blushN > 0.05) {
      const r = W*0.06*blushN;
      for (let i=0;i<2;i++) {
        const bx = cx + (i===0?-1:1) * W*0.12 + off.x;
        const by = cy + H*0.09 + off.y;
        const g2 = ctx.createRadialGradient(bx, by, 0, bx, by, r);
        g2.addColorStop(0, `rgba(255,120,130,${0.35*blushN})`);
        g2.addColorStop(1, 'rgba(255,120,130,0)');
        ctx.fillStyle = g2;
        ctx.fillRect(bx-r, by-r, r*2, r*2);
      }
    }
  }

  drawNose(ctx, cx, cy, W, H, t, p, pushLayer(0.15));
  drawMouth(ctx, cx, cy, W, H, t, p, samp, pushLayer(0.20));
  drawEyes(ctx, cx, cy, W, H, t, p, samp, pushLayer(0.25));
  drawLashes(ctx, cx, cy, W, H, t, p, samp, pushLayer(0.28));
  drawBrows(ctx, cx, cy, W, H, t, p, samp, pushLayer(0.30));
  if (t.eyepatch) drawEyepatch(ctx, cx, cy, W, H, t, pushLayer(0.33));
  if (t.hair_style !== 'bald') drawHairFront(ctx, W, H, cx, cy, t, p, pushLayer(0.35));
  drawPiercings(ctx, cx, cy, W, H, t, pushLayer(0.37));
  if (t.hat_kind) drawHat(ctx, cx, cy, W, H, t, p, pushLayer(0.45));

  ctx.restore();
}

function drawEyes(ctx, cx, cy, W, H, t, p, samp, off) {
  const eyeY = cy - H*0.02;
  const eyeX = W * 0.14 * t.eye_spacing;
  const eyeW = W * 0.055 * t.eye_size;
  const eyeH = H * 0.038 * t.eye_size;
  for (let i=0;i<2;i++) {
    const isLeft = (i===0);
    const ex = cx + (isLeft ? -eyeX : eyeX) + off.x;
    const ey = eyeY + off.y;
    if (t.eyepatch === 'left' && isLeft) continue;
    if (t.eyepatch === 'right' && !isLeft) continue;
    if (t.eyebag > 0.4) {
      ctx.fillStyle = `rgba(60,30,40,${0.15*t.eyebag})`;
      ctx.beginPath();
      ctx.ellipse(ex, ey + eyeH*1.3, eyeW*1.0, eyeH*0.5, 0, 0, Math.PI*2);
      ctx.fill();
    }
    if (t.makeup_eye > 0) {
      ctx.fillStyle = `rgba(120,70,140,${0.25*t.makeup_eye})`;
      ctx.beginPath();
      ctx.ellipse(ex, ey - eyeH*0.6, eyeW*1.2, eyeH*0.9, 0, 0, Math.PI*2);
      ctx.fill();
    }
    ctx.save();
    ctx.translate(ex, ey);
    ctx.rotate((t.eye_tilt * (isLeft?-1:1)) * Math.PI/180);

    let open = 1.0 - Math.max(0, samp.blink);
    if (isLeft  && samp.winkL > 0) open = Math.min(open, 1.0 - samp.winkL);
    if (!isLeft && samp.winkR > 0) open = Math.min(open, 1.0 - samp.winkR);
    open = Math.max(0, Math.min(1, open));
    const shape = t.eye_shape;
    let shapeYScale = 1.0, shapeXScale = 1.0;
    if (shape === 'almond')  shapeYScale = 0.75;
    if (shape === 'cat')     { shapeYScale = 0.65; shapeXScale = 1.12; }
    if (shape === 'sleepy')  shapeYScale = 0.45;
    if (shape === 'wide')    shapeYScale = 1.2;
    if (shape === 'droopy')  shapeYScale = 0.85;

    const effH = Math.max(0, eyeH * shapeYScale * open);
    const effW = Math.max(0.01, eyeW * shapeXScale);

    if (open > 0.08) {
      ctx.fillStyle = '#fbfbf5';
      ctx.beginPath();
      ctx.ellipse(0, 0, effW, effH, 0, 0, Math.PI*2);
      ctx.fill();
      const lx = Math.max(-1, Math.min(1, samp.look_x));
      const ly = Math.max(-1, Math.min(1, samp.look_y));
      const irisR = Math.min(effW, effH) * t.iris_size * 1.15;
      const ix = lx * (effW - irisR) * 0.9;
      const iy = ly * (effH - irisR) * 0.9;
      ctx.save();
      ctx.beginPath();
      ctx.ellipse(0, 0, effW, effH, 0, 0, Math.PI*2);
      ctx.clip();
      const ig = ctx.createRadialGradient(ix, iy, 0, ix, iy, irisR);
      ig.addColorStop(0, lightenHex(p.iris, 30));
      ig.addColorStop(0.6, p.iris);
      ig.addColorStop(1, darkenHex(p.iris, 35));
      ctx.fillStyle = ig;
      ctx.beginPath(); ctx.arc(ix, iy, irisR, 0, Math.PI*2); ctx.fill();
      const dilate = 1.0 + samp.pupil * 0.3;
      ctx.fillStyle = '#0b0b0f';
      ctx.beginPath(); ctx.arc(ix, iy, irisR * t.pupil_size * dilate, 0, Math.PI*2); ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.9)';
      ctx.beginPath();
      ctx.arc(ix - irisR*0.35, iy - irisR*0.35, irisR*0.22, 0, Math.PI*2);
      ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.beginPath();
      ctx.arc(ix + irisR*0.25, iy + irisR*0.2, irisR*0.1, 0, Math.PI*2);
      ctx.fill();
      ctx.restore();
      ctx.strokeStyle = '#2a1820';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.ellipse(0, 0, effW, effH, 0, 0, Math.PI*2);
      ctx.stroke();
    } else {
      ctx.strokeStyle = '#2a1820';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-effW, 0);
      ctx.quadraticCurveTo(0, effH*0.4, effW, 0);
      ctx.stroke();
    }
    ctx.restore();
  }
}

function drawLashes(ctx, cx, cy, W, H, t, p, samp, off) {
  if (t.eyelash <= 0) return;
  const eyeY = cy - H*0.02;
  const eyeX = W * 0.14 * t.eye_spacing;
  const eyeW = W * 0.055 * t.eye_size;
  const eyeH = H * 0.038 * t.eye_size;
  for (let i=0;i<2;i++) {
    const isLeft = (i===0);
    if (t.eyepatch === 'left' && isLeft) continue;
    if (t.eyepatch === 'right' && !isLeft) continue;
    const ex = cx + (isLeft ? -eyeX : eyeX) + off.x;
    const ey = eyeY + off.y;
    let open = 1.0 - Math.max(0, samp.blink);
    if (isLeft && samp.winkL > 0) open = Math.min(open, 1.0 - samp.winkL);
    if (!isLeft && samp.winkR > 0) open = Math.min(open, 1.0 - samp.winkR);
    open = Math.max(0, Math.min(1, open));
    const effH = Math.max(0, eyeH * open);
    ctx.save();
    ctx.translate(ex, ey);
    ctx.rotate((t.eye_tilt * (isLeft?-1:1)) * Math.PI/180);
    ctx.strokeStyle = '#1a0e14';
    ctx.lineWidth = 1.3;
    const count = t.eyelash;
    for (let j=0;j<count;j++) {
      const u = (j+1) / (count+1);
      const sx = -eyeW + u * 2*eyeW;
      const sy = -effH * Math.sin(u * Math.PI) * 0.98;
      const len = 3 + t.eyelash;
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(sx + (u-0.5) * len * 0.4, sy - len);
      ctx.stroke();
    }
    ctx.restore();
  }
}

function drawBrows(ctx, cx, cy, W, H, t, p, samp, off) {
  const browY = cy - H*0.08 + t.brow_y + off.y;
  const eyeX = W * 0.14 * t.eye_spacing;
  const bw = W * 0.055;
  const bh = 2 + t.brow_thick*3;
  for (let i=0;i<2;i++) {
    const isLeft = (i===0);
    const bx = cx + (isLeft ? -eyeX : eyeX) + off.x;
    let by = browY;
    by -= samp.brow_raise * 6;
    if (isLeft) by -= samp.brow_twitch * 2;
    const tilt = (t.brow_tilt * (isLeft?-1:1)) * Math.PI/180;
    ctx.save();
    ctx.translate(bx, by);
    ctx.rotate(tilt);
    ctx.fillStyle = p.hairShade;
    ctx.beginPath();
    const shape = t.brow_shape;
    const pts = [];
    const steps = 10;
    for (let s=0; s<=steps; s++) {
      const u = s/steps;
      const x = (u-0.5) * bw * 2;
      let y = 0;
      if (shape === 'arch')  y = -Math.sin(u*Math.PI)*bh*0.8;
      else if (shape === 'flat') y = 0;
      else if (shape === 'angry') y = (u-0.3)*bh*1.2;
      else if (shape === 'sad')   y = -(u-0.5)*bh*1.2;
      else if (shape === 'thin')  y = -Math.sin(u*Math.PI)*bh*0.3;
      else if (shape === 'bushy') y = -Math.sin(u*Math.PI)*bh*0.8;
      pts.push([x, y]);
    }
    ctx.moveTo(pts[0][0], pts[0][1]-bh*0.4);
    for (const [x,y] of pts) ctx.lineTo(x, y-bh*0.4);
    for (let s=pts.length-1; s>=0; s--) {
      const [x,y] = pts[s];
      ctx.lineTo(x, y+bh*0.6);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
}

function drawNose(ctx, cx, cy, W, H, t, p, off) {
  const ny = cy + H*0.07 + off.y;
  const nw = W*0.03 * t.nose_size;
  const nh = H*0.08 * t.nose_size;
  ctx.strokeStyle = 'rgba(60,30,40,0.55)';
  ctx.lineWidth = 1.4;
  ctx.fillStyle = p.skinShade;
  ctx.beginPath();
  const shape = t.nose_shape;
  if (shape === 'button') {
    ctx.moveTo(cx+off.x - nw*0.3, ny);
    ctx.quadraticCurveTo(cx+off.x, ny + nh*0.5, cx+off.x + nw*0.3, ny);
    ctx.stroke();
    ctx.fillStyle = 'rgba(60,30,40,0.4)';
    ctx.beginPath();
    ctx.ellipse(cx+off.x - nw*0.15, ny + nh*0.25, 1.2, 0.8, 0, 0, Math.PI*2);
    ctx.ellipse(cx+off.x + nw*0.15, ny + nh*0.25, 1.2, 0.8, 0, 0, Math.PI*2);
    ctx.fill();
  } else if (shape === 'long') {
    ctx.moveTo(cx+off.x, ny - nh*0.6);
    ctx.quadraticCurveTo(cx+off.x - nw*0.9, ny, cx+off.x - nw*0.4, ny + nh*0.4);
    ctx.quadraticCurveTo(cx+off.x, ny + nh*0.55, cx+off.x + nw*0.4, ny + nh*0.4);
    ctx.quadraticCurveTo(cx+off.x + nw*0.9, ny, cx+off.x, ny - nh*0.6);
    ctx.stroke();
  } else if (shape === 'hook') {
    ctx.moveTo(cx+off.x, ny - nh*0.5);
    ctx.quadraticCurveTo(cx+off.x + nw, ny - nh*0.2, cx+off.x + nw*0.6, ny + nh*0.4);
    ctx.quadraticCurveTo(cx+off.x, ny + nh*0.6, cx+off.x - nw*0.4, ny + nh*0.3);
    ctx.stroke();
  } else if (shape === 'flat') {
    ctx.moveTo(cx+off.x - nw*0.7, ny + nh*0.2);
    ctx.quadraticCurveTo(cx+off.x, ny + nh*0.3, cx+off.x + nw*0.7, ny + nh*0.2);
    ctx.stroke();
  } else {
    ctx.moveTo(cx+off.x - nw*1.1, ny + nh*0.2);
    ctx.quadraticCurveTo(cx+off.x, ny + nh*0.5, cx+off.x + nw*1.1, ny + nh*0.2);
    ctx.stroke();
    ctx.fillStyle = 'rgba(60,30,40,0.4)';
    ctx.beginPath();
    ctx.ellipse(cx+off.x - nw*0.45, ny + nh*0.3, 1.6, 1.0, 0, 0, Math.PI*2);
    ctx.ellipse(cx+off.x + nw*0.45, ny + nh*0.3, 1.6, 1.0, 0, 0, Math.PI*2);
    ctx.fill();
  }
}

function drawMouth(ctx, cx, cy, W, H, t, p, samp, off) {
  const my = cy + H*0.17 + off.y;
  const mw = W*0.08 * t.mouth_width;
  const baseShape = t.mouth_shape;
  const smileDelta = samp.smile;
  const lipCol = t.makeup_lip > 0 ? lerpColor(p.lip, '#c22', Math.min(1, t.makeup_lip)) : p.lip;
  ctx.save();
  ctx.translate(cx + off.x, my);
  let cornerDy = 0, centerDy = 0, openY = 0;
  const mood = smileDelta;
  if (baseShape === 'smile') { cornerDy = -mw*0.25; centerDy = mw*0.05; }
  else if (baseShape === 'grin') { cornerDy = -mw*0.35; openY = mw*0.3; }
  else if (baseShape === 'pout') { cornerDy = mw*0.15; centerDy = -mw*0.08; }
  else if (baseShape === 'frown') { cornerDy = mw*0.3; centerDy = -mw*0.02; }
  else if (baseShape === 'o')     { openY = mw*0.45; }
  else if (baseShape === 'smirk') { cornerDy = -mw*0.2; }
  cornerDy -= mood * mw*0.35;
  centerDy += mood * mw*0.08;
  const lipFull = t.lip_full;
  const topLipH  = 2 + lipFull*4;
  const botLipH  = 3 + lipFull*5;
  if (openY > 0 || t.teeth_show > 0.1) {
    const showY = Math.max(openY, t.teeth_show * mw*0.35);
    ctx.fillStyle = '#2a0d14';
    ctx.beginPath();
    ctx.moveTo(-mw, 0 + cornerDy);
    ctx.quadraticCurveTo(0, centerDy + topLipH*0.5, mw, cornerDy);
    ctx.quadraticCurveTo(mw*0.8, showY*0.9, 0, showY);
    ctx.quadraticCurveTo(-mw*0.8, showY*0.9, -mw, cornerDy);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#f4f1e0';
    const teeth = t.teeth_count || 4;
    const tw = mw*1.8 / teeth;
    for (let j=0;j<teeth;j++) {
      const tx = -mw*0.9 + j*tw;
      ctx.fillRect(tx, cornerDy + 1, tw*0.85, showY*0.45);
    }
  }
  ctx.fillStyle = lipCol;
  ctx.beginPath();
  ctx.moveTo(-mw, cornerDy);
  ctx.quadraticCurveTo(-mw*0.5, cornerDy - topLipH*1.2, 0, centerDy);
  ctx.quadraticCurveTo(mw*0.5, cornerDy - topLipH*1.2, mw, cornerDy);
  ctx.quadraticCurveTo(mw*0.5, cornerDy - topLipH*0.3, 0, centerDy + topLipH*0.4);
  ctx.quadraticCurveTo(-mw*0.5, cornerDy - topLipH*0.3, -mw, cornerDy);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(-mw, cornerDy);
  ctx.quadraticCurveTo(0, cornerDy + botLipH*0.5, mw, cornerDy);
  ctx.quadraticCurveTo(mw*0.6, cornerDy + botLipH*2.0, 0, cornerDy + botLipH*2.2);
  ctx.quadraticCurveTo(-mw*0.6, cornerDy + botLipH*2.0, -mw, cornerDy);
  ctx.fill();
  ctx.fillStyle = 'rgba(255,255,255,0.25)';
  ctx.beginPath();
  ctx.ellipse(0, cornerDy + botLipH*0.9, mw*0.35, botLipH*0.3, 0, 0, Math.PI*2);
  ctx.fill();
  ctx.restore();
}

function drawHairBack(ctx, W, H, cx, cy, t, p, off) {
  ctx.fillStyle = p.hair;
  const style = t.hair_style;
  const vol = t.hair_volume;
  const fw = W*0.26 * t.face_w * vol;
  const fh = H*0.35 * t.face_h * vol;
  if (style === 'long') {
    ctx.beginPath();
    ctx.ellipse(cx + off.x, cy + H*0.08 + off.y, fw*1.05, fh*1.4, 0, 0, Math.PI*2);
    ctx.fill();
  } else if (style === 'twintails') {
    ctx.beginPath();
    ctx.ellipse(cx + off.x - fw*0.95, cy + H*0.15 + off.y, fw*0.28, fh*0.7, 0.3, 0, Math.PI*2);
    ctx.ellipse(cx + off.x + fw*0.95, cy + H*0.15 + off.y, fw*0.28, fh*0.7, -0.3, 0, Math.PI*2);
    ctx.fill();
    ctx.beginPath();
    ctx.ellipse(cx + off.x, cy - H*0.05 + off.y, fw*0.98, fh*0.6, 0, Math.PI, 0);
    ctx.fill();
  } else if (style === 'bun') {
    ctx.beginPath();
    ctx.arc(cx + off.x, cy - H*0.26 + off.y, fw*0.35, 0, Math.PI*2);
    ctx.fill();
  } else if (style === 'afro') {
    ctx.beginPath();
    ctx.arc(cx + off.x, cy - H*0.05 + off.y, fw*1.05, 0, Math.PI*2);
    ctx.fill();
  } else if (style === 'ponytail') {
    ctx.beginPath();
    ctx.ellipse(cx + off.x + fw*1.0, cy + H*0.05 + off.y, fw*0.25, fh*0.7, -0.4, 0, Math.PI*2);
    ctx.fill();
  } else if (style === 'bob' || style === 'short' || style === 'fringe') {
    ctx.beginPath();
    ctx.ellipse(cx + off.x, cy - H*0.02 + off.y, fw*0.95, fh*0.65, 0, Math.PI, 0);
    ctx.fill();
  } else if (style === 'wild') {
    ctx.save();
    ctx.translate(cx + off.x, cy - H*0.02 + off.y);
    ctx.beginPath();
    for (let k=0;k<14;k++) {
      const a = (k/14)*Math.PI - Math.PI*0.05;
      const r = fw*0.95 + (Math.sin(k*3.17)*fw*0.2);
      const x = Math.cos(a)*r;
      const y = Math.sin(a)*r*1.1;
      if (k===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  } else if (style === 'mohawk') {
    ctx.fillStyle = p.skinShade;
    ctx.beginPath();
    ctx.ellipse(cx + off.x, cy - H*0.05 + off.y, fw*0.9, fh*0.7, 0, Math.PI, 0);
    ctx.fill();
  }
}

function drawHairFront(ctx, W, H, cx, cy, t, p, off) {
  const style = t.hair_style;
  const fringe = t.fringe;
  if (style === 'bald' || style === 'mohawk') {
    if (style === 'mohawk') {
      ctx.fillStyle = p.hair;
      ctx.beginPath();
      const mw = W*0.05 * t.hair_volume;
      const my = cy - H*0.28 + off.y;
      ctx.moveTo(cx + off.x - mw, cy - H*0.1 + off.y);
      for (let k=0;k<8;k++) {
        const u = k/7;
        ctx.lineTo(cx + off.x + (u-0.5)*mw*2, my - (Math.sin(u*Math.PI))*H*0.12);
      }
      ctx.lineTo(cx + off.x + mw, cy - H*0.1 + off.y);
      ctx.closePath();
      ctx.fill();
    }
    return;
  }
  const fw = W*0.22 * t.face_w;
  ctx.fillStyle = p.hair;
  ctx.beginPath();
  ctx.moveTo(cx + off.x - fw, cy - H*0.18 + off.y);
  const steps = 10;
  for (let s=0;s<=steps;s++) {
    const u = s/steps;
    const x = cx + off.x + (u-0.5)*fw*2;
    const dip = Math.sin(u*Math.PI*3 + t.hair_volume*2);
    const y = cy - H*0.07 + off.y + dip*H*0.015 - fringe*H*0.01;
    ctx.lineTo(x, y + fringe*H*0.05 + (u<0.5?-1:1)*H*0.005);
  }
  ctx.lineTo(cx + off.x + fw, cy - H*0.22 + off.y);
  ctx.quadraticCurveTo(cx + off.x, cy - H*0.30 + off.y, cx + off.x - fw, cy - H*0.22 + off.y);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = lightenHex(p.hair, 18);
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.moveTo(cx + off.x - fw*0.5, cy - H*0.22 + off.y);
  ctx.quadraticCurveTo(cx + off.x - fw*0.3, cy - H*0.15 + off.y, cx + off.x - fw*0.2, cy - H*0.10 + off.y);
  ctx.stroke();
}

function drawHat(ctx, cx, cy, W, H, t, p, off) {
  const kind = t.hat_kind;
  const hx = cx + off.x;
  const hy = cy - H*0.28 + off.y;
  const col = p.hatCol;
  ctx.fillStyle = col;
  if (kind === 'beret') {
    ctx.beginPath();
    ctx.ellipse(hx + W*0.03, hy - H*0.02, W*0.17, H*0.07, -0.2, 0, Math.PI*2);
    ctx.fill();
    ctx.beginPath(); ctx.arc(hx+W*0.14, hy - H*0.04, 3, 0, Math.PI*2); ctx.fill();
  } else if (kind === 'crown') {
    ctx.fillStyle = '#e8c96a';
    ctx.beginPath();
    ctx.moveTo(hx - W*0.14, hy);
    for (let k=0;k<5;k++) {
      const u = k/4;
      ctx.lineTo(hx - W*0.14 + u*W*0.28, hy - H*0.06);
      ctx.lineTo(hx - W*0.14 + (u+0.125)*W*0.28, hy);
    }
    ctx.lineTo(hx + W*0.14, hy);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#e33';
    ctx.beginPath(); ctx.arc(hx, hy - H*0.02, 2.5, 0, Math.PI*2); ctx.fill();
  } else if (kind === 'wizard') {
    ctx.beginPath();
    ctx.moveTo(hx - W*0.13, hy);
    ctx.lineTo(hx, hy - H*0.22);
    ctx.lineTo(hx + W*0.13, hy);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(hx - W*0.18, hy - 2, W*0.36, 4);
  } else if (kind === 'top_hat') {
    ctx.fillStyle = '#10131a';
    ctx.fillRect(hx - W*0.11, hy - H*0.18, W*0.22, H*0.18);
    ctx.fillRect(hx - W*0.17, hy - 2, W*0.34, 5);
    ctx.strokeStyle = col; ctx.lineWidth = 4;
    ctx.beginPath(); ctx.moveTo(hx - W*0.11, hy - H*0.05); ctx.lineTo(hx + W*0.11, hy - H*0.05); ctx.stroke();
  } else if (kind === 'beanie') {
    ctx.beginPath();
    ctx.ellipse(hx, hy - H*0.02, W*0.17, H*0.10, 0, Math.PI, 0);
    ctx.fill();
    ctx.fillStyle = lightenHex(col, -12);
    ctx.fillRect(hx - W*0.17, hy - H*0.02 - 2, W*0.34, 5);
  } else if (kind === 'headband') {
    ctx.fillRect(hx - W*0.18, hy + H*0.02, W*0.36, 6);
  } else if (kind === 'flower') {
    ctx.fillStyle = '#f088aa';
    for (let k=0;k<5;k++) {
      const a = k/5 * Math.PI*2;
      ctx.beginPath();
      ctx.ellipse(hx + W*0.12 + Math.cos(a)*4, hy + H*0.03 + Math.sin(a)*4, 4, 4, 0, 0, Math.PI*2);
      ctx.fill();
    }
    ctx.fillStyle = '#f0c040';
    ctx.beginPath(); ctx.arc(hx + W*0.12, hy + H*0.03, 3, 0, Math.PI*2); ctx.fill();
  } else if (kind === 'halo') {
    ctx.strokeStyle = '#f0e08a';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.ellipse(hx, hy - H*0.04, W*0.16, H*0.025, 0, 0, Math.PI*2);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(255,255,200,0.35)';
    ctx.lineWidth = 8;
    ctx.beginPath();
    ctx.ellipse(hx, hy - H*0.04, W*0.16, H*0.025, 0, 0, Math.PI*2);
    ctx.stroke();
  } else if (kind === 'bow') {
    ctx.fillStyle = '#e04466';
    ctx.beginPath();
    ctx.moveTo(hx - W*0.08, hy + H*0.05);
    ctx.lineTo(hx, hy + H*0.02);
    ctx.lineTo(hx - W*0.08, hy);
    ctx.closePath();
    ctx.moveTo(hx + W*0.08, hy + H*0.05);
    ctx.lineTo(hx, hy + H*0.02);
    ctx.lineTo(hx + W*0.08, hy);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath(); ctx.arc(hx, hy + H*0.025, 3, 0, Math.PI*2); ctx.fill();
  } else if (kind === 'cat_ears') {
    ctx.fillStyle = p.hair;
    ctx.beginPath();
    ctx.moveTo(hx - W*0.12, hy + H*0.05);
    ctx.lineTo(hx - W*0.16, hy - H*0.05);
    ctx.lineTo(hx - W*0.07, hy + H*0.02);
    ctx.closePath();
    ctx.moveTo(hx + W*0.12, hy + H*0.05);
    ctx.lineTo(hx + W*0.16, hy - H*0.05);
    ctx.lineTo(hx + W*0.07, hy + H*0.02);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#f088aa';
    ctx.beginPath();
    ctx.moveTo(hx - W*0.13, hy + H*0.04); ctx.lineTo(hx - W*0.14, hy - H*0.01); ctx.lineTo(hx - W*0.09, hy + H*0.02);
    ctx.moveTo(hx + W*0.13, hy + H*0.04); ctx.lineTo(hx + W*0.14, hy - H*0.01); ctx.lineTo(hx + W*0.09, hy + H*0.02);
    ctx.fill();
  }
}

function drawPiercings(ctx, cx, cy, W, H, t, off) {
  if (t.nose_ring) {
    ctx.strokeStyle = '#c0c0c0'; ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(cx + off.x + W*0.02, cy + H*0.12 + off.y, 3, 0, Math.PI*2);
    ctx.stroke();
  }
  if (t.septum) {
    ctx.strokeStyle = '#c0c0c0'; ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.arc(cx + off.x, cy + H*0.14 + off.y, 3, 0, Math.PI, true);
    ctx.stroke();
  }
  if (t.forehead_gem) {
    ctx.fillStyle = '#ff3b6b';
    ctx.beginPath();
    ctx.moveTo(cx + off.x, cy - H*0.18 + off.y);
    ctx.lineTo(cx + off.x - 3, cy - H*0.17 + off.y);
    ctx.lineTo(cx + off.x, cy - H*0.15 + off.y);
    ctx.lineTo(cx + off.x + 3, cy - H*0.17 + off.y);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,0.6)';
    ctx.beginPath();
    ctx.arc(cx + off.x - 1, cy - H*0.175 + off.y, 1.2, 0, Math.PI*2);
    ctx.fill();
  }
}

function drawEyepatch(ctx, cx, cy, W, H, t, off) {
  const eyeX = W * 0.14;
  const ex = cx + (t.eyepatch === 'left' ? -eyeX : eyeX) + off.x;
  const ey = cy - H*0.02 + off.y;
  ctx.fillStyle = '#0a0a0d';
  ctx.beginPath();
  ctx.ellipse(ex, ey, W*0.08, H*0.055, 0, 0, Math.PI*2);
  ctx.fill();
  ctx.strokeStyle = '#0a0a0d';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(ex - W*0.08, ey - H*0.05);
  ctx.lineTo(cx - W*0.22 + off.x, cy - H*0.15 + off.y);
  ctx.moveTo(ex + W*0.08, ey - H*0.05);
  ctx.lineTo(cx + W*0.22 + off.x, cy - H*0.15 + off.y);
  ctx.stroke();
}

function drawFreckles(ctx, cx, cy, W, H, t, seed) {
  const rng = mulberry32(seed + 999);
  const n = Math.floor(16 * t.freckles);
  ctx.fillStyle = 'rgba(120,60,30,0.55)';
  for (let i=0;i<n;i++) {
    const a = rng()*Math.PI*2;
    const r = rng()*W*0.14;
    const x = cx + Math.cos(a)*r;
    const y = cy + H*0.05 + Math.sin(a)*r*0.7;
    ctx.beginPath();
    ctx.arc(x, y, 1 + rng()*0.6, 0, Math.PI*2);
    ctx.fill();
  }
}

function drawWrinkles(ctx, cx, cy, W, H, t) {
  ctx.strokeStyle = 'rgba(60,30,20,0.35)';
  ctx.lineWidth = 1;
  for (let i=0;i<t.wrinkle;i++) {
    const y = cy - H*0.15 + i*3;
    ctx.beginPath();
    ctx.moveTo(cx - W*0.12, y);
    ctx.quadraticCurveTo(cx, y - 2, cx + W*0.12, y);
    ctx.stroke();
  }
}

function drawWarts(ctx, cx, cy, W, H, t, seed) {
  const rng = mulberry32(seed + 17);
  for (let i=0;i<t.wart;i++) {
    const wx = cx + (t.wart_x - 0.5) * W * 0.3 + (rng()-0.5)*W*0.1;
    const wy = cy + (t.wart_y - 0.5) * H * 0.3 + (rng()-0.5)*H*0.1;
    ctx.fillStyle = '#6b4a38';
    ctx.beginPath();
    ctx.arc(wx, wy, 2 + rng()*1.5, 0, Math.PI*2);
    ctx.fill();
    ctx.fillStyle = 'rgba(30,20,10,0.5)';
    ctx.beginPath();
    ctx.arc(wx + 0.5, wy + 0.5, 1, 0, Math.PI*2);
    ctx.fill();
  }
}

function drawTattoo(ctx, cx, cy, W, H, t, p) {
  const tx = cx + (t.tattoo_x - 0.5) * W * 0.3;
  const ty = cy + (t.tattoo_y - 0.5) * H * 0.35;
  ctx.strokeStyle = p.tattooCol;
  ctx.fillStyle = p.tattooCol;
  ctx.lineWidth = 1.5;
  const k = t.tattoo_kind;
  if (k === 'tear') {
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.quadraticCurveTo(tx-3, ty+3, tx, ty+6);
    ctx.quadraticCurveTo(tx+3, ty+3, tx, ty);
    ctx.fill();
  } else if (k === 'rune') {
    ctx.beginPath();
    ctx.moveTo(tx-5, ty-5); ctx.lineTo(tx+5, ty+5);
    ctx.moveTo(tx+5, ty-5); ctx.lineTo(tx-5, ty+5);
    ctx.moveTo(tx, ty-6); ctx.lineTo(tx, ty+6);
    ctx.stroke();
  } else if (k === 'dots') {
    for (let i=0;i<5;i++) {
      ctx.beginPath();
      ctx.arc(tx + i*3 - 6, ty, 1.1, 0, Math.PI*2);
      ctx.fill();
    }
  } else if (k === 'line') {
    ctx.beginPath(); ctx.moveTo(tx-8, ty); ctx.lineTo(tx+8, ty); ctx.stroke();
  } else if (k === 'star') {
    ctx.beginPath();
    for (let i=0;i<10;i++) {
      const a = i/10 * Math.PI*2 - Math.PI/2;
      const r = (i%2===0) ? 5 : 2;
      const x = tx + Math.cos(a)*r, y = ty + Math.sin(a)*r;
      if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.closePath();
    ctx.fill();
  } else if (k === 'heart') {
    ctx.beginPath();
    ctx.moveTo(tx, ty+4);
    ctx.bezierCurveTo(tx+6, ty-2, tx+3, ty-6, tx, ty-2);
    ctx.bezierCurveTo(tx-3, ty-6, tx-6, ty-2, tx, ty+4);
    ctx.fill();
  }
}

function drawScar(ctx, cx, cy, W, H, t) {
  const k = t.scar_kind;
  ctx.strokeStyle = '#d09098';
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  if (k === 'cheek') {
    ctx.moveTo(cx + W*0.09, cy + H*0.04);
    ctx.lineTo(cx + W*0.14, cy + H*0.09);
  } else if (k === 'brow') {
    ctx.moveTo(cx - W*0.12, cy - H*0.11);
    ctx.lineTo(cx - W*0.08, cy - H*0.06);
  } else if (k === 'lip') {
    ctx.moveTo(cx - W*0.02, cy + H*0.14);
    ctx.lineTo(cx + W*0.03, cy + H*0.20);
  } else if (k === 'nose') {
    ctx.moveTo(cx - W*0.03, cy + H*0.05);
    ctx.lineTo(cx + W*0.04, cy + H*0.10);
  } else if (k === 'eye') {
    ctx.moveTo(cx - W*0.14, cy - H*0.06);
    ctx.lineTo(cx - W*0.04, cy + H*0.04);
  }
  ctx.stroke();
}

window.FaceRender = {
  randomGenome, mutateGenome, makeAnimState,
  advanceAnim, sampleAnim, renderFace, expandLSystem,
};
})();
