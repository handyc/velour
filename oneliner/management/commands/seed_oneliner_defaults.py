"""Seed the Oneliner app with a handful of classic sub-80-col C
programs. Idempotent: re-running updates the row in place if the
slug already exists.
"""

from django.core.management.base import BaseCommand

from oneliner.models import Oneliner


SEEDS = [
    {
        'slug': 'hello-world',
        'name': 'hello, world',
        'purpose': 'The K&R classic. Implicit int return, no #include.',
        'code': 'main(){puts("hello, world");}',
    },
    {
        'slug': 'exit-42',
        'name': 'exit 42',
        'purpose': 'Shortest legal program after main(){}. '
                   'Useful when you need a status-only binary.',
        'code': 'main(){return 42;}',
    },
    {
        'slug': 'yes',
        'name': 'yes',
        'purpose': 'Unix `yes` in 25 chars. Fill a pipe with "y" '
                   'until someone closes the reader.',
        'code': 'main(){for(;;)puts("y");}',
    },
    {
        'slug': 'cat',
        'name': 'cat',
        'purpose': 'Byte-exact cat via getchar/putchar. '
                   '~(c=getchar()) trick: ~(-1)==0 is the EOF test.',
        'code': 'main(c){while(~(c=getchar()))putchar(c);}',
        'stdin_fixture': 'hello from stdin\n',
    },
    {
        'slug': 'hex-stdin',
        'name': 'hex stdin',
        'purpose': 'Dump stdin as space-separated hex bytes.',
        'code': 'main(c){while(~(c=getchar()))printf("%02x ",c);}',
        'stdin_fixture': 'ABC',
    },
    {
        'slug': 'count-to-10',
        'name': 'count to 10',
        'purpose': 'Reuse argc as the loop counter — saves a decl.',
        'code': 'main(c){for(c=1;c<11;c++)printf("%d\\n",c);}',
    },
    {
        'slug': 'squares',
        'name': 'squares',
        'purpose': 'Print the first ten square numbers on one line.',
        'code': 'main(c){for(;c<10;c++)printf("%d ",c*c);puts("");}',
    },
    {
        'slug': 'ascii-printable',
        'name': 'ascii printable',
        'purpose': 'Dump ASCII 32..126 in one line, terminating newline.',
        'code': 'main(c){for(c=32;c<127;c++)putchar(c);puts("");}',
    },
    {
        'slug': 'fibonacci-10',
        'name': 'fibonacci (first 10)',
        'purpose': 'Comma-operator rotate: b=a+b, a=b-a. No third temp. '
                   'i initialized alongside a,b — skip this and argc '
                   'leaks into the loop bound.',
        'code': 'main(i,a,b){for(a=b=i=1;i++<11;b=a+b,a=b-a)printf("%d ",a);}',
    },
    {
        'slug': 'environ-dump',
        'name': 'environ dump',
        'purpose': 'Third argument to main is envp (POSIX). One line, '
                   'no #include, walks env strings to the null terminator.',
        'code': 'main(c,v,e)char**e;{while(*e)puts(*e++);}',
    },
]


class Command(BaseCommand):
    help = 'Seed the Oneliner app with classic sub-80-col C programs.'

    def add_arguments(self, parser):
        parser.add_argument('--compile', action='store_true',
            help='After seeding, compile each oneliner so the index '
                 'page shows binary sizes immediately.')

    def handle(self, *args, **opts):
        created = updated = 0
        for seed in SEEDS:
            obj, was_created = Oneliner.objects.update_or_create(
                slug=seed['slug'],
                defaults={
                    'name':          seed['name'],
                    'purpose':       seed.get('purpose', ''),
                    'code':          seed['code'],
                    'compile_flags': seed.get('compile_flags', '-w'),
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
            f'Seeded {len(SEEDS)} oneliners '
            f'({created} new, {updated} updated).'))

        if opts['compile']:
            self.stdout.write('')
            self.stdout.write('Compiling …')
            for obj in Oneliner.objects.all():
                r = obj.compile()
                self.stdout.write(
                    f'  {obj.slug}: {r["status"]} '
                    + (f'({r["binary_size"]} B)'
                       if r['binary_size'] else '(no binary)'))
