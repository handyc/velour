"""Import a manuscript file into a new Codex Manual from the CLI.

    python manage.py import_manuscript path/to/book.docx --title "The Book"
    python manage.py import_manuscript notes.html --title "Notes" --subtitle "2026"
    python manage.py import_manuscript paper.tex --title "Paper" --format complete

The command reads the file, converts it to markdown via the importers
module, splits the result at H1/H2 boundaries, and creates one Section
per chunk. Same code path as the web importer at /codex/import/.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from codex.importers import import_bytes, split_sections, supported_extensions
from codex.models import Manual, Section


class Command(BaseCommand):
    help = 'Import a manuscript file into a new Codex Manual.'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--title', required=True)
        parser.add_argument('--subtitle', default='')
        parser.add_argument('--format', default='short',
                            choices=['quickstart', 'short', 'complete'])

    def handle(self, *args, **opts):
        path = Path(opts['path'])
        if not path.is_file():
            raise CommandError(f'No such file: {path}')
        try:
            md = import_bytes(path.read_bytes(), path.name)
        except ValueError:
            raise CommandError(
                f'Unsupported extension: {path.suffix}. Known: '
                f'{", ".join(supported_extensions())}')
        except (ImportError, RuntimeError) as e:
            raise CommandError(str(e))

        m = Manual(title=opts['title'], subtitle=opts['subtitle'],
                   format=opts['format'])
        m.save()
        pairs = split_sections(md) or [(None, md)]
        for i, (sec_title, body) in enumerate(pairs):
            name = sec_title or ('Preamble' if i == 0 else m.title)
            Section.objects.create(
                manual=m, title=name[:200],
                body=body, sort_order=i * 10,
            )
        self.stdout.write(self.style.SUCCESS(
            f'Imported {path.name} → "{m.title}" '
            f'({len(pairs)} section{"" if len(pairs) == 1 else "s"}) '
            f'[slug: {m.slug}]'))
