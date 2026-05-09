"""Seed bidir with the officerpg parity table.  Idempotent — re-runs
upsert by slug rather than duplicating."""
from django.core.management.base import BaseCommand

from bidir.models import Feature, PortStatus, Variant


VARIANTS = [
    ('js-html',  'JS / HTML browser build', 'browser', True,  10),
    ('ansi-c',   'ANSI-C native (planned)', 'native',  False, 20),
]

FEATURES = [
    ('hex-ca',           'Hex cellular automaton terrain',           'ev1',  10),
    ('lsystem-sprites',  'L-system entity sprites',                  'ev1',  20),
    ('lsystem-genome',   'Background L-system GA + library',         'ev15', 30),
    ('hex-meta-grid',    'Hex meta-grid (offset-hex panel chain)',   'ev20', 40),
    ('block-ca-textures', 'Block-CA textures (CA-everywhere render)', 'ev1',  50),
    ('autoplay-journey', 'Autoplay / journey planner',               'ev9',  60),
    ('autoplay-stuck',   'Escalating chaotic stuck-recovery',        'ev45', 65),
    ('inv-zap-bend',     'Inventory + zap + terrain/category bend',  'ev1',  70),
    ('image-presets',    'Image-CA preset terrains (Mars/Paris/etc)','ev33', 80),
    ('flower-rule-view', 'All-rules flower view (16384)',            'ev36', 85),
    ('genome-workshop',  'Genome workshop (16384-rule editor)',      'ev1',  90),
    ('bio-lab',          'Bio lab (L-system breeder UI)',            'ev27', 95),
    ('rgba-pal-alpha',   'Per-slot RGBA alpha gene',                 'ev45', 100),
    ('music-mood',       'Mood-modulated bytebeat music',            'ev42', 110),
    ('music-stereo',     'Stereo music (score-CA L / meta-CA R)',    'ev47', 112),
    ('music-smooth',     'Worker scheduler + slip recovery',         'ev49', 114),
    ('music-waltz',      'Waltz / 3-4 meter toggle',                 'ev60', 113),
    ('animal-action-anim', 'Per-animal CA + 10 action maps',         'ev61', 156),
    ('lite-terminal',    'Embedded lite terminal sub-game',          'ev18', 120),
    ('full-auto-mode',   'Full-auto mode (live+music+map+journey)',  'ev45', 125),
    ('shot-export',      'Live browser-shot export + replay',        'ev44', 130),
    ('shot-bundle-full', 'Complete world bundle export (s key)',     'ev57', 132),
    ('death-respawn',    'Auto-respawn in journey mode',             'ev43', 135),
    ('tile-shape',       'Custom Tilesmith tile shapes (Shift+T)',   'ev46', 140),
    ('tile-shape-seam',  'Seamless Path2D clip + protrusion fill',   'ev48', 142),
    ('tile-shape-evolve', 'Tile-shape GA in the modal',              'ev51', 144),
    ('tile-shape-auto',  'Auto tile-shape GA in full-auto mode',     'ev55', 146),
    ('tile-zoom',        'Live tile-size zoom (+/-)',                'ev53', 148),
    ('per-cell-rules',   'Per-cell rule pool (u toggle, 256 rules)', 'ev52', 150),
    ('per-cell-rules-ga', 'Pool GA when per-cell rules engaged',     'ev54', 152),
    ('hex-meta-cascade', 'Hex topology at every meta cascade level', 'ev56', 154),
    ('pc-speaker',       'PC speaker / KIOCSOUND audio (C only)',    '—',    200),
]


class Command(BaseCommand):
    help = 'Seed bidir with the officerpg js-html ↔ ansi-c parity table.'

    def handle(self, *args, **opts):
        for slug, name, kind, canonical, sort_order in VARIANTS:
            v, _ = Variant.objects.update_or_create(
                slug=slug, defaults={
                    'name': name, 'runtime_kind': kind,
                    'is_canonical': canonical, 'sort_order': sort_order,
                })
            self.stdout.write(f'variant {v.slug} ✓')
        for slug, name, intro, sort_order in FEATURES:
            f, _ = Feature.objects.update_or_create(
                slug=slug, defaults={
                    'name': name, 'introduced_in': intro,
                    'sort_order': sort_order,
                })
            self.stdout.write(f'feature {f.slug} ✓')

        js = Variant.objects.get(slug='js-html')
        c  = Variant.objects.get(slug='ansi-c')
        # Features actually shipped in the ANSI-C port (officerpgc).
        ANSIC_DONE = {
            'hex-ca', 'lsystem-sprites', 'hex-meta-grid',
            'block-ca-textures', 'autoplay-journey', 'autoplay-stuck',
            'inv-zap-bend', 'full-auto-mode', 'shot-export',
            'shot-bundle-full', 'death-respawn', 'per-cell-rules',
            'per-cell-rules-ga', 'hex-meta-cascade',
            'animal-action-anim', 'pc-speaker',
        }
        # Features that cannot meaningfully ship in a nostdlib ANSI-C
        # terminal binary.  Three reasons collapse here:
        #   - Browser audio (Web Audio API has no terminal analog;
        #     pc-speaker is the C-side counterpart).
        #   - Sub-cell pixel rendering (terminal cells are character-
        #     sized; tile-shape geometry + zoom assume a canvas).
        #   - Browser-side interactive UIs (flower-rule-view modal,
        #     bio-lab breeder, genome-workshop editor); image-upload
        #     presets; circular concept (lite-terminal in a terminal).
        ANSIC_NA = {
            'lsystem-genome', 'image-presets', 'flower-rule-view',
            'genome-workshop', 'bio-lab', 'rgba-pal-alpha',
            'music-mood', 'music-stereo', 'music-waltz', 'music-smooth',
            'lite-terminal', 'tile-shape', 'tile-shape-seam',
            'tile-shape-evolve', 'tile-shape-auto', 'tile-zoom',
        }
        for f in Feature.objects.all():
            # PC speaker is C-only so the JS variant marks it n/a.
            if f.slug == 'pc-speaker':
                PortStatus.objects.update_or_create(
                    feature=f, variant=js, defaults={'state': 'na'})
                PortStatus.objects.update_or_create(
                    feature=f, variant=c,  defaults={'state': 'done'})
                continue
            PortStatus.objects.update_or_create(
                feature=f, variant=js, defaults={'state': 'done'})
            if f.slug in ANSIC_DONE:
                state = 'done'
            elif f.slug in ANSIC_NA:
                state = 'na'
            else:
                state = 'todo'
            PortStatus.objects.update_or_create(
                feature=f, variant=c, defaults={'state': state})
        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Variant.objects.count()} variants, '
            f'{Feature.objects.count()} features, '
            f'{PortStatus.objects.count()} status rows.'))
