"""Phase 1a tests for the signs app — schema + frames.json shape."""

from django.test import TestCase, Client
from django.urls import reverse

from signs.models import Language, Variety, Lemma, Sign, Frame


class SchemaTest(TestCase):
    def test_language_variety_slug_autofill(self):
        lang = Language.objects.create(name='Ghanaian Sign Language')
        self.assertEqual(lang.slug, 'ghanaian-sign-language')
        v = Variety.objects.create(language=lang, name='GSL-English')
        self.assertTrue(v.slug.startswith('ghanaian-sign-language-gsl-english'))

    def test_variety_unique_per_language(self):
        lang = Language.objects.create(name='Test SL')
        Variety.objects.create(language=lang, name='dialect-1')
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Variety.objects.create(language=lang, name='dialect-1')

    def test_sign_slug_includes_lemma_and_variety_name(self):
        lang = Language.objects.create(name='Test SL')
        v = Variety.objects.create(language=lang, name='v1')
        l = Lemma.objects.create(gloss='WATER')
        s = Sign.objects.create(lemma=l, variety=v)
        self.assertIn('water', s.slug)
        # Slug uses variety *name* (v1), not slug (test-sl-v1), so
        # the language name doesn't appear twice in URLs.
        self.assertIn('v1', s.slug)
        self.assertNotIn('test-sl', s.slug)

    def test_frame_unique_index_per_sign(self):
        lang = Language.objects.create(name='Test SL')
        v = Variety.objects.create(language=lang, name='v1')
        l = Lemma.objects.create(gloss='WATER')
        s = Sign.objects.create(lemma=l, variety=v)
        Frame.objects.create(sign=s, index=0, cylinder_rotations=[[0,0,0]]*30)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            Frame.objects.create(sign=s, index=0, cylinder_rotations=[[0,0,0]]*30)


class FramesJsonTest(TestCase):
    def setUp(self):
        lang = Language.objects.create(name='Test SL')
        v = Variety.objects.create(language=lang, name='v1')
        lemma = Lemma.objects.create(gloss='REST')
        self.sign = Sign.objects.create(lemma=lemma, variety=v, fps=24)
        Frame.objects.create(sign=self.sign, index=0, duration_ms=100,
                             cylinder_rotations=[[0.1, 0.2, 0.3]] * 30,
                             palm_r_pos=[0.5, 0.0, 0.0])
        Frame.objects.create(sign=self.sign, index=1, duration_ms=200,
                             cylinder_rotations=[[0.4, 0.5, 0.6]] * 30)

    def test_json_shape(self):
        c = Client()
        r = c.get(reverse('signs:frames_json', args=[self.sign.slug]))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data['name'], 'REST')
        self.assertEqual(data['fps'], 24)
        self.assertEqual(len(data['frames']), 2)
        self.assertEqual(len(data['frames'][0]['pose']), 30)
        self.assertEqual(data['frames'][0]['pose'][0], [0.1, 0.2, 0.3])
        self.assertEqual(data['frames'][0]['duration'], 100)
        self.assertEqual(data['frames'][0]['palm_r'], [0.5, 0.0, 0.0])
        self.assertEqual(data['frames'][0]['palm_l'], [])
        # default wrist rotation is filled in by view
        self.assertEqual(data['frames'][0]['wrist_l'], [0, 0, 0])

    def test_frames_ordered(self):
        c = Client()
        data = c.get(reverse('signs:frames_json', args=[self.sign.slug])).json()
        self.assertEqual(data['frames'][0]['duration'], 100)
        self.assertEqual(data['frames'][1]['duration'], 200)


class IndexAndDetailTest(TestCase):
    def setUp(self):
        lang = Language.objects.create(name='Test SL')
        v = Variety.objects.create(language=lang, name='v1')
        lemma = Lemma.objects.create(gloss='HELLO')
        self.sign = Sign.objects.create(lemma=lemma, variety=v)

    def test_index_renders(self):
        r = Client().get(reverse('signs:index'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Test SL')
        self.assertContains(r, 'HELLO')

    def test_detail_renders(self):
        r = Client().get(reverse('signs:detail', args=[self.sign.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'HELLO')
        self.assertContains(r, 'Test SL')

    def test_viewer_renders(self):
        r = Client().get(reverse('signs:viewer', args=[self.sign.slug]))
        self.assertEqual(r.status_code, 200)
        # The viewer fetches /signs/<slug>/frames.json
        self.assertContains(r, reverse('signs:frames_json', args=[self.sign.slug]))


class SlugShapeTest(TestCase):
    """The post-Phase-1c slug should be `<lemma>-<variety-name>`,
    not `<lemma>-<variety-slug>` (which redundantly included the
    language name)."""

    def test_sign_slug_does_not_include_language_name(self):
        lang = Language.objects.create(name='Ghanaian Sign Language')
        v = Variety.objects.create(language=lang, name='gsl-lexicon-2021')
        l = Lemma.objects.create(gloss='WATER')
        s = Sign.objects.create(lemma=l, variety=v)
        self.assertEqual(s.slug, 'water-gsl-lexicon-2021')

    def test_collision_appends_numeric_tail(self):
        lang = Language.objects.create(name='L')
        v = Variety.objects.create(language=lang, name='v')
        l = Lemma.objects.create(gloss='HELLO')
        a = Sign.objects.create(lemma=l, variety=v)
        # Second Sign with same (lemma, variety) — protocol allows
        # multiple recordings — should get a -2 suffix.
        b = Sign.objects.create(lemma=l, variety=v)
        self.assertEqual(a.slug, 'hello-v')
        self.assertEqual(b.slug, 'hello-v-2')


class IndexFilteringAndPaginationTest(TestCase):
    def setUp(self):
        lang = Language.objects.create(name='Test SL')
        self.v1 = Variety.objects.create(language=lang, name='v1')
        self.v2 = Variety.objects.create(language=lang, name='v2')
        for g in ('WATER', 'WIND', 'WOOD', 'WALK', 'WORM'):
            Sign.objects.create(lemma=Lemma.objects.create(gloss=g),
                                variety=self.v1)
        Sign.objects.create(lemma=Lemma.objects.create(gloss='FIRE'),
                            variety=self.v2)

    def test_search_by_lemma(self):
        r = Client().get(reverse('signs:index') + '?q=WAL')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'WALK')
        self.assertNotContains(r, '<span class="gloss">FIRE</span>', html=False)
        self.assertNotContains(r, '<span class="gloss">WATER</span>', html=False)

    def test_filter_by_variety(self):
        r = Client().get(reverse('signs:index') + f'?v={self.v2.slug}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'FIRE')
        self.assertNotContains(r, '>WATER<')

    def test_random_redirects_to_a_viewer(self):
        r = Client().get(reverse('signs:random'), follow=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn('/signs/view/', r['Location'])

    def test_random_respects_variety_filter(self):
        r = Client().get(reverse('signs:random') + f'?v={self.v2.slug}', follow=False)
        self.assertEqual(r.status_code, 302)
        # Only one sign in v2 → must redirect to fire viewer
        self.assertIn('fire-v2', r['Location'])

    def test_random_404s_when_empty(self):
        Sign.objects.all().delete()
        r = Client().get(reverse('signs:random'))
        self.assertEqual(r.status_code, 404)
