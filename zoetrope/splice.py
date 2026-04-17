"""Splice two Reels into a new Reel.

Two modes:

- `concat`: plain front-to-back concatenation. Whichever reel plays
  first is randomly picked.

- `oscillate`: crossfades back and forth between the two reels in
  sync with a generated distorted sine wave. One reel is "A", the
  other is "B"; at time t, the output frame is a blend
      out = A*(1-w(t)) + B*w(t)
  where w(t) is a [0,1] waveform built from a base sine plus a few
  harmonics and a tanh soft-clip — producing a wobble that mostly
  lives on one side or the other with fast transitions when it
  crosses the middle. The effect is a dream-logic channel flip.

Both modes produce a fresh Reel row and render to mp4 in-place.
"""

import math
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import Reel


def _synth_speech_wav(path, duration_s, sample_count, volume):
    """Build a speech WAV at `path`. Silent fallback — a missing or
    failed audio track shouldn't kill a splice render."""
    try:
        import random as _random

        from grammar_engine import synth

        rng = _random.Random()
        track = synth.build_speech_track(
            duration_s=float(duration_s),
            sample_count=int(sample_count),
            rng=rng,
            volume=float(volume),
        )
        Path(path).write_bytes(synth.float_to_wav_bytes(track))
    except Exception:
        return


def _distorted_sine(n_samples, rng):
    """Generate `n_samples` values in [0,1] along a distorted sine.

    The wave is sum of a base sine at one cycle-per-~1.5-4s plus a few
    randomized harmonics, then run through tanh and normalized.
    Returns a Python list of floats in [0.0, 1.0]."""
    # Base period: somewhere between 0.6 and 3.5 cycles over the reel.
    base_cycles = rng.uniform(0.6, 3.5)
    harmonics = []
    for _ in range(rng.randint(2, 4)):
        harmonics.append((
            rng.uniform(1.5, 5.5),          # multiplier of base
            rng.uniform(0.15, 0.6),          # amplitude
            rng.uniform(0, 2 * math.pi),     # phase
        ))
    distortion = rng.uniform(1.2, 3.0)
    out = []
    raw = []
    for i in range(n_samples):
        t = i / max(1, n_samples - 1)
        v = math.sin(2 * math.pi * base_cycles * t)
        for mult, amp, phase in harmonics:
            v += amp * math.sin(2 * math.pi * base_cycles * mult * t + phase)
        v = math.tanh(v * distortion)
        raw.append(v)
    lo, hi = min(raw), max(raw)
    span = hi - lo if hi > lo else 1.0
    return [(v - lo) / span for v in raw]


def _extract_frames(mp4_path, out_dir, target_fps, label):
    """Pull frames from `mp4_path` at `target_fps` into `out_dir`,
    named `{label}-%05d.png`. Returns the sorted list of paths."""
    pattern = str(out_dir / f'{label}-%05d.png')
    cmd = [
        'ffmpeg', '-y',
        '-i', str(mp4_path),
        '-vf', f'fps={target_fps}',
        pattern,
    ]
    subprocess.run(cmd, capture_output=True)
    return sorted(out_dir.glob(f'{label}-*.png'))


