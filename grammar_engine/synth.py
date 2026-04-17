"""Server-side speech synthesizer for Grammar Engine Languages.

Python counterpart to the browser engine.mjs — takes a Language,
picks a grammar variant, expands the L-system into a particle symbol
string, and renders it to a float32 audio buffer. Used by Zoetrope
to drop random-language speech samples onto reel soundtracks.

The synthesis is a simplified mirror of engine.mjs:
- Voiced particles (V, v, n, l): sawtooth glottal source at a
  per-speaker pitch + vibrato, run through two parallel bandpass
  filters at the particle's formant frequencies.
- Unvoiced particles (C, s, p): white/pink noise source through
  the same bandpass pair, shorter envelope.
- Punctuation (. , ?) inserts a pause of the appropriate length.

Determinism: pass an `rng` (random.Random) to get reproducible
output. The speaker profile is drawn from `rng` too, so the same
(language, variant, rng-seed) tuple produces the same WAV.
"""

import io
import math
import random
import struct
import wave

import numpy as np


SAMPLE_RATE = 22050

PUNCT_DUR = {
    '.': 0.12,
    ',': 0.28,
    '?': 0.35,
    '!': 0.18,
    ' ': 0.05,
}


def _random_speaker(rng):
    """A per-utterance speaker profile. Formant shift, base pitch,
    speech rate, vibrato. All sampled inside human-ish ranges."""
    return {
        'pitch':          rng.uniform(110.0, 240.0),
        'formant_shift':  rng.uniform(0.85, 1.18),
        'rate':           rng.uniform(0.85, 1.15),
        'vibrato_hz':     rng.uniform(4.0, 7.0),
        'vibrato_depth':  rng.uniform(0.01, 0.04),
        'breathiness':    rng.uniform(0.25, 0.75),
    }


def _bandpass(signal, center_start, center_end, q, sr):
    """Time-varying 2nd-order bandpass via a simple biquad whose
    coefficients are recomputed each sample from a linearly
    interpolated center frequency. Cheap and OK-sounding for the
    lengths we're rendering (≤ 250ms)."""
    n = len(signal)
    if n == 0:
        return signal
    out = np.zeros_like(signal)
    x1 = x2 = y1 = y2 = 0.0
    center_start = max(30.0, float(center_start))
    center_end = max(30.0, float(center_end))
    q = max(0.5, float(q))
    for i in range(n):
        frac = i / max(1, n - 1)
        f0 = center_start + (center_end - center_start) * frac
        f0 = max(30.0, min(sr * 0.45, f0))
        w0 = 2.0 * math.pi * f0 / sr
        cos_w0 = math.cos(w0)
        alpha = math.sin(w0) / (2.0 * q)
        b0 =  alpha
        b1 =  0.0
        b2 = -alpha
        a0 =  1.0 + alpha
        a1 = -2.0 * cos_w0
        a2 =  1.0 - alpha
        x0 = signal[i]
        y0 = (b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2) / a0
        out[i] = y0
        x2, x1 = x1, x0
        y2, y1 = y1, y0
    return out


def _envelope(n, shape, sr):
    """ADSR-ish envelope per shape, length n samples."""
    if n <= 2:
        return np.ones(n, dtype=np.float32) * 0.6
    t = np.arange(n) / sr
    total = t[-1] if t[-1] > 0 else 1e-3
    env = np.zeros(n, dtype=np.float32)
    if shape in ('vowel', 'nasal', 'liquid'):
        a = min(0.018, total * 0.25)
        r = min(0.025, total * 0.3)
        attack_n  = max(1, int(a * sr))
        release_n = max(1, int(r * sr))
        sustain_n = max(0, n - attack_n - release_n)
        env[:attack_n] = np.linspace(0.001, 1.0, attack_n)
        env[attack_n:attack_n + sustain_n] = 1.0
        env[attack_n + sustain_n:] = np.linspace(1.0, 0.001, n - attack_n - sustain_n)
    elif shape == 'plosive':
        attack_n = max(1, int(0.004 * sr))
        env[:attack_n] = np.linspace(0.001, 1.0, attack_n)
        decay = np.linspace(1.0, 0.001, n - attack_n) ** 1.6
        env[attack_n:] = decay
    else:
        attack_n = max(1, int(0.008 * sr))
        env[:attack_n] = np.linspace(0.001, 1.0, attack_n)
        decay = np.linspace(1.0, 0.001, n - attack_n) ** 1.2
        env[attack_n:] = decay
    return env


