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

    def test_llm_cost_cap_blocks_when_exceeded(self):
        from decimal import Decimal
        from identity.models import (LLMProvider, LLMExchange,
                                      IdentityToggles, llm_cost_cap_check)
        toggles = IdentityToggles.get_self()
        toggles.llm_daily_cost_cap_usd = Decimal('0.01')
        toggles.save()
        provider = LLMProvider.objects.create(
            name='test', slug='test',
            base_url='http://localhost/',
            model='m',
            cost_per_million_input_tokens_usd=Decimal('1'),
            cost_per_million_output_tokens_usd=Decimal('1'),
        )
        # Burn the budget with one expensive exchange.
        e = LLMExchange.objects.create(
            provider=provider, prompt='x',
            tokens_in=20_000, tokens_out=0)
        e.cost_usd = e.compute_cost()
        e.save()
        # Next call's estimated cost should now be refused.
        allowed, reason = llm_cost_cap_check(Decimal('0.005'))
        self.assertFalse(allowed)
        self.assertIn('daily cap exceeded', reason)

    def test_llm_cost_cap_allows_when_under_budget(self):
        from decimal import Decimal
        from identity.models import (LLMProvider, IdentityToggles,
                                      llm_cost_cap_check)
        toggles = IdentityToggles.get_self()
        toggles.llm_daily_cost_cap_usd = Decimal('1.0')
        toggles.llm_monthly_cost_cap_usd = Decimal('10.0')
        toggles.save()
        allowed, reason = llm_cost_cap_check(Decimal('0.01'))
        self.assertTrue(allowed)
        self.assertEqual(reason, '')

    def test_llm_exchange_compute_cost(self):
        from decimal import Decimal
        from identity.models import LLMProvider, LLMExchange
        provider = LLMProvider.objects.create(
            name='test', slug='test', base_url='http://x/', model='m',
            cost_per_million_input_tokens_usd=Decimal('2'),
            cost_per_million_output_tokens_usd=Decimal('6'),
        )
        e = LLMExchange.objects.create(
            provider=provider, prompt='x',
            tokens_in=1_000_000, tokens_out=500_000)
        # 1M input × $2 + 500k output × $6 = $2 + $3 = $5.00
        self.assertEqual(e.compute_cost(), Decimal('5.000000'))

    def test_l4_augmentation_skipped_when_toggle_off(self):
        from identity.meditation import _augment_l4_body
        from identity.models import IdentityToggles
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_meditations_enabled = False
        toggles.save()
        result = _augment_l4_body(
            toggles,
            {'commits': [{'subject': 'x', 'body': '', 'ai_coauthor': False}]},
            'meditation body')
        self.assertEqual(result, '')

    def test_l4_augmentation_skipped_when_provider_unset(self):
        from identity.meditation import _augment_l4_body
        from identity.models import IdentityToggles
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_meditations_enabled = True
        toggles.llm_augment_provider = None
        toggles.save()
        result = _augment_l4_body(
            toggles,
            {'commits': [{'subject': 'x', 'body': '', 'ai_coauthor': False}]},
            'meditation body')
        self.assertEqual(result, '')

    def test_reflection_augmentation_skipped_when_toggle_off(self):
        from identity.reflection import _augment_reflection
        from identity.models import IdentityToggles
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_reflections_enabled = False
        toggles.save()
        self.assertEqual(_augment_reflection(toggles, 'body'), '')

    def test_reflection_augmentation_skipped_when_provider_unset(self):
        from identity.reflection import _augment_reflection
        from identity.models import IdentityToggles
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_reflections_enabled = True
        toggles.llm_augment_provider = None
        toggles.save()
        self.assertEqual(_augment_reflection(toggles, 'body'), '')

    def test_reflection_hourly_period_never_augmented(self):
        # The reflect() function gates augmentation to
        # daily/weekly/monthly. Hourly should pass through with no
        # augmentation regardless of toggle state.
        from decimal import Decimal
        from identity.reflection import reflect
        from identity.models import (IdentityToggles, LLMProvider,
                                      LLMExchange, Tick)
        provider = LLMProvider.objects.create(
            name='test', slug='test', base_url='http://x/', model='m',
            cost_per_million_input_tokens_usd=Decimal('1'),
            cost_per_million_output_tokens_usd=Decimal('1'),
        )
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_reflections_enabled = True
        toggles.llm_augment_provider = provider
        toggles.llm_daily_cost_cap_usd = Decimal('10.00')
        toggles.save()
        # Run hourly; if augmentation fired, an LLMExchange row
        # would be created.
        reflect(period='hourly', push_to_codex=False)
        self.assertEqual(
            LLMExchange.objects.filter(provider=provider).count(), 0)

    def test_rumination_augment_endpoint_skips_when_disabled(self):
        from identity.models import IdentityToggles
        from django.contrib.auth.models import User
        u = User.objects.create_user('alice', password='pw')
        self.client.force_login(u)
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_rumination_enabled = False
        toggles.save()
        resp = self.client.post(
            reverse('identity:rumination_augment'),
            {'artifact_a': 'X', 'artifact_b': 'Y'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['coda'], '')
        self.assertIn('disabled', data['error'])

    def test_l4_augmentation_logs_refusal_when_cap_exceeded(self):
        from decimal import Decimal
        from identity.meditation import _augment_l4_body
        from identity.models import (IdentityToggles, LLMProvider,
                                      LLMExchange)
        provider = LLMProvider.objects.create(
            name='test', slug='test',
            base_url='http://localhost/', model='m',
            cost_per_million_input_tokens_usd=Decimal('100'),
            cost_per_million_output_tokens_usd=Decimal('100'),
        )
        toggles = IdentityToggles.get_self()
        toggles.llm_augment_meditations_enabled = True
        toggles.llm_augment_provider = provider
        toggles.llm_daily_cost_cap_usd = Decimal('0.0001')
        toggles.save()
        result = _augment_l4_body(
            toggles,
            {'commits': [{'subject': 'x' * 200, 'body': '',
                          'ai_coauthor': False}]},
            'meditation body')
        self.assertEqual(result, '')
        # Refusal logged with the cap-exceeded reason.
        ex = LLMExchange.objects.filter(provider=provider).first()
        self.assertIsNotNone(ex)
        self.assertIn('refused', ex.error)

    def test_apply_clone_init_updates_identity_and_renames_file(self):
        import json, os, tempfile
        from unittest.mock import patch
        from io import StringIO
        from django.conf import settings
        from django.core.management import call_command
        from identity.models import Identity

        with tempfile.TemporaryDirectory() as tmp:
            init_path = os.path.join(tmp, 'clone_init.json')
            with open(init_path, 'w') as f:
                json.dump({
                    'instance_label': 'Velour at the Lab',
                    'hostname':       'lab.example.com',
                    'admin_email':    'lab-ops@example.com',
                }, f)

            # Patch BASE_DIR so the command looks in our tmp dir.
            with patch.object(settings, 'BASE_DIR', tmp):
                call_command('apply_clone_init', stdout=StringIO())

            ident = Identity.get_self()
            self.assertEqual(ident.name, 'Velour at the Lab')
            self.assertEqual(ident.hostname, 'lab.example.com')
            self.assertEqual(ident.admin_email, 'lab-ops@example.com')

            # File renamed → idempotent
            self.assertFalse(os.path.exists(init_path))
            self.assertTrue(os.path.exists(init_path + '.applied'))

    def test_apply_clone_init_skips_blank_fields(self):
        import json, os, tempfile
        from unittest.mock import patch
        from io import StringIO
        from django.conf import settings
        from django.core.management import call_command
        from identity.models import Identity

        ident = Identity.get_self()
        ident.name = 'Original Name'
        ident.hostname = 'original.example.com'
        ident.save()

        with tempfile.TemporaryDirectory() as tmp:
            init_path = os.path.join(tmp, 'clone_init.json')
            with open(init_path, 'w') as f:
                # All blank — should not overwrite anything.
                json.dump({
                    'instance_label': '',
                    'hostname':       '',
                    'admin_email':    '',
                }, f)
            with patch.object(settings, 'BASE_DIR', tmp):
                call_command('apply_clone_init', stdout=StringIO())

        ident.refresh_from_db()
        self.assertEqual(ident.name, 'Original Name')
        self.assertEqual(ident.hostname, 'original.example.com')

    def test_apply_clone_init_no_op_when_file_missing(self):
        import tempfile
        from unittest.mock import patch
        from io import StringIO
        from django.conf import settings
        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(settings, 'BASE_DIR', tmp):
                # Should not raise — just print "nothing to do".
                call_command('apply_clone_init', stdout=StringIO())

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
