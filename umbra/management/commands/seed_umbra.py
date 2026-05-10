"""Seed the Umbra catalogue with the four canonical FHE schemes plus
a curated set of references — papers, libraries, awesome-lists.

Idempotent: re-running updates existing rows by slug.

Run via:  venv/bin/python manage.py seed_umbra
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from umbra.models import Scheme, Reference


SCHEMES = [
    {
        'name':            'BFV',
        'family':          'RLWE',
        'datatype':        Scheme.DATATYPE_INT,
        'bootstrappable':  True,
        'year_introduced': 2012,
        'paper_title':     'Somewhat Practical Fully Homomorphic Encryption',
        'paper_url':       'https://eprint.iacr.org/2012/144',
        'summary':
            'Brakerski / Fan-Vercauteren — exact integer arithmetic on '
            'plaintexts encoded as polynomial coefficients.  Modular '
            'reduction by a fixed plaintext modulus, no scale.  '
            'Workhorse for integer evaluation circuits with deep '
            'multiplications when paired with relinearization.',
        'parameter_notes':
            'poly_modulus_degree typically 4096-32768; plaintext '
            'modulus a small prime (often ~786433 for 20-bit slots); '
            'coefficient modulus chosen for the desired multiplicative '
            'depth.',
    },
    {
        'name':            'BGV',
        'family':          'RLWE',
        'datatype':        Scheme.DATATYPE_INT,
        'bootstrappable':  True,
        'year_introduced': 2012,
        'paper_title':     '(Leveled) Fully Homomorphic Encryption '
                           'without Bootstrapping',
        'paper_url':       'https://eprint.iacr.org/2011/277',
        'summary':
            'Brakerski-Gentry-Vaikuntanathan — exact integer arithmetic '
            'with modulus switching for noise control.  Closely related '
            'to BFV; differs mainly in encoding and noise management.  '
            'HElib is the canonical implementation.',
        'parameter_notes':
            'Similar parameter knobs as BFV; HElib expresses them via '
            'L (number of levels) + bits-per-level.',
    },
    {
        'name':            'CKKS',
        'family':          'RLWE',
        'datatype':        Scheme.DATATYPE_FLOAT,
        'bootstrappable':  True,
        'year_introduced': 2017,
        'paper_title':     'Homomorphic Encryption for Arithmetic of '
                           'Approximate Numbers',
        'paper_url':       'https://eprint.iacr.org/2016/421',
        'summary':
            'Cheon-Kim-Kim-Song — approximate fixed-point arithmetic on '
            'real / complex vectors.  Sacrifices exactness for native '
            'support of fractional values, making it the de-facto '
            'choice for ML inference on encrypted data.',
        'parameter_notes':
            'scale (precision in bits, typically 30-40) trades off '
            'against the bits-per-level budget; poly_modulus_degree '
            '8192-32768 typical.',
    },
    {
        'name':            'TFHE',
        'family':          'GSW / LWE',
        'datatype':        Scheme.DATATYPE_BOOL,
        'bootstrappable':  True,
        'year_introduced': 2016,
        'paper_title':     'Faster Fully Homomorphic Encryption: '
                           'Bootstrapping in less than 0.1 Seconds',
        'paper_url':       'https://eprint.iacr.org/2016/870',
        'summary':
            'Chillotti-Gama-Georgieva-Izabachene — fast gate-by-gate '
            'bootstrapping enables arbitrary boolean / lookup-table '
            'evaluation with low latency per gate.  Programmable '
            'bootstrapping is the headline feature; Zama Concrete is '
            'the modern toolchain.',
        'parameter_notes':
            'Security parameter, message bit-width, decomposition base '
            'L + level — set via Concrete\'s param search rather than '
            'tuned by hand.',
    },
]


REFS = [
    # Awesome-lists
    ('awesome-zama',
        'https://github.com/zama-ai/awesome-zama',
        Reference.KIND_AWESOME, '', None,
        'Curated index of FHE / Zama resources — papers, '
        'libraries, talks.', ['TFHE', 'CKKS'], 'index,zama'),
    ('Awesome Homomorphic Encryption',
        'https://github.com/jonaschn/awesome-he',
        Reference.KIND_AWESOME, 'Jonas Schneider', None,
        'Long-running general FHE awesome-list — schemes, libraries, '
        'compilers, applications.', [], 'index'),

    # Libraries / repos
    ('Pyfhel',
        'https://github.com/ibarrond/Pyfhel',
        Reference.KIND_LIBRARY, 'Alberto Ibarrondo', 2018,
        'Python wrapper around Microsoft SEAL — gives a high-level '
        'Pythonic API to BFV / BGV / CKKS for prototyping.',
        ['BFV', 'BGV', 'CKKS'], 'python,seal'),
    ('Concrete',
        'https://github.com/zama-ai/concrete',
        Reference.KIND_LIBRARY, 'Zama', 2020,
        'Rust + Python TFHE toolchain with programmable bootstrapping.  '
        '`concrete-python` compiles numpy-like code to FHE circuits.',
        ['TFHE'], 'python,rust,zama'),
    ('Concrete-ML',
        'https://github.com/zama-ai/concrete-ml',
        Reference.KIND_LIBRARY, 'Zama', 2022,
        'scikit-learn-style API on top of Concrete — train / quantize / '
        'serve ML models with FHE inference.', ['TFHE'], 'ml,zama'),
    ('TFHE-rs',
        'https://github.com/zama-ai/tfhe-rs',
        Reference.KIND_LIBRARY, 'Zama', 2022,
        'Pure-Rust TFHE implementation — the runtime under Concrete.',
        ['TFHE'], 'rust,zama'),
    ('Microsoft SEAL',
        'https://github.com/microsoft/SEAL',
        Reference.KIND_LIBRARY, 'Microsoft', 2018,
        'C++ library for BFV / BGV / CKKS.  The reference '
        'implementation most other tools wrap.',
        ['BFV', 'BGV', 'CKKS'], 'cpp,seal'),
    ('HElib',
        'https://github.com/homenc/HElib',
        Reference.KIND_LIBRARY, 'IBM', 2013,
        'C++ implementation of BGV (and CKKS).  Long history; the '
        'home of bootstrapping research.',
        ['BGV', 'CKKS'], 'cpp,ibm'),
    ('OpenFHE',
        'https://github.com/openfheorg/openfhe-development',
        Reference.KIND_LIBRARY, 'OpenFHE consortium', 2022,
        'Open-source unification of PALISADE + HElib + others — '
        'BFV/BGV/CKKS/TFHE under one C++ API.',
        ['BFV', 'BGV', 'CKKS', 'TFHE'], 'cpp,palisade'),

    # Foundational papers
    ('Gentry — Fully Homomorphic Encryption Using Ideal Lattices',
        'https://crypto.stanford.edu/craig/craig-thesis.pdf',
        Reference.KIND_PAPER, 'Craig Gentry', 2009,
        'The original FHE construction.  Introduces bootstrapping; '
        'now mostly historical but the conceptual map starts here.',
        [], 'foundational,bootstrapping'),
    ('BFV — Somewhat Practical FHE',
        'https://eprint.iacr.org/2012/144',
        Reference.KIND_PAPER, 'Fan, Vercauteren', 2012,
        'The BFV scheme paper.', ['BFV'], 'rlwe'),
    ('BGV — Leveled FHE without Bootstrapping',
        'https://eprint.iacr.org/2011/277',
        Reference.KIND_PAPER,
        'Brakerski, Gentry, Vaikuntanathan', 2011,
        'BGV scheme + modulus switching for noise control.',
        ['BGV'], 'rlwe'),
    ('CKKS — HE for Arithmetic of Approximate Numbers',
        'https://eprint.iacr.org/2016/421',
        Reference.KIND_PAPER, 'Cheon, Kim, Kim, Song', 2017,
        'The approximate-arithmetic scheme behind ML-on-FHE.',
        ['CKKS'], 'rlwe,approximate'),
    ('TFHE — Bootstrapping in less than 0.1 Seconds',
        'https://eprint.iacr.org/2016/870',
        Reference.KIND_PAPER,
        'Chillotti, Gama, Georgieva, Izabachene', 2016,
        'Fast gate-bootstrapping; the GSW-style scheme behind '
        'Concrete.', ['TFHE'], 'gsw,bootstrapping'),

    # Tutorials / talks
    ('Zama Bootcamp — TFHE Deep Dive',
        'https://www.zama.ai/post/tfhe-deep-dive-part-1',
        Reference.KIND_TUTORIAL, 'Zama', 2022,
        'Multi-part walkthrough of TFHE internals for engineers.',
        ['TFHE'], 'tutorial,zama'),
    ('Pyfhel Quickstart Notebook',
        'https://github.com/ibarrond/Pyfhel/blob/master/Demos_Examples/'
        'Demo_1_HelloWorld.ipynb',
        Reference.KIND_TUTORIAL, 'Alberto Ibarrondo', 2020,
        'Hello-world for Pyfhel — encrypt, add, multiply, decrypt.',
        ['BFV'], 'tutorial,python'),
]


class Command(BaseCommand):
    help = 'Seed Umbra with the canonical FHE schemes + curated references.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset', action='store_true',
            help='Delete existing schemes/references before seeding.',
        )

    def handle(self, *args, **opts):
        if opts['reset']:
            Reference.objects.all().delete()
            Scheme.objects.all().delete()
            self.stdout.write(self.style.WARNING('  reset: cleared schemes + references'))

        # Schemes — upsert by slug.
        scheme_by_name = {}
        n_new = n_upd = 0
        for s in SCHEMES:
            slug = slugify(s['name'])
            obj, created = Scheme.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':            s['name'],
                    'family':          s['family'],
                    'datatype':        s['datatype'],
                    'bootstrappable':  s['bootstrappable'],
                    'year_introduced': s['year_introduced'],
                    'paper_title':     s['paper_title'],
                    'paper_url':       s['paper_url'],
                    'summary':         s['summary'],
                    'parameter_notes': s['parameter_notes'],
                },
            )
            scheme_by_name[s['name']] = obj
            if created: n_new += 1
            else:       n_upd += 1
        self.stdout.write(self.style.SUCCESS(
            f'  schemes: {n_new} new, {n_upd} updated'))

        # References — upsert by slug.
        n_new = n_upd = 0
        for (title, url, kind, authors, year, summary,
             scheme_names, tags) in REFS:
            slug = slugify(title)[:120] or 'reference'
            obj, created = Reference.objects.update_or_create(
                slug=slug,
                defaults={
                    'title':   title,
                    'url':     url,
                    'kind':    kind,
                    'authors': authors,
                    'year':    year,
                    'summary': summary,
                    'tags':    tags,
                },
            )
            obj.schemes.set([scheme_by_name[n] for n in scheme_names
                             if n in scheme_by_name])
            if created: n_new += 1
            else:       n_upd += 1
        self.stdout.write(self.style.SUCCESS(
            f'  references: {n_new} new, {n_upd} updated'))
        self.stdout.write(self.style.SUCCESS(
            f'  total: {Scheme.objects.count()} schemes / '
            f'{Reference.objects.count()} references'))