def _render_particle(pp, speaker, rng, sr=SAMPLE_RATE):
    """Render one particle dict to a float32 numpy array."""
    fs = speaker['formant_shift']
    rate = speaker['rate']
    dur = max(0.005, float(pp.get('dur', 0.05)) * rate)
    n = max(1, int(dur * sr))
    shape = pp.get('shape', 'vowel')
    gain = float(pp.get('gain', 0.6))
    voiced = bool(pp.get('voiced', False))

    bp1s = float(pp.get('bp1Freq', 700)) * fs
    bp1e = float(pp.get('bp1End', bp1s)) * fs
    bp1q = float(pp.get('bp1Q', 6))
    bp2s = float(pp.get('bp2Freq', 1500)) * fs
    bp2e = float(pp.get('bp2End', bp2s)) * fs
    bp2q = float(pp.get('bp2Q', 6))

    # Source signal
    t = np.arange(n) / sr
    if voiced:
        # Sawtooth at pitch with tiny vibrato. Cheap additive-less
        # sawtooth via the naive 2*(t*f - floor(t*f + 0.5)) formula.
        f0 = speaker['pitch']
        vib = speaker['vibrato_depth'] * np.sin(2 * math.pi * speaker['vibrato_hz'] * t)
        freq = f0 * (1.0 + vib)
        phase = np.cumsum(freq) * 2 * math.pi / sr
        glottal = 2.0 * (phase / (2 * math.pi) - np.floor(phase / (2 * math.pi) + 0.5))
        breath = speaker['breathiness']
        noise = rng.random()  # advance rng
        source = (1.0 - 0.35 * breath) * glottal \
                 + 0.35 * breath * (np.random.default_rng(int(noise * 2**31)).standard_normal(n))
    else:
        # Pink-ish noise: filtered white noise. Cheap approx is just
        # white noise; the bandpass handles tone-shaping.
        seed = rng.randrange(1, 2**31)
        source = np.random.default_rng(seed).standard_normal(n).astype(np.float32)

    # Parallel bandpass pair
    a = _bandpass(source.astype(np.float64), bp1s, bp1e, bp1q, sr)
    b = _bandpass(source.astype(np.float64), bp2s, bp2e, bp2q, sr)
    mixed = (a + b).astype(np.float32)

    # Envelope + gain
    env = _envelope(n, shape, sr)
    out = (mixed * env * gain).astype(np.float32)

    # Soft-clip to keep DC-less, bounded output.
    out = np.tanh(out * 0.9) * 0.9
    return out


def _pick_variant(language, rng):
    """Pick one (category, variant) pair from the language's spec."""
    variants = list(language.variants())
    if not variants:
        return None
    cat, var, axiom, iters, rules = rng.choice(variants)
    return cat, var


def expand_symbols(language, category=None, variant=None, rng=None,
                   max_len=80):
    """Return the symbol string (e.g. 'CVCV.CVCV,') for an expanded
    variant. If category/variant are None, pick randomly. Returns ''
    if the language has no grammars."""
    if rng is None:
        rng = random.Random()
    if category is None or variant is None:
        pick = _pick_variant(language, rng)
        if pick is None:
            return ''
        category, variant = pick
    return language.expand_variant(category, variant, max_len=max_len)


def _ensure_spec(language):
    """Return the language's spec — if empty, regenerate in-memory
    from the language's seed so every Language is playable even
    when its stored spec is a stub."""
    spec = language.spec or {}
    if spec.get('particles') and spec.get('grammars'):
        return spec
    from .seed_gen import generate_spec
    return generate_spec(int(language.seed or language.pk))


