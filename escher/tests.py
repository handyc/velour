"""Tests for the escher app — 17 wallpaper-group tilings."""

from __future__ import annotations

import math
import re

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model

from escher import groups, motifs, svg


class WallpaperGroupTableTest(TestCase):
    def test_seventeen_groups_present(self):
        self.assertEqual(len(groups.GROUPS), 17,
                          'wallpaper groups must list exactly 17 entries')
        slugs = {g.slug for g in groups.GROUPS}
        self.assertEqual(slugs, {
            'p1', 'p2', 'pm', 'pg', 'cm', 'pmm', 'pmg', 'pgg', 'cmm',
            'p4', 'p4m', 'p4g', 'p3', 'p3m1', 'p31m', 'p6', 'p6m',
        })

    def test_orbit_sizes_match_theory(self):
        """Orbit cardinalities are fixed by the group: ratio of the
        point group's order to the lattice's symmetry."""
        expected = {
            'p1': 1, 'p2': 2,
            'pm': 2, 'pg': 2, 'cm': 2,
            'pmm': 4, 'pmg': 4, 'pgg': 4, 'cmm': 4,
            'p4': 4, 'p4m': 8, 'p4g': 8,
            'p3': 3, 'p3m1': 6, 'p31m': 6,
            'p6': 6, 'p6m': 12,
        }
        for g in groups.GROUPS:
            self.assertEqual(g.orbit_size, expected[g.slug],
                              f'group {g.slug}: orbit size mismatch')

    def test_basis_vectors_nondegenerate(self):
        """No group can have parallel basis vectors (zero determinant)."""
        for g in groups.GROUPS:
            ax, ay = g.a
            bx, by = g.b
            det = ax * by - ay * bx
            self.assertGreater(abs(det), 1e-6,
                                f'{g.slug}: degenerate lattice basis')


class RenderTest(TestCase):
    def test_render_includes_one_use_per_orbit_x_lattice(self):
        """Every orbit element appears at least once in the output;
        for a smallish viewport the count tracks (orbit × lattice)."""
        g = groups.get('p4m')   # orbit 8
        body = svg.render(g, motifs.get('comma').svg_body,
                            svg.RenderConfig(tile_mm=40.0,
                                                viewport_w_mm=120.0,
                                                viewport_h_mm=120.0,
                                                margin_mm=5.0))
        # The renderer emits one <use href="#motif" .../> per (lattice cell,
        # orbit element).  At tile=40 in a 120×120 box (lattice = square)
        # we expect a few cells × 8 orbit elements = a few dozen uses.
        n_use = body.count('<use href="#motif"')
        self.assertGreater(n_use, 24,
                            f'p4m yielded only {n_use} motif placements')
        self.assertIn('viewBox="0 0 120.0 120.0"', body)

    def test_p1_has_smallest_motif_count(self):
        """For the same viewport, p1 (1-element orbit) should yield
        fewer motif placements than p6m (12-element orbit)."""
        cfg = svg.RenderConfig(tile_mm=40.0, viewport_w_mm=120.0,
                                viewport_h_mm=120.0, margin_mm=5.0)
        n1 = svg.render(groups.get('p1'),
                         motifs.get('comma').svg_body, cfg
                         ).count('<use href="#motif"')
        n6m = svg.render(groups.get('p6m'),
                          motifs.get('comma').svg_body, cfg
                          ).count('<use href="#motif"')
        self.assertLess(n1, n6m,
                         'p6m must emit more motif copies than p1 '
                         'in the same viewport')

    def test_unknown_motif_falls_back_silently_in_view(self):
        """View path falls back to DEFAULT_MOTIF when motif_slug is
        bogus.  No 500."""
        User = get_user_model()
        u = User.objects.create_user(username='esc-test', password='x')
        self.client.force_login(u)
        r = self.client.get(reverse('escher:render_svg'),
                              {'group': 'p4m', 'motif_slug': 'no-such-thing'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<svg', r.content)

    def test_unknown_group_404s(self):
        User = get_user_model()
        u = User.objects.create_user(username='esc-404', password='x')
        self.client.force_login(u)
        r = self.client.get(reverse('escher:render_svg'),
                              {'group': 'not-a-group'})
        self.assertEqual(r.status_code, 404)


class ViewsTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='esc-views', password='x')
        self.client.force_login(self.user)

    def test_index_renders(self):
        r = self.client.get(reverse('escher:index'))
        self.assertEqual(r.status_code, 200)
        # Every group slug should appear on the index card list.
        body = r.content.decode()
        for g in groups.GROUPS:
            self.assertIn(g.slug, body, f'{g.slug} missing from index')

    def test_group_detail_renders(self):
        r = self.client.get(reverse('escher:group_detail',
                                      kwargs={'slug': 'p6m'}))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'p6m', r.content)

    def test_groups_grid_emits_one_svg_per_group(self):
        r = self.client.get(reverse('escher:groups_grid'))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The reference sheet has 17 group labels; check a sample.
        for slug in ('p1', 'p4m', 'p6', 'pgg', 'cm', 'p3m1'):
            self.assertIn(f'>{slug}<', body)

    def test_render_svg_with_cells_overlay(self):
        r = self.client.get(reverse('escher:render_svg'),
                              {'group': 'p4', 'cells': '1', 'tile': '40'})
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # cells overlay → at least one polygon outlining the unit cell.
        self.assertIn('<polygon', body)


