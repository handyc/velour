"""Tests for the SealedLex split-process protocol.

These tests run real Concrete circuits, so they're slow (~20-30 s per
test).  Skip the Concrete-heavy ones if `UMBRA_SKIP_FHE=1` is set in
the environment.
"""
import io
import os
import tarfile
import tempfile
import unittest

from django.test import TestCase

from umbra import sealedlex, sealedlex_protocol


SKIP_FHE = os.environ.get('UMBRA_SKIP_FHE') == '1'


SAMPLE_CSV = """form,gloss,language
guru,teacher,Sanskrit
shishya,student,Sanskrit
namaste,greetings,Hindi
"""


@unittest.skipIf(SKIP_FHE, 'set UMBRA_SKIP_FHE=1 to skip Concrete tests')
class ProtocolRoundTripTests(TestCase):
    """The full encrypt → evaluate → decrypt round trip works, and
    the math matches the in-process pipeline."""

    def test_count_class_round_trip(self):
        op = {'op': 'count_class', 'col': 0, 'target': sealedlex.CLASS_VOWEL,
              'dst_col': 3}
        enc = sealedlex_protocol.encrypt(SAMPLE_CSV, op, 'ascii')
        ev  = sealedlex_protocol.evaluate(enc['package_bytes'])
        dec = sealedlex_protocol.decrypt(
            package_bytes=enc['package_bytes'],
            results_bytes=ev['results_bytes'],
            keys_bytes=enc['keys_bytes'],
            original_csv=SAMPLE_CSV,
        )
        grid, _, _ = sealedlex.parse_csv(dec['output_csv'])
        # Header row unchanged; vowel counts in new col 3.
        self.assertEqual(grid[0][0], 'form')
        self.assertEqual(grid[1][3], '2')   # "guru" -> u,u
        self.assertEqual(grid[2][3], '2')   # "shishya" -> i,a
        self.assertEqual(grid[3][3], '3')   # "namaste" -> a,a,e


@unittest.skipIf(SKIP_FHE, 'set UMBRA_SKIP_FHE=1 to skip Concrete tests')
class ProtocolPrivacyTests(TestCase):
    """The privacy property: the evaluate side never has secret-key
    material.  Even if a malicious evaluate process tries to decrypt
    the outputs it produced, it can't."""

    def test_evaluate_side_cannot_decrypt(self):
        from concrete import fhe
        from concrete.fhe.compilation import Client

        op = {'op': 'length', 'col': 0, 'dst_col': 3}
        enc = sealedlex_protocol.encrypt(SAMPLE_CSV, op, 'ascii')
        ev  = sealedlex_protocol.evaluate(enc['package_bytes'])

        # Reach into the package as a malicious evaluate-side would —
        # try to construct a Client from public artefacts only.
        pkg = enc['package_bytes']
        server_zip = None
        with tarfile.open(fileobj=io.BytesIO(pkg), mode='r:gz') as tar:
            for m in tar.getmembers():
                if m.name == 'server.zip':
                    server_zip = tar.extractfile(m).read()
        self.assertIsNotNone(server_zip)

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as fp:
            sp = fp.name
            fp.write(server_zip)
        try:
            attacker_client = Client.load(sp)
        finally:
            os.unlink(sp)

        # The attacker_client has no generated keys.
        self.assertIsNotNone(attacker_client._keys)
        self.assertFalse(attacker_client._keys.are_generated,
                         'evaluate-side client must not have generated keys')

        # Pull a result ciphertext from the results bundle.
        res = ev['results_bytes']
        chunk_bytes = None
        with tarfile.open(fileobj=io.BytesIO(res), mode='r:gz') as tar:
            for m in tar.getmembers():
                if m.name.startswith('outputs/chunk_'):
                    chunk_bytes = tar.extractfile(m).read()
                    break
        self.assertIsNotNone(chunk_bytes)

        # Attempt to decrypt — should fail because the keys aren't generated.
        ct = fhe.Value.deserialize(chunk_bytes)
        with self.assertRaises(AssertionError):
            attacker_client.decrypt(ct)

    def test_keys_file_is_separate_from_package(self):
        """The keys bytes returned by encrypt() must NOT appear inside
        the package — the whole point is that the package is shippable
        without leaking the secret material."""
        op = {'op': 'length', 'col': 0, 'dst_col': 3}
        enc = sealedlex_protocol.encrypt(SAMPLE_CSV, op, 'ascii')

        # The package shouldn't contain anything literally identical to
        # the keys bytes.  This is a coarse check; a real adversary would
        # need to extract specific key material, but the property is:
        # there is no `keys.dat`-like member in the tar.
        with tarfile.open(fileobj=io.BytesIO(enc['package_bytes']),
                          mode='r:gz') as tar:
            names = [m.name for m in tar.getmembers()]
        # Allowed members: manifest, server, eval.keys (public), inputs/.
        # NOT allowed: anything that smells like 'secret', 'private', 'sk'.
        for name in names:
            self.assertFalse('secret' in name.lower(),
                             f'suspicious member: {name}')
            self.assertFalse('private' in name.lower(),
                             f'suspicious member: {name}')
        # And the keys file is non-empty, distinct, and the eval keys
        # serialised by encrypt are smaller than the full secret keys.
        self.assertGreater(len(enc['keys_bytes']), 0)
        # Heuristic: full key set is much bigger than eval-only.
        with tarfile.open(fileobj=io.BytesIO(enc['package_bytes']),
                          mode='r:gz') as tar:
            eval_member = tar.getmember('eval.keys')
            self.assertLess(eval_member.size, len(enc['keys_bytes']))


class ProtocolCheapTests(TestCase):
    """Tests that don't run a Concrete circuit — safe at any time."""

    def test_required_cell_len_picks_constant_aware_max(self):
        sel = [(1, 'abc'), (2, 'de')]
        self.assertEqual(
            sealedlex.required_cell_len({'op': 'length', 'col': 0}, sel),
            3)
        self.assertEqual(
            sealedlex.required_cell_len(
                {'op': 'equal_to', 'col': 0, 'constant': 'longerthancells'},
                sel),
            sealedlex.MAX_CELL_LEN)

    def test_decode_op_chunk_output_shapes(self):
        # char_class_map → matrix of class digits
        import numpy as np
        m = np.array([[2, 1, 2, 1, 0, 0], [2, 2, 1, 0, 0, 0]])
        out = sealedlex.decode_op_chunk_output({'op': 'char_class_map'}, m)
        self.assertEqual(out, ['2121', '221'])

        # count_class → vector of ints rendered as strings
        v = np.array([3, 1, 7])
        out = sealedlex.decode_op_chunk_output({'op': 'count_class'}, v)
        self.assertEqual(out, ['3', '1', '7'])
