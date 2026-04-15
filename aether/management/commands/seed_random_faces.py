"""Seed the Face Forge library with N random faces.

Ports the JS randomGenome() in static/aether/face_render.js to Python so
faces can be created without a browser. Structure must match what
face_render.js renderFace() expects: {seed, lineage, palette, traits, anim}.
"""
import colorsys
import random

from django.core.management.base import BaseCommand

from aether.models import SavedFace


FACE_SHAPES  = ['round', 'oval', 'heart', 'square', 'long']
EYE_SHAPES   = ['round', 'almond', 'cat', 'sleepy', 'wide', 'droopy']
BROW_SHAPES  = ['arch', 'flat', 'angry', 'sad', 'thin', 'bushy']
NOSE_SHAPES  = ['button', 'long', 'hook', 'flat', 'wide']
MOUTH_SHAPES = ['smile', 'neutral', 'pout', 'grin', 'frown', 'o', 'smirk']
HAIR_STYLES  = ['short', 'long', 'bun', 'twintails', 'bob', 'wild', 'bald',
                'mohawk', 'ponytail', 'fringe', 'afro']
HAT_KINDS    = ['', '', '', '', 'beret', 'crown', 'wizard', 'top_hat',
                'beanie', 'headband', 'flower', 'halo', 'bow', 'cat_ears']
EAR_STYLES   = ['normal', 'pointed', 'big', 'small', 'elf']
TATTOO_KINDS = ['', '', '', '', '', 'tear', 'rune', 'dots', 'line', 'star', 'heart']
SCAR_KINDS   = ['', '', '', 'cheek', 'brow', 'lip', 'nose', 'eye']
EYEPATCH_SIDE = ['left', 'right']

RULE_POOL = '.ib.BW.wLR..SsFPpTEeHCY..Ii.'


# Ada Lovelace, Turing, Shannon, Hopper, Dijkstra, Knuth, Alan Kay,
# Margaret Hamilton, Hedy Lamarr, Lovecraft, Borges, Calvino, Dürer,
# Escher, Hofstadter, Bach, Gödel — and plenty more; used as display
# names. Seeded faces get numbered names so they're sortable.
FIRST_NAMES = [
    'Ada', 'Alan', 'Grace', 'Claude', 'Ondine', 'Iris', 'Mei', 'Otto',
    'Sable', 'Juno', 'Cass', 'Tam', 'Vero', 'Rafe', 'Lumi', 'Neve',
    'Orin', 'Pax', 'Quill', 'Ren', 'Saga', 'Til', 'Una', 'Vesper',
    'Wren', 'Xan', 'Yuki', 'Zia', 'Baz', 'Cleo', 'Drix', 'Echo',
    'Flor', 'Ghost', 'Hilde', 'Inge', 'Jax', 'Kori', 'Lior', 'Milo',
    'Noor', 'Osk', 'Pria', 'Quinn', 'Roan', 'Sky', 'Tor', 'Una',
    'Vale', 'Whim', 'Ximen', 'Yara', 'Zoe', 'Asta', 'Bram', 'Coral',
    'Dag', 'Ember', 'Fenix', 'Glim', 'Hart', 'Ivo', 'Jude', 'Kai',
    'Lev', 'Mira', 'Nox', 'Olla', 'Pipp', 'Quen', 'Rus', 'Sef',
]
SURNAMES = [
    'Noon', 'Forge', 'Ember', 'Marrow', 'Veil', 'Hollow', 'Glass',
    'Crown', 'Moth', 'Ash', 'Pine', 'Quartz', 'Slate', 'Tide', 'Vane',
    'Wisp', 'Yarrow', 'Zephyr', 'Bell', 'Cairn', 'Drift', 'Fen',
    'Graven', 'Heron', 'Iver', 'Juno', 'Kestrel', 'Lark', 'Mire',
    'Nook', 'Oak', 'Plume', 'Quail', 'Rook', 'Sable', 'Thorn',
]


def hsl_to_hex(h, s, l):
    # h in [0, 360), s and l in [0, 100]
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, l / 100.0, s / 100.0)
    return '#{:02x}{:02x}{:02x}'.format(
        int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
    )


def _gen_rule(rng):
    n = 5 + rng.randrange(8)
    out = []
    for _ in range(n):
        if rng.random() < 0.12:
            out.append(rng.choice(['I', 'J', 'K']))
        else:
            out.append(RULE_POOL[rng.randrange(len(RULE_POOL))])
    return ''.join(out)


def _random_anim(rng):
    axiom_len = 4 + rng.randrange(4)
    axiom = ''.join(rng.choice(['I', 'J', 'K', '.', 'i']) for _ in range(axiom_len))
    return {
        'axiom': axiom,
        'rules': {'I': _gen_rule(rng), 'J': _gen_rule(rng), 'K': _gen_rule(rng)},
        'iters': 2 + rng.randrange(2),
        'tempo': 1.2 + rng.random() * 1.4,
    }


