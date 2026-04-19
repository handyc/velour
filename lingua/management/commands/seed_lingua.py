"""Seed the 10 priority languages + English baseline."""

from django.core.management.base import BaseCommand

from lingua.models import Language


LANGS = [
    # code, name, endonym, script, rtl, low_resource
    ('en',      'English',           'English',    'latin',      False, False),
    ('nl',      'Dutch',             'Nederlands', 'latin',      False, False),
    ('zh-Hans', 'Chinese (Simp.)',   '简体中文',    'han',        False, False),
    ('es',      'Spanish',           'Español',    'latin',      False, False),
    ('fr',      'French',            'Français',   'latin',      False, False),
    ('he',      'Modern Hebrew',     'עברית',      'hebrew',     True,  False),
    ('grc',     'Ancient Greek',     'Ἑλληνική',   'greek',      False, True),
    ('la',      'Latin',             'Latina',     'latin',      False, True),
    ('san',     'Sanskrit',          'संस्कृतम्',       'devanagari', False, True),
    ('ja',      'Japanese',          '日本語',      'hiragana',   False, False),
    ('ko',      'Korean',            '한국어',      'hangul',     False, False),
]


class Command(BaseCommand):
    help = "Seed Lingua's priority languages."

    def handle(self, *args, **opts):
        created = 0
        updated = 0
        for code, name, endonym, script, rtl, low_resource in LANGS:
            obj, was_created = Language.objects.update_or_create(
                code=code,
                defaults={
                    'name': name, 'endonym': endonym,
                    'script': script, 'rtl': rtl,
                    'low_resource': low_resource,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'lingua: {created} created, {updated} updated'
        ))
