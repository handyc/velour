// doom_ca/music.js — CA-driven music engine.  Port of officerpg
// ev88's musicCA/metaCA system, retargeted at the doom_ca pact rule
// so the same CA that generates the visible world also generates the
// soundtrack.  Drop in via:
//
//   <script src="engine.js"></script>
//   <script src="music.js"></script>
//
// then from your game runtime:
//
//   DoomMusic.setRuleTable(rule)        // Uint8Array(16384) — pact rule
//   DoomMusic.toggle()                  // start/stop, returns new state
//   DoomMusic.cycleStyle()              // advance to next meter
//   DoomMusic.setStyleIndex(i)
//   DoomMusic.updateSignals({           // each tick, gameplay signals
//     hp, ammo, hasShotgun,
//     wallAdj,                          // 0..6 walls around player
//     nearestMonsterDist,               // hex-distance to closest
//     monstersInView,                   // count
//   });
//
// Architecture mirrors officerpg ev88:
// - Two 64×64 hex CAs (score + conductor), both ticking under the
//   pact's 16,384-entry rule via engine.js tickRule.
// - Conductor steps 1/8 as fast as the score; reads pick chord root,
//   per-voice gain, timbre source.
// - 8 voices × N-steps-per-bar gain matrix from MUSIC_STYLES table
//   (16 hand-crafted cultural meters).
// - Wavetable timbre packed from CA cells: 4 cells (2 bits each) →
//   one 8-bit sample, single-cycle WT looped at note frequency.
// - Stereo split: score on L, conductor on R.
// - Mood smoother: doom_ca-specific signals drive pitch + intensity
//   offsets (low HP + cornered = darker; open + safe = brighter).
(function (global) {
  'use strict';

  // ── Constants ───────────────────────────────────────────────
  var MUSIC_W = 64, MUSIC_H = 64;
  var MUSIC_WT_LEN  = (MUSIC_W * MUSIC_H) >> 2;          // 1024
  var MUSIC_VOICES  = 8;
  var MUSIC_BASE_FREQ      = 55;
  var MUSIC_LOOK_AHEAD_S   = 3.5;
  var MUSIC_SCHED_MS       = 100;
  var MUSIC_CELL_TO_SEMI   = [null, 0, 3, 7];            // rest, root, m3, 5
  var META_BARS_PER_STEP   = 8;
  var META_VOICE_ROW       = 32;
  var META_TIMBRE_R        = 32;
  var META_TIMBRE_C        = 32;
  var META_GAIN_MUL        = [0.0, 0.5, 1.0, 1.4];
  var META_ROOT_SEMI       = [0, 5, -3, 7];              // i, IV, vi, V in A-minor
  var MUSIC_MOOD_ALPHA     = 0.06;                       // doom_ca turns are slower than 60 fps; faster mood

  // 16 hand-crafted cultural meters from officerpg ev88, verbatim.
  // Each entry: { name, steps, stepDur (seconds), gain[steps][8] }.
  var MUSIC_STYLES = [
    { name: 'common (4/4)', steps: 8, stepDur: 0.25, gain: [
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
      [1, 1, 1, 1, 1, 1, 1, 1],
    ]},
    { name: 'waltz (3/4)', steps: 6, stepDur: 0.20, gain: [
      [2.5, 2.5, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.5, 1.5, 1.5, 1.5, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.5, 1.5, 1.5, 1.5, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
    ]},
    { name: 'Chinese (ping-pong)', steps: 8, stepDur: 0.24, gain: [
      [2.2, 2.2, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 0.8, 0.8, 0.8, 0.8, 0.7, 0.7],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [2.2, 2.2, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 0.8, 0.8, 0.8, 0.8, 0.7, 0.7],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]},
    { name: 'Indian (Keherwa 8/4)', steps: 8, stepDur: 0.21, gain: [
      [2.5, 2.5, 1.2, 1.2, 0.0, 0.0, 1.5, 1.5],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.0, 1.0, 0.8, 0.8, 0.8, 0.8],
      [0.0, 0.0, 0.5, 0.5, 0.0, 0.0, 0.4, 0.4],
      [1.5, 1.5, 0.6, 0.6, 0.0, 0.0, 1.0, 1.0],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.0, 1.0, 0.8, 0.8, 0.8, 0.8],
      [0.0, 0.0, 0.5, 0.5, 0.0, 0.0, 0.4, 0.4],
    ]},
    { name: 'Russian (Trepak)', steps: 8, stepDur: 0.17, gain: [
      [2.8, 2.8, 1.4, 1.4, 1.4, 1.4, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7, 0.7],
      [1.6, 1.6, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7, 0.7],
      [2.8, 2.8, 1.4, 1.4, 1.4, 1.4, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7, 0.7],
      [1.6, 1.6, 1.2, 1.2, 1.2, 1.2, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7, 0.7],
    ]},
    { name: 'Bossa Nova', steps: 8, stepDur: 0.22, gain: [
      [2.0, 2.0, 0.6, 0.6, 0.6, 0.6, 1.4, 1.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 0.6, 0.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.4, 1.4],
      [0.0, 0.0, 0.6, 0.6, 0.6, 0.6, 0.0, 0.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]},
    { name: 'Pow-wow heartbeat', steps: 4, stepDur: 0.32, gain: [
      [3.2, 3.2, 0.0, 0.0, 0.0, 0.0, 1.4, 1.4],
      [1.4, 1.4, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
      [1.4, 1.4, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
    ]},
    { name: 'African 12/8', steps: 12, stepDur: 0.16, gain: [
      [2.4, 2.4, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 0.4, 0.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.4],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 0.6, 0.6],
      [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.4, 0.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
    ]},
    { name: 'Celtic jig (6/8)', steps: 6, stepDur: 0.18, gain: [
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 1.5, 1.5],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
      [1.8, 1.8, 0.0, 0.0, 0.0, 0.0, 1.4, 1.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    ]},
    { name: 'Maqsum (Arabic)', steps: 8, stepDur: 0.20, gain: [
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 1.4, 1.4],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 0.7, 0.7],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 0.7, 0.7],
      [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 0.7, 0.7],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]},
    { name: 'Japanese (5/4)', steps: 5, stepDur: 0.30, gain: [
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.8],
      [0.0, 0.0, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.8],
      [0.0, 0.0, 1.2, 1.2, 1.2, 1.2, 1.0, 1.0],
    ]},
    { name: 'Flamenco (Soleá 12)', steps: 12, stepDur: 0.18, gain: [
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [2.6, 2.6, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [0.0, 0.0, 1.4, 1.4, 1.4, 1.4, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5],
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 1.6, 1.6],
    ]},
    { name: 'Reggae skank', steps: 8, stepDur: 0.22, gain: [
      [2.4, 2.4, 0.0, 0.0, 0.0, 0.0, 0.8, 0.8],
      [0.0, 0.0, 1.6, 1.6, 1.6, 1.6, 1.4, 1.4],
      [0.0, 0.0, 1.2, 1.2, 1.2, 1.2, 0.9, 0.9],
      [0.0, 0.0, 1.6, 1.6, 1.6, 1.6, 1.4, 1.4],
      [2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.8, 0.8],
      [0.0, 0.0, 1.6, 1.6, 1.6, 1.6, 1.4, 1.4],
      [0.0, 0.0, 1.2, 1.2, 1.2, 1.2, 0.9, 0.9],
      [0.0, 0.0, 1.6, 1.6, 1.6, 1.6, 1.4, 1.4],
    ]},
    { name: 'Tango', steps: 8, stepDur: 0.22, gain: [
      [2.6, 2.6, 0.0, 0.0, 0.0, 0.0, 1.4, 1.4],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.2, 1.2, 1.2, 1.2, 0.9, 0.9],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0],
      [2.2, 2.2, 0.0, 0.0, 0.0, 0.0, 1.2, 1.2],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]},
    { name: 'Doom march (2/4 driving)', steps: 8, stepDur: 0.15, gain: [
      // E1M1-ish — fast 4/4 with bass on every beat, lead syncopated.
      [3.0, 3.0, 0.0, 0.0, 1.0, 1.0, 1.4, 1.4],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.0, 0.0],
      [2.4, 2.4, 0.0, 0.0, 1.0, 1.0, 1.2, 1.2],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.8, 0.8],
      [3.0, 3.0, 0.0, 0.0, 1.0, 1.0, 1.4, 1.4],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.0, 0.0],
      [2.4, 2.4, 0.0, 0.0, 1.0, 1.0, 1.2, 1.2],
      [0.0, 0.0, 0.6, 0.6, 0.0, 0.0, 0.8, 0.8],
    ]},
    { name: 'Ambient drift (4/4 slow)', steps: 4, stepDur: 0.60, gain: [
      // Spacious — bass anchor, lead pads only, no mid percussion.
      [1.6, 1.6, 0.0, 0.0, 0.0, 0.0, 0.8, 0.8],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
      [1.2, 1.2, 0.0, 0.0, 0.0, 0.0, 0.7, 0.7],
      [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6],
    ]},
  ];

  var MUSIC_VOICE_CFG = [
    { octave: 1, dec: 1.6, vol: 0.30 },
    { octave: 1, dec: 1.6, vol: 0.28 },
    { octave: 2, dec: 1.4, vol: 0.22 },
    { octave: 2, dec: 1.4, vol: 0.22 },
    { octave: 3, dec: 1.2, vol: 0.18 },
    { octave: 3, dec: 1.2, vol: 0.18 },
    { octave: 4, dec: 1.0, vol: 0.16 },
    { octave: 4, dec: 1.0, vol: 0.16 },
  ];

  // ── State ───────────────────────────────────────────────────
  var audioCtx = null;
  var musicMaster = null, musicShelf = null, musicComp = null;
  var musicLDest = null, musicRDest = null, musicStereo = true;
  var musicCA = null, musicCABuf = null;
  var metaCA  = null, metaCABuf  = null;
  var musicCAGen = 0, metaCAGen = 0;
  var musicWtCache = null, musicWtKey = '';
  var musicBarCount = 0, musicNextBarT = 0;
  var musicSchedTimer = null;
  var musicWorker = null;
  var musicOn = false;
  var musicStyle = 0;
  var ruleTable = null;       // Uint8Array(16384) — pact rule
  var musicMoodSemi = 0;
  var musicMoodIntensity = 1.0;

  // ── Helpers ─────────────────────────────────────────────────
  function mulberry32 (seed) {
    var s = seed >>> 0;
    return function () {
      s = (s + 0x6D2B79F5) >>> 0;
      var t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 0x100000000;
    };
  }

  function seedCAGrid (seedU32) {
    var rng = mulberry32(seedU32 | 1);
    var g = new Uint8Array(MUSIC_W * MUSIC_H);
    for (var i = 0; i < g.length; i++) g[i] = (rng() * 4) | 0;
    return g;
  }

  // Tick a 64×64 CA under the pact rule using engine.js's tickRule.
  function tickCA (which) {
    if (!ruleTable) return;
    var E = global.DoomCAEngine;
    if (which === 'score') {
      E.tickRule(musicCA, musicCABuf, MUSIC_W, ruleTable);
      var t = musicCA; musicCA = musicCABuf; musicCABuf = t;
      musicCAGen++;
    } else {
      E.tickRule(metaCA, metaCABuf, MUSIC_W, ruleTable);
      var t2 = metaCA; metaCA = metaCABuf; metaCABuf = t2;
      metaCAGen++;
    }
  }

  function buildWavetable (ctx, src) {
    var buf = ctx.createBuffer(1, MUSIC_WT_LEN, ctx.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < MUSIC_WT_LEN; i++) {
      var j = i << 2;
      var b = ((src[j]     & 3) << 6) |
              ((src[j + 1] & 3) << 4) |
              ((src[j + 2] & 3) << 2) |
              ( src[j + 3] & 3);
      data[i] = (b - 128) / 128;
    }
    return buf;
  }

  function scheduleNote (ctx, wt, freq, startT, durSecs, vol, dest) {
    var src = ctx.createBufferSource();
    src.buffer = wt;
    src.loop = true;
    src.playbackRate.value = freq * MUSIC_WT_LEN / ctx.sampleRate;
    var env = ctx.createGain();
    var FLOOR = 0.0001;
    env.gain.setValueAtTime(FLOOR, startT);
    env.gain.exponentialRampToValueAtTime(vol,  startT + 0.005);
    env.gain.exponentialRampToValueAtTime(FLOOR, startT + durSecs);
    src.connect(env).connect(dest || musicMaster);
    src.start(startT);
    src.stop(startT + durSecs + 0.02);
  }

  function scheduleBar (ctx, barStartT) {
    var timbreCell = metaCA[META_TIMBRE_R * MUSIC_W + META_TIMBRE_C] & 3;
    var useMeta = timbreCell >= 2;
    var wtSrc = useMeta ? metaCA : musicCA;
    var wtKey = (useMeta ? 'm' : 's') + ':' + (useMeta ? metaCAGen : musicCAGen);
    var wt;
    if (musicWtCache && musicWtKey === wtKey) {
      wt = musicWtCache;
    } else {
      wt = buildWavetable(ctx, wtSrc);
      musicWtCache = wt;
      musicWtKey = wtKey;
    }
    var rootCell = metaCA[0] & 3;
    var moodOffset = Math.round(musicMoodSemi);
    var rootSemi = META_ROOT_SEMI[rootCell] + moodOffset;
    var moodGain = musicMoodIntensity;
    if (moodGain < 0.6) moodGain = 0.6;
    if (moodGain > 1.4) moodGain = 1.4;
    var style = MUSIC_STYLES[musicStyle] || MUSIC_STYLES[0];
    var stepsThisBar = style.steps;
    var stepDur = style.stepDur;
    var styleGain = style.gain;
    var lDest = musicStereo ? musicLDest : musicMaster;
    var rDest = musicStereo ? musicRDest : musicMaster;
    var R_GAIN = 0.75;
    for (var v = 0; v < MUSIC_VOICES; v++) {
      var cfg = MUSIC_VOICE_CFG[v];
      var row = (v * (MUSIC_H / MUSIC_VOICES)) | 0;
      var gainCol = (v * (MUSIC_W / MUSIC_VOICES)) | 0;
      var gainCell = metaCA[META_VOICE_ROW * MUSIC_W + gainCol] & 3;
      var gainMul = META_GAIN_MUL[gainCell];
      if (gainMul === 0) continue;
      for (var s = 0; s < stepsThisBar; s++) {
        var col = (s * (MUSIC_W / stepsThisBar)) | 0;
        var cellL = musicCA[row * MUSIC_W + col] & 3;
        var semiL = MUSIC_CELL_TO_SEMI[cellL];
        var noteStart = barStartT + s * stepDur;
        var noteDur = stepDur * cfg.dec;
        var meterGain = styleGain[s][v];
        if (meterGain === 0) continue;
        if (semiL !== null) {
          var freqL = MUSIC_BASE_FREQ *
                      Math.pow(2, cfg.octave + (semiL + rootSemi) / 12);
          scheduleNote(ctx, wt, freqL, noteStart, noteDur,
                       cfg.vol * gainMul * moodGain * meterGain, lDest);
        }
        if (musicStereo) {
          var cellR = metaCA[row * MUSIC_W + col] & 3;
          var semiR = MUSIC_CELL_TO_SEMI[cellR];
          if (semiR !== null) {
            var freqR = MUSIC_BASE_FREQ *
                        Math.pow(2, cfg.octave + (semiR + rootSemi) / 12);
            scheduleNote(ctx, wt, freqR, noteStart, noteDur,
                         cfg.vol * gainMul * moodGain * meterGain * R_GAIN,
                         rDest);
          }
        }
      }
    }
  }

  function schedulerTick () {
    if (!musicOn || !audioCtx) return;
    var now = audioCtx.currentTime;
    var style = MUSIC_STYLES[musicStyle] || MUSIC_STYLES[0];
    var barSecs = style.steps * style.stepDur;
    if (musicNextBarT < now) {
      while (musicNextBarT < now) {
        tickCA('score');
        musicBarCount++;
        if ((musicBarCount % META_BARS_PER_STEP) === 0) tickCA('meta');
        musicNextBarT += barSecs;
      }
      musicNextBarT = now + 0.05;
    }
    while (musicNextBarT < now + MUSIC_LOOK_AHEAD_S) {
      scheduleBar(audioCtx, musicNextBarT);
      tickCA('score');
      musicBarCount++;
      if ((musicBarCount % META_BARS_PER_STEP) === 0) tickCA('meta');
      musicNextBarT += barSecs;
    }
  }

  function ensureWorker () {
    if (musicWorker) return musicWorker;
    try {
      var src = "let iv=null;onmessage=(e)=>{" +
        "if(e.data==='start'){if(!iv)iv=setInterval(()=>postMessage('t')," +
        MUSIC_SCHED_MS + ");}" +
        "else if(e.data==='stop'){if(iv){clearInterval(iv);iv=null;}}};";
      var blob = new Blob([src], { type: 'application/javascript' });
      var url = URL.createObjectURL(blob);
      var w = new Worker(url);
      w.onmessage = schedulerTick;
      musicWorker = w;
      return w;
    } catch (e) {
      musicWorker = null;
      return null;
    }
  }

  // ── Public API ──────────────────────────────────────────────
  function setRuleTable (rule) {
    if (rule && rule.length === 16384) ruleTable = rule;
  }

  function start () {
    if (musicOn) return true;
    if (!ruleTable) {
      console.warn('DoomMusic: no ruleTable set');
      return false;
    }
    if (!audioCtx) {
      var Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return false;
      audioCtx = new Ctx();
    }
    if (audioCtx.state === 'suspended') audioCtx.resume();

    musicMaster = audioCtx.createGain();
    musicMaster.gain.value = 0.55;
    var chainTail = musicMaster;
    if (typeof audioCtx.createBiquadFilter === 'function') {
      musicShelf = audioCtx.createBiquadFilter();
      musicShelf.type = 'highshelf';
      var t = audioCtx.currentTime;
      musicShelf.frequency.setValueAtTime(4000, t);
      musicShelf.gain.setValueAtTime(-8, t);
      chainTail.connect(musicShelf);
      chainTail = musicShelf;
    }
    if (typeof audioCtx.createDynamicsCompressor === 'function') {
      musicComp = audioCtx.createDynamicsCompressor();
      var t2 = audioCtx.currentTime;
      musicComp.threshold.setValueAtTime(-22, t2);
      musicComp.knee.setValueAtTime(18, t2);
      musicComp.ratio.setValueAtTime(6, t2);
      musicComp.attack.setValueAtTime(0.005, t2);
      musicComp.release.setValueAtTime(0.20, t2);
      chainTail.connect(musicComp);
      musicComp.connect(audioCtx.destination);
    } else {
      chainTail.connect(audioCtx.destination);
    }
    if (typeof audioCtx.createStereoPanner === 'function') {
      musicLDest = audioCtx.createStereoPanner();
      musicLDest.pan.value = -1.0;
      musicLDest.connect(musicMaster);
      musicRDest = audioCtx.createStereoPanner();
      musicRDest.pan.value = +1.0;
      musicRDest.connect(musicMaster);
      musicStereo = true;
    } else {
      musicLDest = musicRDest = musicMaster;
      musicStereo = false;
    }
    musicCA    = seedCAGrid((Math.random() * 0xffffffff) | 0);
    musicCABuf = new Uint8Array(MUSIC_W * MUSIC_H);
    metaCA     = seedCAGrid(((Math.random() * 0xffffffff) | 0) ^ 0xdeadbeef);
    metaCABuf  = new Uint8Array(MUSIC_W * MUSIC_H);
    musicCAGen = 0; metaCAGen = 0;
    musicWtCache = null; musicWtKey = '';
    musicBarCount = 0;
    musicNextBarT = audioCtx.currentTime + 0.15;
    musicOn = true;
    schedulerTick();
    var w = ensureWorker();
    if (w) {
      w.postMessage('start');
      musicSchedTimer = 'worker';
    } else {
      musicSchedTimer = setInterval(schedulerTick, MUSIC_SCHED_MS);
    }
    return true;
  }

  function stop () {
    if (!musicOn) return;
    musicOn = false;
    if (musicSchedTimer === 'worker') {
      if (musicWorker) musicWorker.postMessage('stop');
    } else if (musicSchedTimer) {
      clearInterval(musicSchedTimer);
    }
    musicSchedTimer = null;
    if (musicMaster && audioCtx) {
      var t = audioCtx.currentTime;
      musicMaster.gain.setValueAtTime(musicMaster.gain.value, t);
      musicMaster.gain.exponentialRampToValueAtTime(0.0001, t + 0.3);
    }
  }

  function toggle () { if (musicOn) stop(); else start(); return musicOn; }

  function cycleStyle () {
    musicStyle = (musicStyle + 1) % MUSIC_STYLES.length;
    return musicStyle;
  }
  function setStyleIndex (i) {
    musicStyle = ((i | 0) % MUSIC_STYLES.length + MUSIC_STYLES.length) %
                  MUSIC_STYLES.length;
  }

  function getStyleName () {
    return (MUSIC_STYLES[musicStyle] || MUSIC_STYLES[0]).name;
  }
  function getStyleIdx () { return musicStyle; }
  function getStyleCount () { return MUSIC_STYLES.length; }
  function isOn () { return musicOn; }

  // doom_ca-specific multi-signal mood mapping.  Each signal is
  // optional; missing fields default to neutral.  semi target:
  //   open + healthy + safe  →  +3..+4 (bright major-ish)
  //   cornered + low HP + threat  →  -5..-4 (dark, drop-tuned)
  // intensity target tracks combat density.
  function updateSignals (s) {
    if (!musicOn) return;
    var hp = (s.hp != null) ? Math.max(0, s.hp) : 100;
    var hpRatio = Math.min(1, hp / 100);
    var ammo = (s.ammo != null) ? s.ammo : 0;
    var wallAdj = (s.wallAdj != null) ? s.wallAdj : 0;        // 0..6
    var wallOpenness = 1 - wallAdj / 6;
    var nearestDist = (s.nearestMonsterDist != null)
                      ? s.nearestMonsterDist : 99;
    var threatProx = Math.max(0, 1 - nearestDist / 10);
    var inView = (s.monstersInView != null) ? s.monstersInView : 0;

    // Pitch target: brighter when open & healthy, darker when threatened.
    var tgtSemi = Math.round(
      -3 + 5 * hpRatio + 3 * wallOpenness - 4 * threatProx
    );
    musicMoodSemi += (tgtSemi - musicMoodSemi) * MUSIC_MOOD_ALPHA;

    // Intensity target: louder + denser when combat is close.
    var tgtInt = 0.7 + 0.4 * Math.min(1, inView / 8) + 0.3 * threatProx
                 - 0.2 * (1 - hpRatio);
    if (tgtInt < 0.6) tgtInt = 0.6;
    if (tgtInt > 1.4) tgtInt = 1.4;
    musicMoodIntensity += (tgtInt - musicMoodIntensity) * MUSIC_MOOD_ALPHA;
  }

  global.DoomMusic = {
    setRuleTable: setRuleTable,
    start: start, stop: stop, toggle: toggle,
    cycleStyle: cycleStyle, setStyleIndex: setStyleIndex,
    getStyleName: getStyleName, getStyleIdx: getStyleIdx,
    getStyleCount: getStyleCount, isOn: isOn,
    updateSignals: updateSignals,
  };
})(typeof window !== 'undefined' ? window : globalThis);