def random_genome(seed):
    rng = random.Random(seed)

    skinH = rng.uniform(10, 35)
    skinS = rng.uniform(30, 65)
    skinL = rng.uniform(55, 85)
    skin = hsl_to_hex(skinH, skinS, skinL)
    skinShade = hsl_to_hex(skinH, skinS, max(30, skinL - 15))
    skinHL = hsl_to_hex(skinH, skinS * 0.7, min(95, skinL + 10))

    hairH = rng.uniform(0, 360) if rng.random() < 0.15 else rng.uniform(0, 60)
    hairL = rng.uniform(12, 75)
    hair = hsl_to_hex(hairH, rng.uniform(30, 85), hairL)
    hairShade = hsl_to_hex(hairH, 60, max(5, hairL - 18))

    irisH = rng.uniform(0, 360)
    iris = hsl_to_hex(irisH, rng.uniform(30, 85), rng.uniform(25, 55))

    lipH = rng.uniform(340, 380) % 360
    lip = hsl_to_hex(lipH, rng.uniform(40, 80), rng.uniform(40, 65))

    return {
        'seed': seed,
        'lineage': 0,
        'palette': {
            'skin': skin, 'skinShade': skinShade, 'skinHL': skinHL,
            'hair': hair, 'hairShade': hairShade,
            'iris': iris, 'lip': lip,
            'tattooCol': hsl_to_hex(rng.uniform(0, 360), 60, 30),
            'hatCol':    hsl_to_hex(rng.uniform(0, 360), rng.uniform(30, 85), rng.uniform(25, 60)),
            'blush':     hsl_to_hex((lipH + 10) % 360, 70, 70),
        },
        'traits': {
            'face_shape':  rng.choice(FACE_SHAPES),
            'face_w':      rng.uniform(0.82, 1.12),
            'face_h':      rng.uniform(0.90, 1.18),
            'eye_shape':   rng.choice(EYE_SHAPES),
            'eye_size':    rng.uniform(0.85, 1.35),
            'eye_spacing': rng.uniform(0.88, 1.12),
            'eye_tilt':    rng.uniform(-12, 12),
            'iris_size':   rng.uniform(0.65, 1.05),
            'pupil_size':  rng.uniform(0.32, 0.55),
            'eyelash':     rng.randrange(5),
            'eyebag':      rng.random(),
            'brow_shape':  rng.choice(BROW_SHAPES),
            'brow_thick':  rng.uniform(0.5, 1.6),
            'brow_tilt':   rng.uniform(-15, 15),
            'brow_y':      rng.uniform(-3, 3),
            'nose_shape':  rng.choice(NOSE_SHAPES),
            'nose_size':   rng.uniform(0.7, 1.3),
            'mouth_shape': rng.choice(MOUTH_SHAPES),
            'mouth_width': rng.uniform(0.7, 1.25),
            'lip_full':    rng.uniform(0.4, 1.4),
            'teeth_show':  rng.uniform(0.1, 0.6) if rng.random() < 0.35 else 0,
            'teeth_count': 2 + rng.randrange(6),
            'ear_style':   rng.choice(EAR_STYLES),
            'ear_size':    rng.uniform(0.8, 1.25),
            'hair_style':  rng.choice(HAIR_STYLES),
            'hair_volume': rng.uniform(0.6, 1.6),
            'fringe':      rng.random(),
            'hat_kind':    rng.choice(HAT_KINDS),
            'earrings':    1 + rng.randrange(2) if rng.random() < 0.3 else 0,
            'nose_ring':   1 if rng.random() < 0.08 else 0,
            'septum':      1 if rng.random() < 0.05 else 0,
            'forehead_gem': 1 if rng.random() < 0.06 else 0,
            'neck_chain':  1 if rng.random() < 0.15 else 0,
            'tattoo_kind': rng.choice(TATTOO_KINDS),
            'tattoo_x':    rng.uniform(0.15, 0.85),
            'tattoo_y':    rng.uniform(0.25, 0.85),
            'wrinkle':     rng.randrange(7 if rng.random() < 0.3 else 2),
            'wart':        1 + rng.randrange(3) if rng.random() < 0.15 else 0,
            'wart_x':      rng.uniform(0.2, 0.8),
            'wart_y':      rng.uniform(0.3, 0.75),
            'scar_kind':   rng.choice(SCAR_KINDS),
            'eyepatch':    rng.choice(EYEPATCH_SIDE) if rng.random() < 0.04 else '',
            'freckles':    rng.uniform(0.2, 1.0) if rng.random() < 0.25 else 0,
            'blush':       rng.uniform(0.2, 1.0) if rng.random() < 0.55 else 0,
            'makeup_eye':  rng.uniform(0.3, 1.0) if rng.random() < 0.30 else 0,
            'makeup_lip':  rng.uniform(0.3, 1.0) if rng.random() < 0.35 else 0,
        },
        'anim': _random_anim(rng),
    }


class Command(BaseCommand):
    help = 'Seed the Face Forge library with N random faces.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=500,
                            help='How many faces to create (default 500).')
        parser.add_argument('--seed', type=int, default=20260415,
                            help='Base seed for reproducibility.')
        parser.add_argument('--prefix', type=str, default='Genesis',
                            help='Name prefix for the generated batch.')

    def handle(self, *args, **options):
        count = options['count']
        base_seed = options['seed']
        prefix = options['prefix']

        name_rng = random.Random(base_seed ^ 0xA1CE)
        to_create = []
        for i in range(count):
            seed = base_seed + i
            genome = random_genome(seed)
            first = name_rng.choice(FIRST_NAMES)
            last = name_rng.choice(SURNAMES)
            name = f'{prefix} {i+1:04d} — {first} {last}'
            to_create.append(SavedFace(name=name, genome=genome, lineage=0))

        # bulk_create skips .save() so slugs wouldn't generate. Create one
        # at a time to get unique slugs; it's a one-shot seeder.
        created = 0
        for face in to_create:
            face.save()
            created += 1
            if created % 50 == 0:
                self.stdout.write(f'  {created}/{count}...')

        total = SavedFace.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {created} random faces. Library now has {total} total.'
        ))
