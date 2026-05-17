"""Test famous-artist paintings for self-reproduction (quine) score.

Curates a list of public-domain (or otherwise canonical) artworks
across artists/styles, posterises each to K=4, scores as a K=4 hex CA
rule LUT, and reports a ranked table.  The question: do certain
painterly styles (flat colour fields, geometric cubism, late
impressionism …) yield higher SR than others?

Usage::

    manage.py test_artwork_quines
    manage.py test_artwork_quines --only "Van Gogh"
    manage.py test_artwork_quines --quantize kmeans
    manage.py test_artwork_quines --cache .artifacts/artwork_cache/
    manage.py test_artwork_quines --save-best  # commit top-N as quines
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Some Wikimedia masters are >1 Gpx; Pillow refuses these by default
# as decompression-bomb DoS protection.  We're trusting the source, so
# lift the cap.  We resize to 128×128 immediately anyway.
from PIL import Image as _PILImage
_PILImage.MAX_IMAGE_PIXELS = None


# ─── Curated corpus ──────────────────────────────────────────────────
#
# 25 paintings spanning 5 styles.  All are public-domain (artist >100 yr
# dead) or available as low-res thumbnails for educational analysis on
# Wikimedia Commons.  URLs point to 800px thumbnails to keep download
# small — the posterise step throws away all detail past 128×128
# anyway, so resolution beyond that doesn't matter.

CORPUS: list[dict] = [
    # ── Van Gogh — Arles (1888–early 1889): yellow house, vivid blocks ──
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'Sunflowers (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_127.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'Bedroom in Arles (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_De_slaapkamer_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'Café Terrace at Night (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_Cafe_Terrace_at_Night_%28Yorck%29.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'The Night Café (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_076.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'The Yellow House (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_The_yellow_house_%28%27The_street%27%29.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'The Sower (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_De_zaaier_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'Café Terrace at Night (1888) — alt',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Caf%C3%A9terras_bij_nacht_%28place_du_Forum%29_-_Kr%C3%B6ller-M%C3%BCller_Museum.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'The Red Vineyard (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Red_vineyards.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-arles',
       'title': 'La Berceuse — Augustine Roulin (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_La_berceuse_%28Augustine_Roulin%29_-_Google_Art_Project.jpg?width=1024'},

    # ── Van Gogh — Saint-Rémy asylum (May 1889 – May 1890) ──
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'The Starry Night (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Van_Gogh_-_Starry_Night_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Self-Portrait (Sept 1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Self-Portrait_-_Google_Art_Project_%28454045%29.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Self-Portrait Without Beard (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_106.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Irises (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Irises-Vincent_van_Gogh.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Wheat Field with Cypresses (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Wheat_Field_with_Cypresses_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Olive Trees with Yellow Sky and Sun (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_Olive_Trees_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Cypresses (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Cypresses_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'The Mulberry Tree (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_The_Mulberry_Tree_in_Autumn.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Wheatfield with a Reaper (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_Wheat_Field_with_Reaper_and_Sun_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Garden of the Asylum (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_044.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Starry Night Over the Rhône (1888)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Starry_Night_Over_the_Rhone.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Almond Blossom (Feb 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Almond_blossom_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-saint-remy',
       'title': 'Field with Poppies (1889)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_Field_with_Poppies_%281889%29.jpg?width=1024'},

    # ── Van Gogh — Auvers-sur-Oise (May–July 1890), the final two months ──
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Wheatfield with Crows (Jul 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_%281853-1890%29_-_Wheat_Field_with_Crows_%281890%29.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'The Church at Auvers (Jun 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_The_Church_in_Auvers-sur-Oise%2C_View_from_the_Chevet_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Portrait of Dr. Gachet (Jun 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Portrait_of_Dr._Gachet.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Daubigny\'s Garden (Jul 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Daubigny%27s_Garden_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Tree Roots (Jul 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_%281853-1890%29_-_Tree_Roots_%281890%29.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Country Road in Provence by Night (May 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Country_road_in_Provence_by_night_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Wheat Field Under Clouded Sky (Jul 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_Wheatfield_under_thunderclouds_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'White House at Night (Jun 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_Willem_van_Gogh_-_The_White_House_at_Night.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Two Peasant Women in a Field (Jul 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Two_peasant_women_digging_in_field_with_snow.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Roses (May 1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Vincent_van_Gogh_-_Roses_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Van Gogh', 'style': 'vg-auvers',
       'title': 'Wheatfield with Crows — alt scan',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Wheatfield_with_crows.jpg?width=1024'},

    # ── Monet (impressionism, soft colour fields, atmospheric) ──
    {'artist': 'Monet', 'style': 'impressionism',
       'title': 'Impression, Sunrise',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Monet_-_Impression%2C_Sunrise.jpg?width=1024'},
    {'artist': 'Monet', 'style': 'impressionism',
       'title': 'Water Lilies (1916)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Claude_Monet_-_Water_Lilies_-_1906%2C_Ryerson.jpg?width=1024'},
    {'artist': 'Monet', 'style': 'impressionism',
       'title': 'Houses of Parliament',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Claude_Monet_-_The_Houses_of_Parliament%2C_Sunset.jpg?width=1024'},
    {'artist': 'Monet', 'style': 'impressionism',
       'title': 'Haystacks (1890)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Claude_Monet_-_Meule_%28W_1273%29.jpg?width=1024'},
    {'artist': 'Monet', 'style': 'impressionism',
       'title': 'The Japanese Footbridge',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Claude_Monet_-_The_Japanese_Footbridge_-_Google_Art_Project.jpg?width=1024'},

    # ── Rembrandt (baroque, chiaroscuro, dark fields) ──
    {'artist': 'Rembrandt', 'style': 'baroque',
       'title': 'The Night Watch',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/The_Night_Watch_-_HD.jpg?width=1024'},
    {'artist': 'Rembrandt', 'style': 'baroque',
       'title': 'Self-Portrait (1659)',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Rembrandt_van_Rijn_-_Self-Portrait_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Rembrandt', 'style': 'baroque',
       'title': 'Anatomy Lesson of Dr Tulp',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Rembrandt_-_The_Anatomy_Lesson_of_Dr_Nicolaes_Tulp.jpg?width=1024'},
    {'artist': 'Rembrandt', 'style': 'baroque',
       'title': 'The Jewish Bride',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Rembrandt_Harmensz_van_Rijn_-_Portret_van_een_paar_als_oudtestamentische_figuren%2C_genaamd_%27Het_Joodse_bruidje%27_-_Google_Art_Project.jpg?width=1024'},
    {'artist': 'Rembrandt', 'style': 'baroque',
       'title': 'Storm on the Sea of Galilee',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Rembrandt_Christ_in_the_Storm_on_the_Lake_of_Galilee.jpg?width=1024'},

    # ── Picasso (cubism, blue period, flat plane fragments) ──
    {'artist': 'Picasso', 'style': 'cubism',
       'title': 'Les Demoiselles d’Avignon',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/Les_Demoiselles_d%27Avignon.jpg?width=1024'},
    {'artist': 'Picasso', 'style': 'cubism',
       'title': 'Girl Before a Mirror',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/Pablo_Picasso%2C_1932%2C_Girl_before_a_Mirror.jpg?width=1024'},
    {'artist': 'Picasso', 'style': 'blue-period',
       'title': 'The Old Guitarist',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Old_guitarist_chicago.jpg?width=1024'},
    {'artist': 'Picasso', 'style': 'cubism',
       'title': 'Three Musicians',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/Pablo_Picasso%2C_1921%2C_Nous_autres_musiciens_%28Three_Musicians%29%2C_oil_on_canvas%2C_204.5_x_188.3_cm%2C_Philadelphia_Museum_of_Art.jpg?width=1024'},
    {'artist': 'Picasso', 'style': 'cubism',
       'title': 'Ma Jolie',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/Pablo_Picasso%2C_1911-12%2C_Ma_Jolie%2C_oil_on_canvas%2C_100_x_64.1_cm%2C_Museum_of_Modern_Art_New_York.jpg?width=1024'},

    # ── Miró (surrealism, flat fields, biomorphic shapes) ──
    {'artist': 'Miro', 'style': 'surrealism',
       'title': 'Harlequin’s Carnival',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/HarlequinsCarnival.jpg?width=1024'},
    {'artist': 'Miro', 'style': 'surrealism',
       'title': 'The Farm',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/MiroFarm.jpg?width=1024'},
    {'artist': 'Miro', 'style': 'surrealism',
       'title': 'The Tilled Field',
       'url': 'https://en.wikipedia.org/wiki/Special:FilePath/Joan_Mir%C3%B3%2C_1923-24%2C_The_Tilled_Field.jpg?width=1024'},

    # ── Bonus controls: deeply geometric / flat-colour movements ──
    {'artist': 'Mondrian', 'style': 'neo-plasticism',
       'title': 'Composition with Red Blue Yellow',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Piet_Mondriaan%2C_1930_-_Mondrian_Composition_II_in_Red%2C_Blue%2C_and_Yellow.jpg?width=1024'},
    {'artist': 'Klimt', 'style': 'symbolism',
       'title': 'The Kiss',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/The_Kiss_-_Gustav_Klimt_-_Google_Cultural_Institute.jpg?width=1024'},
    {'artist': 'Hokusai', 'style': 'ukiyo-e',
       'title': 'The Great Wave',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/The_Great_Wave_off_Kanagawa.jpg?width=1024'},
    {'artist': 'Malevich', 'style': 'suprematism',
       'title': 'Black Square',
       'url': 'https://commons.wikimedia.org/wiki/Special:FilePath/Kazimir_Malevich%2C_1915%2C_Black_Suprematic_Square%2C_oil_on_linen_canvas%2C_79.5_x_79.5_cm%2C_Tretyakov_Gallery%2C_Moscow.jpg?width=1024'},
]


def _slug(s: str) -> str:
    return ''.join(c if c.isalnum() else '_' for c in s.lower()).strip('_')


def _cache_path(cache_dir: Path, url: str) -> Path:
    h = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
    ext = '.jpg' if '.jpg' in url.lower() else '.png'
    return cache_dir / f'{h}{ext}'


def _fetch(url: str, cache_dir: Path, *, log,
             throttle: float = 1.0) -> bytes | None:
    cp = _cache_path(cache_dir, url)
    if cp.exists() and cp.stat().st_size > 1024:
        return cp.read_bytes()
    cache_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={
        'User-Agent': ('VelourSpoeqiResearch/1.0 '
                         '(c.a.handy@hum.leidenuniv.nl)'),
        'Accept': 'image/jpeg, image/png, image/*',
    })
    # Be polite — Wikimedia rate-limits anonymous bulk fetching.
    time.sleep(throttle)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            # urllib follows redirects so this final URL is the upload host.
            final_url = resp.geturl()
            if final_url != url:
                log(f'    (resolved to {final_url})')
    except urllib.error.HTTPError as e:
        log(f'    HTTP {e.code} — skipped')
        return None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log(f'    network error: {e} — skipped')
        return None
    cp.write_bytes(data)
    return data


class Command(BaseCommand):
    help = 'Score famous artworks as candidate K=4 quine LUTs.'

    def add_arguments(self, parser):
        parser.add_argument('--only', type=str, default='',
                              help='substring match on artist/title')
        parser.add_argument('--quantize', type=str, default='median_cut',
                              choices=['median_cut', 'kmeans', 'fast_octree'])
        parser.add_argument('--cache', type=str, default='',
                              help='cache dir for downloaded images')
        parser.add_argument('--save-best', type=int, default=0,
                              help='also commit the top-N scoring rows as '
                                   'quines in the archive (0 = report only)')

    def handle(self, *, only, quantize, cache, save_best, **opts):
        from spoeqi import image_quine as iq

        if cache:
            cache_dir = Path(cache).resolve()
        else:
            cache_dir = Path(settings.BASE_DIR) / '.artifacts' / 'artwork_cache'
        only = only.lower().strip()

        rows: list[dict] = []
        for i, item in enumerate(CORPUS):
            blurb = f"{item['artist']} — {item['title']} ({item['style']})"
            if only and (only not in item['artist'].lower()
                             and only not in item['title'].lower()
                             and only not in item['style'].lower()):
                continue
            self.stdout.write(self.style.NOTICE(
                f"[{i+1:2d}/{len(CORPUS)}] {blurb}"))
            img_bytes = _fetch(item['url'], cache_dir, log=self.stdout.write)
            if img_bytes is None:
                continue

            t0 = time.time()
            try:
                rule = iq.image_to_rule(img_bytes, quantize=quantize)
                scores = iq.score_rule(rule.rule_bytes)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'    fail: {e}'))
                continue
            dt = time.time() - t0

            self.stdout.write(
                f"    SR={scores['sr_strict']:.4f} "
                f"arbσ={scores['sr_arbsigma']:.4f} "
                f"cls={scores['wolfram_class']} "
                f"c4={scores['c4']:.3f} "
                f"act={scores['act']:.3f} "
                f"chain={scores['chain_run_length']} ({dt:.1f}s)")

            rows.append({
                'artist':  item['artist'],
                'title':   item['title'],
                'style':   item['style'],
                'scores':  scores,
                'rule':    rule.rule_bytes,
                'palette': rule.palette_rgb,
                'src_size': rule.src_size,
            })

        if not rows:
            self.stdout.write(self.style.WARNING('no rows scored'))
            return

        # Per-style mean / max table.
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('== Per-style summary =='))
        by_style: dict[str, list[dict]] = {}
        for r in rows:
            by_style.setdefault(r['style'], []).append(r)
        self.stdout.write(
            f"{'style':<22} n   SR mean   SR max   arbσ mean  arbσ max  cls=4")
        for style, rs in sorted(by_style.items(),
                                key=lambda kv: -max(r['scores']['sr_arbsigma']
                                                       for r in kv[1])):
            srs   = [r['scores']['sr_strict']   for r in rs]
            arbs  = [r['scores']['sr_arbsigma'] for r in rs]
            n_cls = sum(1 for r in rs if r['scores']['wolfram_class'] == 4)
            self.stdout.write(
                f"{style:<22} {len(rs):<3} {sum(srs)/len(srs):.4f}  "
                f"{max(srs):.4f}  {sum(arbs)/len(arbs):.4f}    "
                f"{max(arbs):.4f}    {n_cls}/{len(rs)}")

        # Top-10 by arb-sigma.
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('== Top 10 by SR arbσ =='))
        ranked = sorted(rows,
                         key=lambda r: -r['scores']['sr_arbsigma'])[:10]
        for i, r in enumerate(ranked, 1):
            self.stdout.write(
                f"  {i:2d}. arbσ={r['scores']['sr_arbsigma']:.4f} "
                f"SR={r['scores']['sr_strict']:.4f} "
                f"cls={r['scores']['wolfram_class']} "
                f"— {r['artist']} — {r['title']}")

        # Top-10 by strict SR.
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('== Top 10 by strict SR =='))
        ranked_sr = sorted(rows,
                            key=lambda r: -r['scores']['sr_strict'])[:10]
        for i, r in enumerate(ranked_sr, 1):
            self.stdout.write(
                f"  {i:2d}. SR={r['scores']['sr_strict']:.4f} "
                f"arbσ={r['scores']['sr_arbsigma']:.4f} "
                f"cls={r['scores']['wolfram_class']} "
                f"— {r['artist']} — {r['title']}")

        if save_best:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE(
                f'== Saving top {save_best} (by arbσ) =='))
            saved = 0
            for r in ranked[:save_best]:
                s = r['scores']
                # Reuse persist_image_quine; force is implicit since we
                # explicitly opted into save-best from the CLI.
                obj, created = iq.persist_image_quine(
                    r['rule'],
                    scores=s,
                    image_label=f"{r['artist']} — {r['title']}",
                    quantize_method=quantize,
                    src_size=r['src_size'],
                    palette_rgb=r['palette'])
                tag = 'NEW' if created else 'dup'
                self.stdout.write(
                    f"  [{tag}] #{obj.pk}: {r['artist']} — {r['title']} "
                    f"(SR={s['sr_strict']:.4f}, arbσ={s['sr_arbsigma']:.4f})")
                if created:
                    saved += 1
            self.stdout.write(self.style.SUCCESS(
                f'committed {saved} new image-quine row(s)'))
