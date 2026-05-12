"""Seed Umbra with substantive CKKS sample experiments.

Distinct from seed_umbra (catalogue + references) so users can re-seed
sample code without disturbing their own saved experiments.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from umbra.models import Scheme, Experiment


SAMPLES = [
    {
        'name':        'CKKS — encrypted linear regression',
        'description': 'y = w · x + b evaluated entirely on ciphertext. '
                       'Plaintext weights/intercept; encrypted feature vector.',
        'scheme_slug': 'ckks',
        'code': '''\
# CKKS: encrypted linear regression.
# Plaintext model (weights + intercept), encrypted features.
import tenseal as ts

ctx = ts.context(
    ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2 ** 40
ctx.generate_galois_keys()

# Toy "house price" model:
weights = [120.0, 85.0, -3.5, 250.0]   # bedrooms, sq-m, age, has-garden
bias    = 35.0

# Two encrypted houses to score.
x1 = ts.ckks_vector(ctx, [3, 90, 12, 1])
x2 = ts.ckks_vector(ctx, [2, 65,  5, 0])

y1 = x1.dot(weights) + bias
y2 = x2.dot(weights) + bias
print('house 1 price (k EUR):', round(y1.decrypt()[0], 2))   # 8253.0
print('house 2 price (k EUR):', round(y2.decrypt()[0], 2))   # 5782.5
''',
    },
    {
        'name':        'CKKS — encrypted polynomial f(x)=ax^2+bx+c',
        'description': 'Polynomial evaluation on an encrypted vector. '
                       'Two ciphertext multiplications + add — exercises '
                       'multiplicative depth and rescaling.',
        'scheme_slug': 'ckks',
        'code': '''\
# CKKS: evaluate f(x) = 2*x^2 + 3*x + 5 over an encrypted vector.
import tenseal as ts

ctx = ts.context(
    ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2 ** 40
ctx.generate_galois_keys()

x = ts.ckks_vector(ctx, [0.5, 1.0, 1.5, 2.0, 2.5])
y = x * x * 2 + x * 3 + 5         # 2 ct-ct mults consume depth
print('f(x) =', [round(v, 4) for v in y.decrypt()])
# Plaintext check:  f(0.5)=7.0  f(1)=10  f(1.5)=14  f(2)=19  f(2.5)=25
''',
    },
    {
        'name':        'CKKS — two-party encrypted averaging',
        'description': 'Alice + Bob encrypt their contribution under the '
                       'same public context; server sums their ciphertexts '
                       'and scales by 1/N. Only the receiver can decrypt.',
        'scheme_slug': 'ckks',
        'code': '''\
# CKKS: two parties contribute, server averages, only Alice decrypts.
import tenseal as ts

# Shared public context (in reality, only the secret key holder can decrypt;
# both parties encrypt with a copy that has no secret_key bits).
ctx = ts.context(
    ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2 ** 40
ctx.generate_galois_keys()

alice = ts.ckks_vector(ctx, [78.3, 14.1])   # e.g. body temp + glucose
bob   = ts.ckks_vector(ctx, [77.9, 14.4])

# Server side: it sees only ciphertexts.
total   = alice + bob
average = total * 0.5                       # plaintext scalar mult

print('cohort average:', [round(v, 4) for v in average.decrypt()])
# Plaintext check: (78.3+77.9)/2 = 78.1   (14.1+14.4)/2 = 14.25
''',
    },
    {
        'name':        'BFV — exact-integer ciphertext arithmetic (Pyfhel)',
        'description': 'Pyfhel BFV: add + multiply on exact integers. '
                       'Where CKKS approximates floats, BFV is exact '
                       '(over Z_t) — better fit for counters, IDs, '
                       'small-integer tallies.',
        'scheme_slug': 'bfv',
        'code': '''\
# BFV exact-integer arithmetic via Pyfhel.
import numpy as np
from Pyfhel import Pyfhel

he = Pyfhel()
he.contextGen(scheme='BFV', n=2**13, t=65537, t_bits=20)
he.keyGen()
he.relinKeyGen()

a = he.encryptInt(np.array([42], dtype=np.int64))
b = he.encryptInt(np.array([58], dtype=np.int64))

c_sum  = a + b
c_prod = a * b
he.relinearize(c_prod)

print('42 + 58 =', he.decryptInt(c_sum)[0])    # -> 100
print('42 * 58 =', he.decryptInt(c_prod)[0])   # -> 2436

# Constant-time tally aggregation: sum a small batch of encrypted counts.
batch = [he.encryptInt(np.array([v], dtype=np.int64)) for v in (3, 5, 7, 11, 13)]
total = batch[0]
for v in batch[1:]:
    total += v
print('sum(3,5,7,11,13) =', he.decryptInt(total)[0])   # -> 39
''',
    },
    {
        'name':        'TFHE — encrypted char-class lookup (Concrete)',
        'description': 'Programmable bootstrapping on a per-byte LUT — '
                       'the building block for sealed linguistic ops. '
                       'Classifies an encrypted ASCII char as '
                       'vowel/consonant/digit/punct/other.',
        'scheme_slug': 'tfhe',
        'code': '''\
# TFHE via Concrete: byte -> char-class under seal via PBS.
# This is the atom for SealedLex's sealed linguistic ops.
import time, numpy as np
from concrete import fhe

# Char classes: 0=other 1=vowel 2=consonant 3=digit 4=punct.
VOWELS = set(ord(c) for c in "aeiouAEIOU")
PUNCT  = set(map(ord, ' !"\\\'\\,.:;?'))
def classify(c):
    if c in VOWELS:                            return 1
    if (97 <= c <= 122) or (65 <= c <= 90):    return 2
    if 48 <= c <= 57:                          return 3
    if c in PUNCT:                             return 4
    return 0

table = fhe.LookupTable([classify(i) for i in range(128)])

@fhe.compiler({"c": "encrypted"})
def char_class(c):
    return table[c]

t0 = time.monotonic()
circuit = char_class.compile([(i,) for i in range(128)])
print("compile_ms:", int((time.monotonic() - t0) * 1000))

samples = [("a", 1), ("b", 2), ("3", 3), (",", 4), ("@", 0), ("I", 1)]
print("char | class | latency")
for ch, expected in samples:
    t1 = time.monotonic()
    got = circuit.encrypt_run_decrypt(ord(ch))
    print(f"  {ch!r:5} -> {got}  ({int((time.monotonic() - t1) * 1000)} ms)  expected {expected}")
''',
    },
    {
        'name':        'TFHE — vowel count under seal (Concrete)',
        'description': 'Per-byte indicator under PBS, then sum across '
                       'cell — produces an encrypted vowel count for a '
                       'short padded form.  Same shape as the SealedLex '
                       'count_class op.',
        'scheme_slug': 'tfhe',
        'code': '''\
# TFHE via Concrete: encrypted vowel count for an 8-byte cell.
import time, numpy as np
from concrete import fhe

VOWELS = set(ord(c) for c in "aeiouAEIOU")
indicator = np.array([1 if i in VOWELS else 0 for i in range(128)],
                     dtype=np.int64)
table = fhe.LookupTable(indicator.tolist())

CELL_LEN = 8

@fhe.compiler({"cell": "encrypted"})
def vowel_count(cell):
    return np.sum(table[cell])

inputset = [np.random.randint(0, 128, size=CELL_LEN, dtype=np.int64)
            for _ in range(8)]
t0 = time.monotonic()
circuit = vowel_count.compile(inputset)
print("compile_ms:", int((time.monotonic() - t0) * 1000))

def encode(text):
    arr = np.zeros(CELL_LEN, dtype=np.int64)
    for i, ch in enumerate(text[:CELL_LEN]):
        b = ord(ch)
        arr[i] = b if 0 < b < 128 else 0
    return arr

for word in ["guru", "shishya", "namaste", "panee", "ela", "heera"]:
    arr = encode(word)
    t1  = time.monotonic()
    got = circuit.encrypt_run_decrypt(arr)
    expected = sum(1 for c in word[:CELL_LEN] if ord(c) in VOWELS)
    print(f"  {word!r:10} -> {int(got)} vowels  ({int((time.monotonic() - t1) * 1000)} ms)  expected {expected}")
''',
    },
    {
        'name':        'CKKS — encrypted cosine similarity',
        'description': 'Cosine similarity between two encrypted vectors '
                       'via dot product + plaintext norms. Often used in '
                       'private retrieval / embedding search.',
        'scheme_slug': 'ckks',
        'code': '''\
# CKKS: encrypted dot product, with norms pre-computed in plaintext.
import math
import tenseal as ts

ctx = ts.context(
    ts.SCHEME_TYPE.CKKS,
    poly_modulus_degree=8192,
    coeff_mod_bit_sizes=[60, 40, 40, 60],
)
ctx.global_scale = 2 ** 40
ctx.generate_galois_keys()

a_pt = [1.0, 2.0, 3.0, 4.0]
b_pt = [4.0, 3.0, 2.0, 1.0]

a = ts.ckks_vector(ctx, a_pt)
b = ts.ckks_vector(ctx, b_pt)

dot = a.dot(b)
norm_a = math.sqrt(sum(v*v for v in a_pt))
norm_b = math.sqrt(sum(v*v for v in b_pt))

cos = dot.decrypt()[0] / (norm_a * norm_b)
print('cos(a, b) =', round(cos, 6))   # ≈ 0.666667
''',
    },
]


class Command(BaseCommand):
    help = 'Seed Umbra with substantive CKKS sample experiments.'

    def handle(self, *args, **opts):
        n_new = n_upd = 0
        for s in SAMPLES:
            slug = slugify(s['name'])[:120]
            scheme = Scheme.objects.filter(slug=s['scheme_slug']).first()
            obj, created = Experiment.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':        s['name'],
                    'description': s['description'],
                    'code':        s['code'],
                    'scheme':      scheme,
                    'status':      Experiment.STATUS_SAVED,
                },
            )
            if created: n_new += 1
            else:       n_upd += 1
            self.stdout.write(f'  {"new" if created else "upd"}: {slug}')

        self.stdout.write(self.style.SUCCESS(
            f'experiments: {n_new} new, {n_upd} updated; '
            f'total Experiments now = {Experiment.objects.count()}'))
