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
