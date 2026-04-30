"""Build a HuntCorpus from feature-typed windows of a SequenceRecord.

Usage:
    manage.py hexhunt_seed_corpus <record_pk> \\
        --feature-type CDS --window-size 256 --max 200 \\
        --slug drosoph_chr4_cds

One window per qualifying feature, taken from the feature's first
``window_size`` bases (so it always lines up with a real start codon /
regulatory element / etc.). Features shorter than ``window_size`` are
skipped.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from helix.models import (
    AnnotationFeature, HuntCorpus, HuntWindow, SequenceRecord,
)


class Command(BaseCommand):
    help = 'Materialise a HuntCorpus from a SequenceRecord by feature type.'

    def add_arguments(self, parser):
        parser.add_argument('record_pk', type=int)
        parser.add_argument('--feature-type', default='CDS')
        parser.add_argument('--window-size', type=int, default=256)
        parser.add_argument('--max', type=int, default=200,
                            help='Cap on number of windows.')
        parser.add_argument('--slug', default='',
                            help='Corpus slug; auto-generated if blank.')
        parser.add_argument('--name', default='',
                            help='Human name; auto-generated if blank.')

    def handle(self, *args, **opts):
        try:
            record = SequenceRecord.objects.get(pk=opts['record_pk'])
        except SequenceRecord.DoesNotExist:
            raise CommandError(f'no SequenceRecord with pk={opts["record_pk"]}')

        ft = opts['feature_type']
        wsize = opts['window_size']
        cap = opts['max']

        feats_qs = AnnotationFeature.objects.filter(
            record=record, feature_type=ft,
        ).order_by('start')
        feats = []
        for f in feats_qs:
            if f.length() >= wsize:
                feats.append(f)
            if len(feats) >= cap:
                break
        if not feats:
            raise CommandError(
                f'no {ft!r} features ≥ {wsize} bp on '
                f'{record.title} (pk={record.pk})'
            )

        slug = opts['slug'] or slugify(
            f'{record.accession or record.title} {ft} w{wsize}'
        )[:80]
        name = opts['name'] or f'{record.title} · {ft} · {wsize} bp'

        if HuntCorpus.objects.filter(slug=slug).exists():
            raise CommandError(f'corpus slug {slug!r} already exists')

        with transaction.atomic():
            corpus = HuntCorpus.objects.create(
                slug=slug, name=name, feature_type=ft,
                window_size=wsize, windows_count=len(feats),
                description=(
                    f'Auto-built from {record.title} '
                    f'(accession {record.accession or "—"}); '
                    f'{len(feats)} {ft} features, first {wsize} bp each.'
                ),
            )
            HuntWindow.objects.bulk_create([
                HuntWindow(
                    corpus=corpus, record=record, feature=f,
                    start=f.start, end=f.start + wsize, idx=i,
                )
                for i, f in enumerate(feats)
            ])

        self.stdout.write(self.style.SUCCESS(
            f'Created corpus {slug!r} with {len(feats)} windows '
            f'({record.title}, {ft}, {wsize} bp).'
        ))
