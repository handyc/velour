"""Rolling-key authenticated envelope keyed by current CA state.

Both parties holding the same pact derive the same 32-byte
``ChaCha20-Poly1305`` key from the pact's full 64-component state
at any generation ``g``. Alice encrypts at her current generation;
Bob decrypts by brute-forcing a small window around his current
generation. AEAD's MAC tells him which generation matched.

Threat model (v1):
- Pact possession = ability to decrypt all envelopes ever sealed
  under it, past, present, and future. There is no forward secrecy.
  An attacker who later compromises a pact-holder's DB can decrypt
  every historical envelope.
- "Expiry" is a client convention: refuse to decrypt outside a
  small window. It is NOT a cryptographic guarantee.
- A future variant (Phase 2) can ratchet the pact's seed forward
  after each transmission to drop old keys irrecoverably.

File format:
    [ magic b'SPENV' (5) | version 0x01 (1) | nonce (12) |
      ciphertext + 16B Poly1305 tag (variable) ]
Total overhead: 34 bytes. No generation hint — the "right now"
property requires the decryptor to discover ``g`` itself.
"""

from __future__ import annotations
import hashlib
import secrets
import struct
from typing import Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from django.utils import timezone

from . import keystream
from .models import Pact


MAGIC = b'SPENV'
VERSION = 1
HEADER_LEN = len(MAGIC) + 1 + 12  # 5 + 1 + 12 = 18

DEFAULT_WINDOW = 20  # ticks; at 180 ms/tick ≈ 3.6 s of clock-skew tolerance


class EnvelopeError(Exception):
    """Decryption failed — either tampered ciphertext, wrong pact,
    or the encryption generation lies outside the search window."""


def _state_at(pact: Pact, generation: int) -> bytes:
    """Get the CA state at ``generation``, working past the
    keystream's per-call ADVANCE_CAP by walking in CAP-sized chunks.

    The per-call cap exists to protect the HTTP /tap endpoint from
    being pinned by a single request. Envelope work runs locally
    and synchronously, so the cap doesn't apply — but the cost
    (pure-Python step at ~50 ms/tick on a 16×16×64 grid) does.
    For an aged pact at generation g, expect ~g × 50 ms of startup
    on the first call after process restart.
    """
    while True:
        try:
            return keystream.get_state_at(pact, generation)
        except keystream.AdvanceCapExceeded:
            cur = keystream._cache_get(pact.id)
            cur_gen = cur[0] if cur else 0
            keystream.get_state_at(pact, cur_gen + keystream.ADVANCE_CAP)


def derive_key(pact: Pact, generation: int) -> bytes:
    """32-byte ChaCha20-Poly1305 key for ``(pact, generation)``.

    Combines the pact-domain separator, the generation index, and a
    SHA-256 hash of the full 64-component CA state at that generation.
    Using *all* components (not just one) means a single-component
    leak — e.g. through the click-to-Automaton export — does not
    weaken the envelope key.
    """
    state = _state_at(pact, generation)
    h = hashlib.sha256()
    h.update(keystream.DOMAIN_ENVELOPE)
    h.update(struct.pack('<Q', generation))
    h.update(state)
    return h.digest()


def current_generation(pact: Pact, *, now=None) -> int:
    """The pact's tick index at wall-clock ``now`` (defaults to UTC now).

    Envelope only makes sense under ``clock_model='synced'`` —
    local-clock pacts diverge between parties by design, which
    would defeat the protocol.
    """
    if pact.clock_model != 'synced':
        raise EnvelopeError(
            f"envelope requires Pact.clock_model='synced'; "
            f"this pact uses {pact.clock_model!r}")
    if now is None:
        now = timezone.now()
    elapsed = (now - pact.launch_time).total_seconds() * 1000.0
    return max(0, int(elapsed // pact.tick_ms))


def seal(pact: Pact, plaintext: bytes, *,
         generation: int | None = None,
         now=None) -> bytes:
    """Encrypt ``plaintext`` under the pact's current envelope key
    (or a caller-specified generation, e.g. for time-capsule sends).

    Returns the full file-format bytes: magic + version + nonce +
    ciphertext-with-tag.
    """
    if generation is None:
        generation = current_generation(pact, now=now)
    key = derive_key(pact, generation)
    nonce = secrets.token_bytes(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, None)
    return MAGIC + bytes([VERSION]) + nonce + ct


def unseal(pact: Pact, sealed: bytes, *,
           window: int = DEFAULT_WINDOW,
           now=None) -> Tuple[bytes, int]:
    """Decrypt ``sealed`` against the pact's current generation
    within ``±window`` ticks. Returns ``(plaintext, generation)``.

    Strategy: derive all candidate keys for ``g ∈ [g_now-window,
    g_now+window]`` in *forward* order (cache-friendly: the
    keystream cache advances one tick at a time, never restarting
    from gen 0), then try decryption attempts in nearest-to-g_now
    order so the common case (small drift) returns quickly.
    """
    if len(sealed) < HEADER_LEN + 16:
        raise EnvelopeError('sealed payload too short')
    if sealed[:len(MAGIC)] != MAGIC:
        raise EnvelopeError('not a spoeqi envelope (bad magic)')
    if sealed[len(MAGIC)] != VERSION:
        raise EnvelopeError(f'unsupported envelope version {sealed[len(MAGIC)]}')

    nonce = sealed[len(MAGIC) + 1 : HEADER_LEN]
    ct = sealed[HEADER_LEN:]

    g_now = current_generation(pact, now=now)
    start = max(0, g_now - window)
    end = g_now + window
    candidates = [(g, derive_key(pact, g)) for g in range(start, end + 1)]
    candidates.sort(key=lambda gk: abs(gk[0] - g_now))

    for g, key in candidates:
        try:
            pt = ChaCha20Poly1305(key).decrypt(nonce, ct, None)
            return pt, g
        except InvalidTag:
            continue

    raise EnvelopeError(
        f'could not unseal within ±{window} of generation {g_now}; '
        f'either wrong pact, tampered ciphertext, or the sender is '
        f'outside the drift window')
