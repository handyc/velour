"""Refresh Part prices from registered sources.

Iterates `powerlab.sources.enabled_sources()`. Mouser needs an API key
(env MOUSER_API_KEY or mouser_api_key.txt at BASE_DIR). Conrad scrapes
their public search page — fragile by design, and EUR prices are
converted to USD at the pinned rate in powerlab.sources. AliExpress is
manual-only and is skipped by this command.

Usage:
    venv/bin/python manage.py powerlab_refresh_prices
    venv/bin/python manage.py powerlab_refresh_prices --slug=attiny13a
    venv/bin/python manage.py powerlab_refresh_prices --source=conrad
    venv/bin/python manage.py powerlab_refresh_prices --dry-run
"""
import time

from django.core.management.base import BaseCommand

from powerlab.models import Part, PartPriceSnapshot
from powerlab import sources as psources


class Command(BaseCommand):
    help = "Refresh Part prices from every enabled source."

    def add_arguments(self, parser):
        parser.add_argument(
            '--slug', default='',
            help='Only refresh this one part slug.',
        )
        parser.add_argument(
            '--source', default='',
            help='Only query this source (e.g. Mouser, Conrad).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be recorded without writing snapshots.',
        )
        parser.add_argument(
            '--limit', type=int, default=0,
            help='Cap the number of parts queried per source (0 = no cap).',
        )

    def handle(self, *args, **opts):
        active = psources.enabled_sources()
        if opts['source']:
            picked = psources.by_name(opts['source'])
            if picked is None or not picked.get('auto_refresh'):
                self.stdout.write(self.style.ERROR(
                    f"source {opts['source']!r} not found or not auto-refreshable"
                ))
                return
            active = [picked] if picked['enabled']() else []

        if not active:
            self.stdout.write(self.style.WARNING(
                "no auto-refresh sources enabled — set MOUSER_API_KEY to "
                "enable Mouser, or rely on manual snapshots from part pages"
            ))
            return

        qs = Part.objects.exclude(mpn='').exclude(mpn__isnull=True)
        if opts['slug']:
            qs = qs.filter(slug=opts['slug'])
        if opts['limit']:
            qs = qs[:opts['limit']]

        parts = list(qs)
        if not parts:
            self.stdout.write(self.style.WARNING(
                "no parts match — set MPNs on your parts first"
            ))
            return

        dry_run = opts['dry_run']
        recorded = 0
        touched = set()

        for source in active:
            name = source['name']
            self.stdout.write(self.style.MIGRATE_HEADING(f"-- {name} --"))
            for part in parts:
                if source.get('throttle_s'):
                    time.sleep(source['throttle_s'])
                result = source['fetch'](part)
                if not result or result.get('error'):
                    err = (result or {}).get('error') or 'no result'
                    self.stdout.write(
                        f"  [skip] {part.slug} ({part.mpn}): {err}"
                    )
                    continue
                unit = result['unit_price_usd']
                qty = int(result.get('qty_break') or 1)
                url = (result.get('source_url') or '')[:500]
                tag = 'dry-run' if dry_run else 'recorded'
                self.stdout.write(
                    f"  [{tag}] {part.slug}: {name} ${unit} @ qty {qty}"
                )
                if dry_run:
                    continue
                PartPriceSnapshot.objects.create(
                    part=part,
                    vendor=source['vendor_label'],
                    unit_price_usd=unit,
                    qty_break=qty,
                    source_url=url,
                )
                recorded += 1
                touched.add(part.pk)

        # Recompute the blended avg once per touched part (not once per
        # snapshot) — cheaper and correct.
        if not dry_run and touched:
            for p in Part.objects.filter(pk__in=touched):
                p.recompute_avg_price()

        self.stdout.write(self.style.SUCCESS(
            f"done — {recorded} snapshot{'' if recorded == 1 else 's'} written "
            f"across {len(active)} source{'' if len(active) == 1 else 's'}"
        ))
