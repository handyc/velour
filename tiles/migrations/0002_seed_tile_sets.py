"""Seed two canonical Wang tile sets so the catalog has something
to show on first visit.

Set 1: the 2-color / 4-tile 'checkerboard' demonstration — shows
how edge-matching works in the simplest possible case.

Set 2: a 3-color / 8-tile 'river' set that tiles strip-shaped
regions with a blue "river" that must flow consistently between
tiles. Not aperiodic (that would take 11+ tiles per Jeandel-Rao)
but demonstrates multi-color matching constraints.

Both sets use hex colors so the SVG renderer can paint the edge
triangles directly.
"""

from django.db import migrations


def seed(apps, schema_editor):
    TileSet = apps.get_model('tiles', 'TileSet')
    Tile = apps.get_model('tiles', 'Tile')

    if TileSet.objects.exists():
        return

    # --- Set 1: 2-color checkerboard ---------------------------------
    checker = TileSet.objects.create(
        name='2-color checkerboard',
        slug='checkerboard',
        description=('The simplest possible Wang tile set. Two '
                     'colors, four tiles — every combination of '
                     'north/south = black/white with east/west '
                     'matching in a checkerboard pattern. Tiles '
                     'the plane trivially and periodically.'),
        palette=['#0d1117', '#c9d1d9'],
        notes='Pedagogical — the minimum viable Wang tile set.',
    )
    black = '#0d1117'
    white = '#c9d1d9'
    tiles = [
        ('A', white, white, white, white),
        ('B', black, black, black, black),
        ('C', white, black, white, black),
        ('D', black, white, black, white),
    ]
    for i, (name, n, e, s, w) in enumerate(tiles):
        Tile.objects.create(
            tileset=checker, name=name,
            n_color=n, e_color=e, s_color=s, w_color=w,
            sort_order=i,
        )

    # --- Set 2: 3-color river ---------------------------------------
    river = TileSet.objects.create(
        name='3-color river',
        slug='river',
        description=('A 3-color tile set using green (bank), blue '
                     '(water), and brown (shore). The blue edges '
                     'must match to form a contiguous river that '
                     'flows through the tiled region. Useful for '
                     'procedural map generation in small games.'),
        palette=['#3fb950', '#58a6ff', '#d29922'],
        notes=('Demonstrates multi-color matching. Not aperiodic — '
               'the Jeandel-Rao minimum aperiodic set needs 11 '
               'tiles, which this demo omits.'),
    )
    green = '#3fb950'
    blue  = '#58a6ff'
    brown = '#d29922'
    river_tiles = [
        # (name, n, e, s, w)
        ('grass',      green, green, green, green),
        ('bank_n',     brown, green, green, green),
        ('bank_e',     green, brown, green, green),
        ('bank_s',     green, green, brown, green),
        ('bank_w',     green, green, green, brown),
        ('river_ns',   blue,  green, blue,  green),
        ('river_ew',   green, blue,  green, blue),
        ('river_bend_ne', blue, blue, green, green),
    ]
    for i, (name, n, e, s, w) in enumerate(river_tiles):
        Tile.objects.create(
            tileset=river, name=name,
            n_color=n, e_color=e, s_color=s, w_color=w,
            sort_order=i,
        )


def unseed(apps, schema_editor):
    TileSet = apps.get_model('tiles', 'TileSet')
    TileSet.objects.filter(slug__in=['checkerboard', 'river']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tiles', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
