"""Tests for the graphs ring buffer + sysinfo bridge."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from graphs.models import SystemSample
from graphs.views import RETAIN_HOURS, take_persistent_sample


class SystemSampleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('s', password='pw')

    def setUp(self):
        self.client.force_login(self.user)

    def test_take_persistent_sample_creates_row(self):
        self.assertEqual(SystemSample.objects.count(), 0)
        row = take_persistent_sample(force=True)
        self.assertIsNotNone(row)
        self.assertEqual(SystemSample.objects.count(), 1)
        self.assertGreaterEqual(row.cpu_pct, 0)
        self.assertLessEqual(row.cpu_pct, 100)

    def test_throttle_blocks_immediate_resample(self):
        take_persistent_sample(force=True)
        again = take_persistent_sample(force=False)
        self.assertIsNone(again)
        self.assertEqual(SystemSample.objects.count(), 1)

    def test_force_bypasses_throttle(self):
        take_persistent_sample(force=True)
        take_persistent_sample(force=True)
        self.assertEqual(SystemSample.objects.count(), 2)

    def test_prune_drops_old_rows(self):
        take_persistent_sample(force=True)
        # Backdate the existing row past the retention window.
        old_ts = timezone.now() - timedelta(hours=RETAIN_HOURS + 1)
        SystemSample.objects.update(ts=old_ts)
        fresh = take_persistent_sample(force=True)
        self.assertEqual(SystemSample.objects.count(), 1)
        self.assertEqual(SystemSample.objects.first().pk, fresh.pk)

    def test_history_endpoint_returns_parallel_arrays(self):
        a = take_persistent_sample(force=True)
        b = take_persistent_sample(force=True)
        self.assertNotEqual(a.pk, b.pk)
        resp = self.client.get(reverse('graphs:history_json'), {'hours': 1})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['count'], 2)
        for key in ('ts', 'cpu_pct', 'mem_used_pct', 'load1', 'swap_pct', 'entropy'):
            self.assertIn(key, data)
            self.assertEqual(len(data[key]), 2)

    def test_history_endpoint_clamps_hours(self):
        resp = self.client.get(reverse('graphs:history_json'), {'hours': 9999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['hours'], RETAIN_HOURS)

    def test_sample_endpoint_persists_opportunistically(self):
        self.assertEqual(SystemSample.objects.count(), 0)
        resp = self.client.get(reverse('graphs:sample'))
        self.assertEqual(resp.status_code, 200)
        # First call has no prior row, so the throttle check passes and
        # a sample lands.
        self.assertEqual(SystemSample.objects.count(), 1)
        # An immediate second call is throttled.
        self.client.get(reverse('graphs:sample'))
        self.assertEqual(SystemSample.objects.count(), 1)


class SysinfoSnapshotTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('s2', password='pw')

    def setUp(self):
        self.client.force_login(self.user)

    def test_snapshot_endpoint_shape(self):
        resp = self.client.get(reverse('sysinfo:snapshot'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in ('cpu', 'memory', 'disk_lines', 'net_lines', 'ps_rows', 'who_lines'):
            self.assertIn(key, data)
        self.assertIsInstance(data['cpu'], dict)
        self.assertIsInstance(data['ps_rows'], list)

    def test_ps_rows_have_expected_fields(self):
        resp = self.client.get(reverse('sysinfo:snapshot'))
        rows = resp.json()['ps_rows']
        self.assertGreater(len(rows), 0,
                           'expected at least one process in the snapshot')
        for r in rows[:5]:
            for key in ('pid', 'user', 'pcpu', 'pmem', 'rss_kb', 'comm'):
                self.assertIn(key, r)
            self.assertIsInstance(r['pid'], int)
            self.assertGreaterEqual(r['pcpu'], 0)
            self.assertGreaterEqual(r['rss_kb'], 0)

    def test_ps_table_sorted_by_pcpu_desc(self):
        resp = self.client.get(reverse('sysinfo:snapshot'))
        rows = resp.json()['ps_rows']
        for a, b in zip(rows, rows[1:]):
            self.assertGreaterEqual(a['pcpu'], b['pcpu'])