def splice_reels(reel_a, reel_b, mode='concat', rng=None):
    """Build and render a new Reel from `reel_a` + `reel_b`.

    Returns the new Reel. Raises if either input has no rendered mp4
    or if ffmpeg is not on PATH.
    """
    if rng is None:
        rng = random.Random()

    if not reel_a.output or not reel_b.output:
        raise ValueError('Both reels must be rendered before splicing.')
    if shutil.which('ffmpeg') is None:
        raise RuntimeError('ffmpeg not found on PATH.')

    a_path = Path(reel_a.output.path).resolve()
    b_path = Path(reel_b.output.path).resolve()

    fps = max(reel_a.fps, reel_b.fps)
    width = max(reel_a.width, reel_b.width)
    height = max(reel_a.height, reel_b.height)

    now = timezone.now()
    if mode == 'oscillate':
        base_title = f'Oscillating splice · {reel_a.title[:18]} ⇄ {reel_b.title[:18]}'
        duration = max(reel_a.duration_seconds, reel_b.duration_seconds)
    else:
        mode = 'concat'
        base_title = f'Splice · {reel_a.title[:18]} + {reel_b.title[:18]}'
        duration = reel_a.duration_seconds + reel_b.duration_seconds

    # Combine speech: if either parent had speech, the child should too.
    inherited_speech = max(
        reel_a.speech_sample_count or 0,
        reel_b.speech_sample_count or 0,
    )
    # Scale a little for longer outputs so the track doesn't feel empty.
    speech_n = max(inherited_speech, int(round(duration / 2.5)))
    speech_n = min(24, speech_n)

    new_reel = Reel.objects.create(
        title=base_title,
        selection_mode='random',
        fps=fps,
        duration_seconds=float(duration),
        image_count=0,
        width=width,
        height=height,
        status='rendering',
        speech_sample_count=speech_n,
        speech_volume=float(reel_a.speech_volume or reel_b.speech_volume or 0.7),
    )

    try:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            out_path = td_path / 'out.mp4'
            poster_path = td_path / 'poster.jpg'

            # Synthesize a fresh speech track for the whole spliced duration
            # regardless of mode. We always re-encode the video below, so
            # mixing new audio in is simpler than trying to stitch or
            # preserve the parents' audio (which may or may not exist).
            audio_path = None
            if new_reel.speech_sample_count > 0:
                audio_path = td_path / 'speech.wav'
                _synth_speech_wav(
                    audio_path,
                    duration_s=float(duration),
                    sample_count=int(new_reel.speech_sample_count),
                    volume=float(new_reel.speech_volume),
                )
                if not audio_path.exists():
                    audio_path = None

            if mode == 'concat':
                # Random which goes first.
                first, second = (a_path, b_path)
                if rng.random() < 0.5:
                    first, second = second, first
                list_path = td_path / 'concat.txt'
                list_path.write_text(
                    f"file '{first.as_posix()}'\n"
                    f"file '{second.as_posix()}'\n"
                )
                vf = (
                    f'scale={width}:{height}:'
                    'force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,'
                    'setsar=1'
                )
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat', '-safe', '0',
                    '-i', str(list_path),
                ]
                if audio_path is not None:
                    cmd += ['-i', str(audio_path)]
                cmd += [
                    '-vf', vf,
                    '-r', str(fps),
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    '-preset', 'veryfast',
                    '-movflags', '+faststart',
                ]
                if audio_path is not None:
                    cmd += [
                        '-map', '0:v:0', '-map', '1:a:0',
                        '-c:a', 'aac', '-b:a', '128k',
                        '-shortest',
                    ]
                cmd.append(str(out_path))
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(
                        (proc.stderr or 'concat ffmpeg failed')[-1500:])
            else:
                # Oscillating mode: re-sample both reels to the same fps,
                # build a distorted sine mask, then for each frame pick
                # A or B (and occasionally blend them with PIL).
                frames_dir = td_path / 'frames'
                frames_dir.mkdir()
                a_frames = _extract_frames(a_path, frames_dir, fps, 'a')
                b_frames = _extract_frames(b_path, frames_dir, fps, 'b')
                if not a_frames or not b_frames:
                    raise RuntimeError('Could not extract frames from inputs.')
                total = max(len(a_frames), len(b_frames))
                wave = _distorted_sine(total, rng)

                # Build interleaved output frames via PIL.
                from PIL import Image
                out_frames_dir = td_path / 'out_frames'
                out_frames_dir.mkdir()
                for i in range(total):
                    w = wave[i]
                    a_img = Image.open(a_frames[i % len(a_frames)]).convert('RGB')
                    b_img = Image.open(b_frames[i % len(b_frames)]).convert('RGB')
                    if a_img.size != (width, height):
                        a_img = a_img.resize((width, height), Image.BICUBIC)
                    if b_img.size != (width, height):
                        b_img = b_img.resize((width, height), Image.BICUBIC)
                    if w < 0.1:
                        frame = a_img
                    elif w > 0.9:
                        frame = b_img
                    else:
                        frame = Image.blend(a_img, b_img, w)
                    frame.save(out_frames_dir / f'frame-{i:05d}.png', 'PNG')

                cmd = [
                    'ffmpeg', '-y',
                    '-framerate', str(fps),
                    '-i', str(out_frames_dir / 'frame-%05d.png'),
                ]
                if audio_path is not None:
                    cmd += ['-i', str(audio_path)]
                cmd += [
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    '-preset', 'veryfast',
                    '-movflags', '+faststart',
                ]
                if audio_path is not None:
                    cmd += [
                        '-map', '0:v:0', '-map', '1:a:0',
                        '-c:a', 'aac', '-b:a', '128k',
                        '-shortest',
                    ]
                cmd.append(str(out_path))
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(
                        (proc.stderr or 'oscillate ffmpeg failed')[-1500:])

            # Poster
            subprocess.run(
                ['ffmpeg', '-y', '-i', str(out_path),
                 '-vframes', '1', '-q:v', '3', str(poster_path)],
                capture_output=True,
            )

            data = out_path.read_bytes()
            new_reel.output.save(
                f'{new_reel.slug}.mp4', ContentFile(data), save=False)
            if poster_path.exists():
                new_reel.poster.save(
                    f'{new_reel.slug}.jpg',
                    ContentFile(poster_path.read_bytes()),
                    save=False,
                )
            new_reel.size_bytes = len(data)
            new_reel.frames_used = (reel_a.frames_used or 0) + (reel_b.frames_used or 0)
            new_reel.status = 'ready'
            new_reel.status_message = (
                f'Spliced from "{reel_a.title}" + "{reel_b.title}" '
                f'({mode}).'
            )
            new_reel.rendered_at = timezone.now()
            new_reel.save()
    except Exception as exc:
        new_reel.status = 'error'
        new_reel.status_message = str(exc)[-1500:]
        new_reel.save(update_fields=['status', 'status_message'])
        raise

    return new_reel


def pick_two_random_reels(rng=None):
    """Pick two distinct ready Reels at random. Returns (a, b) or None
    if fewer than two ready reels exist."""
    if rng is None:
        rng = random.Random()
    ready = list(Reel.objects.filter(status='ready').exclude(output=''))
    if len(ready) < 2:
        return None
    a = rng.choice(ready)
    rest = [r for r in ready if r.pk != a.pk]
    b = rng.choice(rest)
    return a, b
