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
