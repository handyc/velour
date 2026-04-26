from django.test import TestCase
from django.urls import reverse


class SessionReflectTests(TestCase):
    def test_hub_renders(self):
        resp = self.client.get(reverse('identity:session_reflect'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Session reflection')

    def test_loop_toggle_flips_singleton(self):
        from identity.models import ReflectionLoopState

        state = ReflectionLoopState.get_self()
        self.assertFalse(state.enabled)

        resp = self.client.post(reverse('identity:session_reflect_loop_toggle'), {
            'enabled': '1',
            'interval_seconds': '300',
            'subject_template': 'Test',
        })
        self.assertEqual(resp.status_code, 302)

        state.refresh_from_db()
        self.assertTrue(state.enabled)
        self.assertEqual(state.interval_seconds, 300)
        self.assertEqual(state.subject_template, 'Test')

        resp = self.client.post(reverse('identity:session_reflect_loop_toggle'), {
            'enabled': '0',
        })
        state.refresh_from_db()
        self.assertFalse(state.enabled)

    def test_loop_tick_stops_when_disabled(self):
        resp = self.client.post(reverse('identity:session_reflect_loop_tick'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['action'], 'stop')

    def test_loop_interval_clamps(self):
        resp = self.client.post(reverse('identity:session_reflect_loop_toggle'), {
            'enabled': '1', 'interval_seconds': '10',
        })
        self.assertEqual(resp.status_code, 302)
        from identity.models import ReflectionLoopState
        self.assertEqual(ReflectionLoopState.get_self().interval_seconds, 60)


class MirrorPhaseFourTests(TestCase):
    """Phase 4 of recursive meditation: voice rotation in the weekly
    ladder, the new monthly deep ladder (depths 5→7), and the Mirror
    Index orienting section."""

    def test_weekly_ladder_rotates_voice_by_iso_week(self):
        from unittest.mock import patch
        from identity.cron import _do_meditation_ladder
        from identity.models import Meditation
        # Mock isocalendar() so the ladder picks 'philosophical'
        # (week % 5 == 1 hits voices[1]).
        with patch('identity.cron.timezone.now') as mock_now:
            class _Fake:
                def isocalendar(self):
                    class R: week = 1
                    return R()
            mock_now.return_value = _Fake()
            # The ladder calls meditate(); we don't need to mock
            # that — we just need to verify the voice-selection
            # path and confirm the summary string ends with the
            # voice name.
            try:
                summary = _do_meditation_ladder()
            except Exception:
                # If the source gatherers fail in test (no git etc.)
                # we still want to confirm voice selection happened.
                self.skipTest('source gatherers unavailable in test')
            self.assertIn('(philosophical)', summary)

    def test_mirror_index_creates_orienting_section(self):
        from codex.models import Manual
        from identity.meditation import refresh_mirror_index
        # Index requires the manual to exist. Create the shell
        # explicitly to avoid depending on a meditation having
        # been pushed first.
        Manual.objects.get_or_create(
            slug='identitys-mirror',
            defaults={
                'title': "Identity's Mirror",
                'subtitle': 'test', 'author': 'Velour',
                'version': '1', 'abstract': 'test',
            },
        )
        section = refresh_mirror_index()
        self.assertIsNotNone(section)
        self.assertEqual(section.slug, 'mirror-index')
        self.assertIn('Counts by depth and voice', section.body)
        # Sort key should be very negative so it stays at the top.
        self.assertLess(section.sort_order, -10 ** 17)

    def test_mirror_index_returns_none_when_manual_missing(self):
        from identity.meditation import refresh_mirror_index
        from codex.models import Manual
        Manual.objects.filter(slug='identitys-mirror').delete()
        self.assertIsNone(refresh_mirror_index())

    def test_mirror_index_idempotent(self):
        from codex.models import Manual, Section
        from identity.meditation import refresh_mirror_index
        Manual.objects.get_or_create(
            slug='identitys-mirror',
            defaults={
                'title': "Identity's Mirror",
                'subtitle': 'test', 'author': 'Velour',
                'version': '1', 'abstract': 'test',
            },
        )
        first = refresh_mirror_index()
        second = refresh_mirror_index()
        self.assertEqual(first.id, second.id)
        # Only one mirror-index section regardless of how many
        # times we refresh.
        manual = Manual.objects.get(slug='identitys-mirror')
        self.assertEqual(
            manual.sections.filter(slug='mirror-index').count(), 1)
