"""Seed the Oneliner app with classic sub-80-col bash oneliners.

These are interpreted rather than compiled: each row is stored with
`language='bash'` and runs via `bash -c` on the detail page. The
same 80-char-per-line ceiling applies, which is where the bash-golf
fun lives — brace expansion, parameter substitution, one-letter
flags all bought specifically to make the payload fit.

Idempotent: re-running updates the row in place if the slug already
exists.
"""

from django.core.management.base import BaseCommand

from oneliner.models import Oneliner


SEEDS = [
    {
        'slug': 'bash-hello-world',
        'name': 'hello, world (bash)',
        'purpose': 'Shortest possible. No quotes needed — bash splits on '
                   'whitespace but echo rejoins with a single space.',
        'code': 'echo hello, world',
    },
    {
        'slug': 'bash-yes',
        'name': 'yes (bash)',
        'purpose': 'The `yes` command in pure bash. `:` is the no-op '
                   'builtin — cheaper than `true` and shorter.',
        'code': 'while :; do echo y; done',
    },
    {
        'slug': 'bash-seq-squares',
        'name': 'squares 1..10',
        'purpose': 'Brace expansion {1..10} generates the sequence at '
                   'parse time. $((…)) is arithmetic evaluation.',
        'code': 'for i in {1..10}; do echo $((i*i)); done',
    },
    {
        'slug': 'bash-fibonacci',
        'name': 'fibonacci (first 10)',
        'purpose': 'Three-variable rotate, no temp. (( )) returns 0 for '
                   'true / 1 for false — the inverse of exit codes, so '
                   'its status is usable but rarely what you want.',
        'code': 'a=0 b=1; for i in {1..10}; do echo $a; '
                'c=$((a+b)); a=$b; b=$c; done',
    },
    {
        'slug': 'bash-upper',
        'name': 'upper',
        'purpose': 'tr is the right tool for character-class translation. '
                   'a-z A-Z is shorter than [:lower:] [:upper:].',
        'code': 'tr a-z A-Z',
        'stdin_fixture': 'hello from bash\n',
    },
    {
        'slug': 'bash-rot13',
        'name': 'rot13',
        'purpose': 'tr handles the Caesar cipher in a single class swap. '
                   'Symmetric: piping rot13 twice is the identity.',
        'code': 'tr A-Za-z N-ZA-Mn-za-m',
        'stdin_fixture': 'Attack at dawn.\n',
    },
    {
        'slug': 'bash-word-count',
        'name': 'word count',
        'purpose': 'NF is awk\'s field count per record. Accumulate over '
                   'all records; print in END. Much terser than wc -w '
                   'when you already have an awk pipeline going.',
        'code': "awk '{n+=NF} END{print n}'",
        'stdin_fixture': 'the quick brown fox\njumps over the lazy dog\n',
    },
    {
        'slug': 'bash-column-sum',
        'name': 'column sum',
        'purpose': '$1 is the first whitespace-separated field. awk '
                   'auto-coerces to number. Any column picker becomes '
                   "`awk '{s+=$N}END{print s}'`.",
        'code': "awk '{s+=$1} END{print s}'",
        'stdin_fixture': '10\n20\n30\n42\n',
    },
    {
        'slug': 'bash-top-words',
        'name': 'top words (frequency)',
        'purpose': 'The classic frequency-count pipeline. tr-to-newline '
                   'splits words; sort makes them adjacent; uniq -c '
                   'counts; sort -rn ranks; head caps it.',
        'code': "tr -s ' \\n' '\\n' | sort | uniq -c | sort -rn | head",
        'stdin_fixture': ('the cat sat on the mat and the mat '
                          'was on the floor and the cat was on '
                          'the mat\n'),
    },
    {
        'slug': 'bash-palindrome',
        'name': 'palindrome check',
        'purpose': 'rev reverses stdin. Here-string <<< feeds a var. '
                   '[[ = ]] is bash\'s string equality; && / || make '
                   'the single-line if.',
        'code': 'read w; [[ $w = $(rev <<< "$w") ]] && echo yes || echo no',
        'stdin_fixture': 'racecar\n',
    },
    {
        'slug': 'bash-line-count',
        'name': 'line count (no wc)',
        'purpose': 'Every time awk reads a record, NR increments; print '
                   'at END gives the total. Handles missing trailing '
                   'newline the same way wc -l does.',
        'code': 'awk \'END{print NR}\'',
        'stdin_fixture': 'alpha\nbeta\ngamma\n',
    },
    {
        'slug': 'bash-primes-to-50',
        'name': 'primes up to 50',
        'purpose': '`factor N` prints `N: p q r …`. Primes factor as '
                   '`N: N` (NF==2). seq generates the candidates; awk '
                   'keeps only the primes.',
        'code': "factor $(seq 2 50) | awk 'NF==2{print $2}'",
    },
    {
        'slug': 'bash-pid-of-self',
        'name': 'pid of self',
        'purpose': '$$ is the PID of the current shell. bash -c starts '
                   'a new shell, so each run prints a different pid.',
        'code': 'echo $$',
    },
    {
        'slug': 'bash-env-count',
        'name': 'env var count',
        'purpose': 'env prints one VAR=value per line; wc -l counts '
                   'lines. The inherited environment of a login shell '
                   'is typically ~50 entries.',
        'code': 'env | wc -l',
    },
    {
        'slug': 'bash-uptime-seconds',
        'name': 'uptime in seconds',
        'purpose': '/proc/uptime first field is seconds since boot '
                   'as a float. cut -d\' \' -f1 keeps just that.',
        'code': "cut -d' ' -f1 /proc/uptime",
    },
]


class Command(BaseCommand):
    help = 'Seed the Oneliner app with classic sub-80-col bash programs.'

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true',
            help='After seeding, syntax-check each bash oneliner so '
                 'the index page shows an "ok" status immediately.')

    def handle(self, *args, **opts):
        created = updated = 0
        for seed in SEEDS:
            obj, was_created = Oneliner.objects.update_or_create(
                slug=seed['slug'],
                defaults={
                    'name':          seed['name'],
                    'language':      'bash',
                    'purpose':       seed.get('purpose', ''),
                    'code':          seed['code'],
                    'compile_flags': seed.get('compile_flags', ''),
                    'stdin_fixture': seed.get('stdin_fixture', ''),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(
                f'  {"+" if was_created else "~"} {obj.slug} '
                f'({obj.char_count} ch longest)')

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {len(SEEDS)} bash oneliners '
            f'({created} new, {updated} updated).'))

        if opts['check']:
            self.stdout.write('')
            self.stdout.write('Syntax-checking …')
            for obj in Oneliner.objects.filter(language='bash'):
                r = obj.compile()
                self.stdout.write(
                    f'  {obj.slug}: {r["status"]}'
                    + (f' ({r["output"]})' if r['output'] else ''))