class CAMotifTest(TestCase):
    """Smoke-test the CA-frame motif path against a real spoeqi Pact."""

    def setUp(self):
        from spoeqi.models import Pact, RULE_TABLE_SIZE
        # All-zero rule + xoshiro seed: produces a deterministic non-empty grid.
        self.pact = Pact(name='escher-ca-motif',
                          rule_snapshot=bytes([0] * RULE_TABLE_SIZE))
        self.pact.save()
        User = get_user_model()
        self.user = User.objects.create_user(username='esc-ca', password='x')
        self.client.force_login(self.user)

    def test_ca_motif_renders_in_render_svg(self):
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p3', 'motif': 'spoeqi_component',
            'pact': self.pact.slug, 'component': '0', 'gen': '0',
            'tile': '40',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The motif is a hex grid → many <polygon> children inside the
        # <symbol id="motif">.
        self.assertIn('<symbol id="motif"', body)
        self.assertGreater(body.count('<polygon'), 50,
                            'CA motif should contribute many hex polygons')

    def test_bad_pact_slug_produces_placeholder(self):
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p1', 'motif': 'spoeqi_component',
            'pact': 'no-such-pact', 'component': '0',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'not found', r.content)


class TilesmithMotifTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='esc-ts', password='x')
        self.client.force_login(self.user)
        from tilesmith.models import TileSpec
        self.spec = TileSpec.objects.create(
            slug='esc-bump', name='Esc bump',
            base_w=64, base_h=64,
            edges_json=[[{'p': 0.5, 'off': 16}], [], [], [], [], []],
        )

    def test_tilesmith_motif_renders_polygon(self):
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p4', 'motif': 'tilesmith_tile',
            'tile_slug': self.spec.slug, 'tile': '30',
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        # The motif is one filled polygon inside the <symbol>; the
        # group orbit + lattice produce many <use> placements.
        self.assertIn('<symbol id="motif"', body)
        self.assertIn('<polygon', body)
        self.assertGreater(body.count('<use href="#motif"'), 30)

    def test_missing_tile_slug_shows_placeholder(self):
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p4', 'motif': 'tilesmith_tile',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'missing', r.content)

    def test_unknown_tile_slug_shows_placeholder(self):
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p1', 'motif': 'tilesmith_tile',
            'tile_slug': 'no-such-tile',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'not found', r.content)


class UploadMotifTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='esc-up', password='x')
        self.client.force_login(self.user)

    def _tiny_png(self) -> bytes:
        """A valid 2×2 PNG so PIL can read its dimensions."""
        import base64
        # 2×2 red/blue PNG generated with PIL.  Embedded as base64 so we
        # don't need PIL at test time to generate it.
        return base64.b64decode(
            b'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEUlE'
            b'QVR4nGP8//8/AwwwMwACBQEA/H79zAAAAABJRU5ErkJggg=='
        )

    def test_upload_creates_record(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import UploadedMotif
        f = SimpleUploadedFile('test.png', self._tiny_png(),
                                content_type='image/png')
        r = self.client.post(reverse('escher:uploads'), {'image': f},
                               follow=False)
        # Redirects back to the list after upload.
        self.assertEqual(r.status_code, 302)
        rec = UploadedMotif.objects.first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.width, 2)
        self.assertEqual(rec.height, 2)
        self.assertEqual(len(rec.content_hash), 64)
        rec.file.delete(save=False)
        rec.delete()

    def test_dedup_same_content(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import UploadedMotif
        b = self._tiny_png()
        f1 = SimpleUploadedFile('a.png', b, content_type='image/png')
        f2 = SimpleUploadedFile('b.png', b, content_type='image/png')
        self.client.post(reverse('escher:uploads'), {'image': f1})
        self.client.post(reverse('escher:uploads'), {'image': f2})
        # Same content hash → only one record despite two uploads.
        self.assertEqual(UploadedMotif.objects.count(), 1)
        for rec in UploadedMotif.objects.all():
            rec.file.delete(save=False); rec.delete()

    def test_motif_references_media_url_by_default(self):
        """Default mode points <image> at the served /media/ path so
        the SVG renders reliably inside iframe previews.  Some
        browsers refuse to load <image href="data:..."> when the SVG
        is loaded as a standalone iframe document, so the base64 path
        is opt-in via ?embed_image=base64."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import UploadedMotif
        f = SimpleUploadedFile('m.png', self._tiny_png(),
                                content_type='image/png')
        self.client.post(reverse('escher:uploads'), {'image': f})
        rec = UploadedMotif.objects.first()
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p4m', 'motif': 'upload',
            'upload_slug': rec.slug,
        })
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn(f'<image href="{rec.file.url}"', body)
        self.assertNotIn('data:image/png;base64', body)
        rec.file.delete(save=False); rec.delete()

    def test_motif_embed_base64_opt_in(self):
        """?embed_image=base64 forces self-contained base64 mode for
        people who want to email/save the SVG file."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import UploadedMotif
        f = SimpleUploadedFile('m.png', self._tiny_png(),
                                content_type='image/png')
        self.client.post(reverse('escher:uploads'), {'image': f})
        rec = UploadedMotif.objects.first()
        r = self.client.get(reverse('escher:render_svg'), {
            'group': 'p4m', 'motif': 'upload',
            'upload_slug': rec.slug,
            'embed_image': 'base64',
        })
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'data:image/png;base64,', r.content)
        rec.file.delete(save=False); rec.delete()


class CompositionPersistenceTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='esc-c', password='x')
        self.client.force_login(self.user)

    def test_save_then_load_round_trip(self):
        from escher.models import Composition
        r = self.client.post(reverse('escher:composition_save'), {
            'name': 'Cool p6 comp',
            'group': 'p6',
            'motif': 'stock',
            'motif_slug': 'spiral',
            'tile': '24',
            'landscape': '1',
        }, follow=False)
        self.assertEqual(r.status_code, 302)
        comp = Composition.objects.get(name='Cool p6 comp')
        self.assertEqual(comp.group_slug, 'p6')
        self.assertEqual(comp.motif_kind, 'stock')
        self.assertEqual(comp.motif_spec, {'slug': 'spiral'})
        self.assertAlmostEqual(comp.tile_mm, 24.0)
        self.assertTrue(comp.landscape)

        # Detail page renders with prefilled JSON.
        r = self.client.get(reverse('escher:composition_detail',
                                      kwargs={'slug': comp.slug}))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn('"group": "p6"', body)
        self.assertIn('"motif_slug": "spiral"', body)
        # The page H1 displays the composition name when one is loaded.
        self.assertIn('Cool p6 comp', body)

    def test_save_requires_name(self):
        r = self.client.post(reverse('escher:composition_save'),
                              {'group': 'p4m'})
        self.assertEqual(r.status_code, 302)   # bounced back
        from escher.models import Composition
        self.assertEqual(Composition.objects.count(), 0)

    def test_spec_captures_motif_kind(self):
        from escher.models import Composition
        self.client.post(reverse('escher:composition_save'), {
            'name': 'spoeqi mosaic',
            'group': 'p3', 'motif': 'spoeqi_component',
            'pact': 'p-slug', 'component': '7', 'gen': '12',
        })
        comp = Composition.objects.first()
        self.assertEqual(comp.motif_kind, 'spoeqi_component')
        self.assertEqual(comp.motif_spec, {
            'pact': 'p-slug', 'component': 7, 'generation': 12,
        })

    def test_delete_removes_record(self):
        from escher.models import Composition
        self.client.post(reverse('escher:composition_save'), {
            'name': 'doomed', 'group': 'p2', 'motif': 'stock',
        })
        slug = Composition.objects.get(name='doomed').slug
        r = self.client.post(reverse('escher:composition_delete',
                                       kwargs={'slug': slug}))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Composition.objects.count(), 0)

    def test_list_renders(self):
        self.client.post(reverse('escher:composition_save'), {
            'name': 'listed', 'group': 'cmm', 'motif': 'stock',
            'motif_slug': 'comma',
        })
        r = self.client.get(reverse('escher:composition_list'))
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'listed', r.content)
        self.assertIn(b'cmm', r.content)