def synthesize_utterance(language, category=None, variant=None,
                         rng=None, sample_rate=SAMPLE_RATE,
                         max_symbols=80):
    """Render a single utterance from `language`. Returns a float32
    mono numpy array. Returns np.zeros(1) on any failure so callers
    can still concatenate."""
    if rng is None:
        rng = random.Random()

    spec = _ensure_spec(language)
    particles = spec.get('particles') or []
    grammars = spec.get('grammars') or {}
    if not particles or not grammars:
        return np.zeros(1, dtype=np.float32)

    # Expand from the (possibly regenerated) spec rather than the
    # stored language object, since an empty stored spec would
    # produce an empty string.
    if category is None or variant is None:
        cats = list(grammars.keys())
        if not cats:
            return np.zeros(1, dtype=np.float32)
        category = rng.choice(cats)
        cat = grammars.get(category, {}) or {}
        variants = list((cat.get('variants') or {}).keys())
        if not variants:
            return np.zeros(1, dtype=np.float32)
        variant = rng.choice(variants)

    cat = grammars.get(category, {}) or {}
    axiom = cat.get('axiom', 'S')
    iters = int(cat.get('iterations', 4) or 4)
    rules = (cat.get('variants') or {}).get(variant) or {}
    # Normalize list-valued rules down to first choice (mirror of
    # Language.variants()).
    norm_rules = {}
    for k, v in rules.items():
        if isinstance(v, list):
            v = v[0] if v else ''
        if isinstance(v, str):
            norm_rules[k] = v

    from .models import _expand
    symbols = _expand(axiom, norm_rules, iters, max_len=max_symbols)
    if not symbols:
        return np.zeros(1, dtype=np.float32)

    # Bin particles by type for quick lookup
    by_type = {}
    for pp in particles:
        by_type.setdefault(pp.get('type'), []).append(pp)

    speaker = _random_speaker(rng)

    chunks = []
    for ch in symbols:
        if ch in PUNCT_DUR:
            n = int(PUNCT_DUR[ch] * speaker['rate'] * sample_rate)
            chunks.append(np.zeros(n, dtype=np.float32))
            continue
        pool = by_type.get(ch) or []
        if not pool:
            continue
        pp = rng.choice(pool)
        chunks.append(_render_particle(pp, speaker, rng, sr=sample_rate))

    if not chunks:
        return np.zeros(1, dtype=np.float32)
    return np.concatenate(chunks)


def float_to_wav_bytes(audio, sample_rate=SAMPLE_RATE, channels=1):
    """Encode a float32 numpy array (mono or (2,N) stereo) as WAV
    bytes. Clips to [-1,1] before quantizing to 16-bit PCM."""
    if audio.ndim == 1:
        data = audio
        channels = 1
    else:
        # (channels, n) → interleaved
        data = audio.T.reshape(-1)
        channels = audio.shape[0]
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def build_speech_track(duration_s, sample_rate=SAMPLE_RATE, sample_count=8,
                       languages=None, rng=None, volume=0.7):
    """Compose a full speech soundtrack of `duration_s` seconds by
    placing `sample_count` random utterances from random Languages
    at random times. Returns float32 mono array of len(duration_s*sr).

    If `languages` is None, a random sample is drawn from every
    Language in the DB. Falls back to silence if no Language has a
    usable spec.
    """
    from .models import Language

    if rng is None:
        rng = random.Random()
    total_n = int(duration_s * sample_rate)
    track = np.zeros(total_n, dtype=np.float32)

    if languages is None:
        languages = list(Language.objects.all().order_by('?')[:sample_count * 3])
    if not languages:
        return track

    for _ in range(sample_count):
        lang = rng.choice(languages)
        u_rng = random.Random(rng.randrange(1, 2**31))
        utt = synthesize_utterance(lang, rng=u_rng, sample_rate=sample_rate)
        if utt.size < 2:
            continue
        # Place at a random time; allow the tail to run off the end.
        start = rng.randint(0, max(0, total_n - 1))
        end = min(total_n, start + utt.size)
        n = end - start
        if n <= 0:
            continue
        track[start:end] += utt[:n] * volume

    # Peak-normalize softly so the loudest moment doesn't clip
    peak = float(np.max(np.abs(track))) or 1.0
    if peak > 0.98:
        track *= 0.98 / peak
    return track
