"""Tests for spoeqi.envelope — rolling-key AEAD."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from spoeqi.models import Pact
from spoeqi import envelope, keystream


def _make_pact(name='envelope-test', launch_at=None):
    pact = Pact(name=name)
    if launch_at is not None:
        pact.launch_time = launch_at
    pact.save()
    return pact


class _EnvelopeTestBase(TestCase):
    """The keystream cache is process-level; Django TestCase rolls
    back the DB but the cache survives. Test-DB pact IDs get reused
    across tests with different rule_snapshots, which would cause
    stale-state collisions. Clear it before each test."""

    def setUp(self):
        keystream.cache_clear()


class DeriveKeyTest(_EnvelopeTestBase):
    def test_length_and_determinism(self):
        pact = _make_pact()
        k1 = envelope.derive_key(pact, 0)
        k2 = envelope.derive_key(pact, 0)
        self.assertEqual(len(k1), 32)
        self.assertEqual(k1, k2)

    def test_different_generation_differs(self):
        pact = _make_pact()
        self.assertNotEqual(envelope.derive_key(pact, 0),
                            envelope.derive_key(pact, 1))

    def test_different_pact_differs(self):
        a = _make_pact('alice-pact')
        b = _make_pact('bob-pact')
        self.assertNotEqual(envelope.derive_key(a, 0),
                            envelope.derive_key(b, 0))


class CurrentGenerationTest(_EnvelopeTestBase):
    def test_synced_clock_returns_zero_at_launch(self):
        # Pin launch_time = "now" so elapsed ≈ 0.
        pact = _make_pact(launch_at=timezone.now())
        self.assertEqual(envelope.current_generation(pact), 0)

    def test_synced_clock_advances_with_time(self):
        pact = _make_pact(launch_at=timezone.now() - timedelta(seconds=10))
        # tick_ms default = 180 → 10 s ≈ 55 ticks.
        g = envelope.current_generation(pact)
        self.assertGreaterEqual(g, 50)
        self.assertLessEqual(g, 60)

    def test_local_clock_rejected(self):
        pact = _make_pact()
        pact.clock_model = 'local'
        pact.save()
        with self.assertRaises(envelope.EnvelopeError):
            envelope.current_generation(pact)


class SealUnsealRoundTripTest(_EnvelopeTestBase):
    def test_round_trip_at_same_generation(self):
        pact = _make_pact()
        msg = b'the package leaves at midnight'
        sealed = envelope.seal(pact, msg, generation=42)
        # Pin "now" to gen=42 so unseal finds it immediately.
        ms_per_gen = pact.tick_ms
        now = pact.launch_time + timedelta(milliseconds=42 * ms_per_gen)
        pt, g = envelope.unseal(pact, sealed, now=now)
        self.assertEqual(pt, msg)
        self.assertEqual(g, 42)

    def test_round_trip_within_window(self):
        pact = _make_pact()
        msg = b'within window'
        sealed = envelope.seal(pact, msg, generation=100)
        ms = pact.tick_ms
        # Decryptor is at gen 108 — 8 ticks past sender.
        now = pact.launch_time + timedelta(milliseconds=108 * ms)
        pt, g = envelope.unseal(pact, sealed, window=20, now=now)
        self.assertEqual(pt, msg)
        self.assertEqual(g, 100)

    def test_outside_window_fails(self):
        pact = _make_pact()
        sealed = envelope.seal(pact, b'late', generation=100)
        ms = pact.tick_ms
        now = pact.launch_time + timedelta(milliseconds=200 * ms)
        with self.assertRaises(envelope.EnvelopeError):
            envelope.unseal(pact, sealed, window=20, now=now)

    def test_tampered_ciphertext_fails(self):
        pact = _make_pact()
        sealed = bytearray(envelope.seal(pact, b'authenticated', generation=5))
        sealed[-1] ^= 0xFF  # flip the last tag byte
        ms = pact.tick_ms
        now = pact.launch_time + timedelta(milliseconds=5 * ms)
        with self.assertRaises(envelope.EnvelopeError):
            envelope.unseal(pact, bytes(sealed), now=now)

    def test_wrong_pact_fails(self):
        alice = _make_pact('alice-pact')
        bob = _make_pact('bob-pact')
        sealed = envelope.seal(alice, b'for alice eyes only', generation=10)
        ms = alice.tick_ms
        now = alice.launch_time + timedelta(milliseconds=10 * ms)
        with self.assertRaises(envelope.EnvelopeError):
            envelope.unseal(bob, sealed, now=now)

    def test_empty_plaintext(self):
        pact = _make_pact()
        sealed = envelope.seal(pact, b'', generation=0)
        now = pact.launch_time
        pt, g = envelope.unseal(pact, sealed, now=now)
        self.assertEqual(pt, b'')

    def test_large_plaintext(self):
        pact = _make_pact()
        msg = (b'x' * 100_000) + (b'y' * 50_000)
        sealed = envelope.seal(pact, msg, generation=7)
        ms = pact.tick_ms
        now = pact.launch_time + timedelta(milliseconds=7 * ms)
        pt, g = envelope.unseal(pact, sealed, now=now)
        self.assertEqual(pt, msg)


class FormatTest(_EnvelopeTestBase):
    def test_magic_and_version(self):
        pact = _make_pact()
        sealed = envelope.seal(pact, b'hi', generation=0)
        self.assertEqual(sealed[:5], envelope.MAGIC)
        self.assertEqual(sealed[5], envelope.VERSION)

    def test_short_payload_rejected(self):
        pact = _make_pact()
        with self.assertRaises(envelope.EnvelopeError):
            envelope.unseal(pact, b'too short')

    def test_bad_magic_rejected(self):
        pact = _make_pact()
        with self.assertRaises(envelope.EnvelopeError):
            envelope.unseal(pact, b'XXXXX\x01' + b'\x00' * 28)
