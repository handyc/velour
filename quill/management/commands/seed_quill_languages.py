"""Seed Quill's Language registry with research languages.

Curated for low-resource-language philologists: modern European
research staples + Indic + East Asian + Semitic + classical and
historical scripts. Idempotent — re-run is safe; existing slugs
update in place.

Font stacks lead with the most likely-installed name on Linux/Mac/
Windows that supports the script, then fall back through Noto Sans
(safest cross-platform), then to a generic family. We don't ship
fonts; this is a hint stack the browser falls through.
"""

from django.core.management.base import BaseCommand

from quill.models import Language


SEEDS = [
    # ─── European / research ──────────────────────────────────────
    {
        'slug': 'en', 'name': 'English', 'native_name': 'English',
        'bcp47': 'en', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charter", "Iowan Old Style", "Sitka Text", Georgia, serif',
        'sample_text': 'The quick brown fox jumps over the lazy dog.',
    },
    {
        'slug': 'nl', 'name': 'Dutch', 'native_name': 'Nederlands',
        'bcp47': 'nl', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charter", "Iowan Old Style", "Sitka Text", Georgia, serif',
        'sample_text': 'Pa\'s wijze lynx bezag vroom het fikse aquaduct.',
    },
    {
        'slug': 'de', 'name': 'German', 'native_name': 'Deutsch',
        'bcp47': 'de', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charter", "Iowan Old Style", "Sitka Text", Georgia, serif',
        'sample_text': 'Falsches Üben von Xylophonmusik quält jeden größeren Zwerg.',
    },
    {
        'slug': 'fr', 'name': 'French', 'native_name': 'Français',
        'bcp47': 'fr', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charter", "Iowan Old Style", "Sitka Text", Georgia, serif',
        'sample_text': 'Portez ce vieux whisky au juge blond qui fume.',
    },
    {
        'slug': 'it', 'name': 'Italian', 'native_name': 'Italiano',
        'bcp47': 'it', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charter", "Iowan Old Style", "Sitka Text", Georgia, serif',
        'sample_text': 'Ma la volpe, col suo balzo, ha raggiunto il quieto Fido.',
    },
    {
        'slug': 'la', 'name': 'Latin', 'native_name': 'Latina',
        'bcp47': 'la', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"EB Garamond", "Adobe Garamond Pro", "Garamond", '
                      '"Iowan Old Style", Georgia, serif',
        'sample_text': 'Gallia est omnis divisa in partes tres.',
    },
    {
        'slug': 'grc', 'name': 'Ancient Greek', 'native_name': 'Ἑλληνικά',
        'bcp47': 'grc', 'direction': 'ltr', 'script_name': 'Greek',
        'font_stack': '"GFS Didot", "GFS Neohellenic", "EB Garamond", '
                      '"Noto Serif", "DejaVu Serif", serif',
        'sample_text': 'ἐν ἀρχῇ ἦν ὁ λόγος.',
    },
    {
        'slug': 'el', 'name': 'Greek', 'native_name': 'Ελληνικά',
        'bcp47': 'el', 'direction': 'ltr', 'script_name': 'Greek',
        'font_stack': '"GFS Neohellenic", "Noto Sans Greek", '
                      '"DejaVu Sans", sans-serif',
        'sample_text': 'Ξεσκεπάζω την ψυχοφθόρα βδελυγμία.',
    },

    # ─── Indic ────────────────────────────────────────────────────
    {
        'slug': 'sa', 'name': 'Sanskrit', 'native_name': 'संस्कृतम्',
        'bcp47': 'sa', 'direction': 'ltr', 'script_name': 'Devanagari',
        'font_stack': '"Sanskrit 2003", "Noto Sans Devanagari", '
                      '"Noto Serif Devanagari", "Mangal", serif',
        'sample_text': 'धर्मक्षेत्रे कुरुक्षेत्रे समवेता युयुत्सवः।',
    },
    {
        'slug': 'pi', 'name': 'Pali', 'native_name': 'Pāli',
        'bcp47': 'pi', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Gentium Plus", "Charis SIL", "Doulos SIL", '
                      '"EB Garamond", serif',
        'sample_text': 'Sabbe saṅkhārā aniccā.',
    },
    {
        'slug': 'pi-deva', 'name': 'Pali (Devanagari)', 'native_name': 'पालि',
        'bcp47': 'pi-Deva', 'direction': 'ltr', 'script_name': 'Devanagari',
        'font_stack': '"Sanskrit 2003", "Noto Sans Devanagari", "Mangal", serif',
        'sample_text': 'सब्बे सङ्खारा अनिच्चा।',
    },
    {
        'slug': 'hi', 'name': 'Hindi', 'native_name': 'हिन्दी',
        'bcp47': 'hi', 'direction': 'ltr', 'script_name': 'Devanagari',
        'font_stack': '"Noto Sans Devanagari", "Mangal", "Lohit Devanagari", sans-serif',
        'sample_text': 'ऋषियों को सताने वाले दुष्ट राक्षसों के राजा रावण का सर्वनाश।',
    },

    # ─── Tibetan ──────────────────────────────────────────────────
    {
        'slug': 'bo', 'name': 'Tibetan', 'native_name': 'བོད་སྐད་',
        'bcp47': 'bo', 'direction': 'ltr', 'script_name': 'Tibetan',
        'font_stack': '"Jomolhari", "Noto Sans Tibetan", "Noto Serif Tibetan", '
                      '"Microsoft Himalaya", "Tibetan Machine Uni", serif',
        'sample_text': 'བོད་སྐད་ནི་བོད་དུ་སྐད་ཡིག་ཆེ་ཤོས་ཡིན།',
    },

    # ─── East Asian ───────────────────────────────────────────────
    {
        'slug': 'zh-hans', 'name': 'Chinese (Simplified)', 'native_name': '简体中文',
        'bcp47': 'zh-Hans', 'direction': 'ltr', 'script_name': 'Han',
        'font_stack': '"Noto Sans CJK SC", "Songti SC", "PingFang SC", '
                      '"Microsoft YaHei", "Source Han Sans SC", sans-serif',
        'sample_text': '視野無限廣，窗外有藍天。',
    },
    {
        'slug': 'zh-hant', 'name': 'Chinese (Traditional)', 'native_name': '繁體中文',
        'bcp47': 'zh-Hant', 'direction': 'ltr', 'script_name': 'Han',
        'font_stack': '"Noto Sans CJK TC", "Songti TC", "PingFang TC", '
                      '"Microsoft JhengHei", "Source Han Sans TC", sans-serif',
        'sample_text': '視野無限廣，窗外有藍天。',
    },
    {
        'slug': 'ja', 'name': 'Japanese', 'native_name': '日本語',
        'bcp47': 'ja', 'direction': 'ltr', 'script_name': 'Han',
        'font_stack': '"Noto Sans CJK JP", "Hiragino Mincho ProN", "Yu Mincho", '
                      '"MS Mincho", "Source Han Sans JP", serif',
        'sample_text': 'いろはにほへと ちりぬるを。',
    },
    {
        'slug': 'ko', 'name': 'Korean', 'native_name': '한국어',
        'bcp47': 'ko', 'direction': 'ltr', 'script_name': 'Hangul',
        'font_stack': '"Noto Sans CJK KR", "Apple SD Gothic Neo", "Malgun Gothic", '
                      '"Source Han Sans KR", sans-serif',
        'sample_text': '키스의 고유 조건은 입술끼리 만나야 한다.',
    },

    # ─── Semitic / RTL ────────────────────────────────────────────
    {
        'slug': 'he', 'name': 'Hebrew', 'native_name': 'עברית',
        'bcp47': 'he', 'direction': 'rtl', 'script_name': 'Hebrew',
        'font_stack': '"Frank Ruehl CLM", "David CLM", "Ezra SIL", '
                      '"Noto Sans Hebrew", "Noto Serif Hebrew", serif',
        'sample_text': 'דג סקרן שט בים מאוכזב ולפתע מצא חברה.',
    },
    {
        'slug': 'arc', 'name': 'Aramaic (Imperial)', 'native_name': 'ארמית',
        'bcp47': 'arc', 'direction': 'rtl', 'script_name': 'Hebrew',
        'font_stack': '"Ezra SIL", "Noto Sans Hebrew", "Frank Ruehl CLM", serif',
        'sample_text': 'אבן יסודה דעת אלהא.',
    },
    {
        'slug': 'syr', 'name': 'Syriac', 'native_name': 'ܠܫܢܐ ܣܘܪܝܝܐ',
        'bcp47': 'syr', 'direction': 'rtl', 'script_name': 'Syriac',
        'font_stack': '"Estrangelo Edessa", "Serto Jerusalem", "East Syriac Adiabene", '
                      '"Noto Sans Syriac", serif',
        'sample_text': 'ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ.',
    },
    {
        'slug': 'ar', 'name': 'Arabic', 'native_name': 'العربية',
        'bcp47': 'ar', 'direction': 'rtl', 'script_name': 'Arabic',
        'font_stack': '"Amiri", "Scheherazade New", "Noto Naskh Arabic", '
                      '"Traditional Arabic", "Noto Sans Arabic", serif',
        'sample_text': 'صَلَّى اللَّهُ عَلَى مُحَمَّدٍ وَآلِهِ.',
    },
    {
        'slug': 'fa', 'name': 'Persian', 'native_name': 'فارسی',
        'bcp47': 'fa', 'direction': 'rtl', 'script_name': 'Arabic',
        'font_stack': '"Vazir", "IranNastaliq", "Noto Naskh Arabic", '
                      '"Tahoma", "Noto Sans Arabic", serif',
        'sample_text': 'گر تو نمی‌پسندی، تغییر ده قضا را.',
    },

    # ─── Other classical / specialised ────────────────────────────
    {
        'slug': 'cop', 'name': 'Coptic', 'native_name': 'ⲘⲈⲦⲢⲈⲘⲚⲬⲎⲘⲒ',
        'bcp47': 'cop', 'direction': 'ltr', 'script_name': 'Coptic',
        'font_stack': '"Antinoou", "New Athena Unicode", "Noto Sans Coptic", serif',
        'sample_text': 'ϩⲉⲛ ⲧⲉϩⲟⲩⲉⲓⲧⲉ ⲛⲉϥϣⲟⲟⲡ ⲛϭⲓ ⲡϣⲁϫⲉ.',
    },
    {
        'slug': 'sux', 'name': 'Sumerian (translit.)',
        'native_name': 'eme.gi₇',
        'bcp47': 'sux', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charis SIL", "Doulos SIL", "Gentium Plus", '
                      '"Noto Serif", serif',
        'sample_text': 'lugal-e ki-bal-e gul-gul.',
    },
    {
        'slug': 'akk', 'name': 'Akkadian (translit.)',
        'native_name': 'lišānum akkadītum',
        'bcp47': 'akk', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charis SIL", "Doulos SIL", "Gentium Plus", '
                      '"Noto Serif", serif',
        'sample_text': 'awīlum ša ana mūtim ittadû.',
    },
    {
        'slug': 'ipa', 'name': 'IPA', 'native_name': 'IPA',
        'bcp47': 'und-fonipa', 'direction': 'ltr', 'script_name': 'Latin',
        'font_stack': '"Charis SIL", "Doulos SIL", "Gentium Plus", '
                      '"DejaVu Sans", serif',
        'sample_text': '/ðə kwɪk braʊn fɒks/',
    },
]


class Command(BaseCommand):
    help = 'Seed Quill\'s Language registry. Idempotent.'

    def handle(self, *args, **opts):
        created = updated = 0
        for spec in SEEDS:
            obj, was_created = Language.objects.update_or_create(
                slug=spec['slug'],
                defaults={k: v for k, v in spec.items() if k != 'slug'},
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(self.style.SUCCESS(
            f'Quill languages: created {created}, updated {updated}. '
            f'Total now {Language.objects.count()}.'
        ))
