"""Seed Agora with Velour University — the user's bespoke university
shaped around their six stated subject interests: Computer Science,
Linguistics, Religious Studies, History, Philosophy, and Mathematics.

Idempotent on slug — re-run freely. Only touches Velour University
data; other modelled universities (Leiden, etc.) are preserved.

Run:    venv/bin/python manage.py seed_agora_velour
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from agora.models import (
    Course, Department, Enrollment, Program, ResourceLink,
    Section, Term, University,
)


# Six departments, one per user interest. Codes chosen to not collide
# with Leiden (VC.LING vs LUCL etc. — Velour namespaces them).
DEPARTMENTS = [
    ('vc-cs', 'VC-CS', 'School of Computer Science',
     'Systems, languages, algorithms, and the thoughtful design of '
     'the machines we live with. Strongly integrated with the Velour '
     'Oneliner, Reckoner, and Automaton apps.'),
    ('vc-ling', 'VC-LING', 'School of Linguistics',
     'General, historical, and computational linguistics, with an '
     'endangered-language documentation thread that cross-lists with '
     'the Muka app.'),
    ('vc-relig', 'VC-RELIG', 'School of Religious Studies',
     'Cross-traditional study of religion — texts, practices, '
     'institutions, and the philosophical questions they raise.'),
    ('vc-hist', 'VC-HIST', 'School of History',
     'World history with a heavy bench in intellectual and scientific '
     'history; the Studious scholar library is our auxiliary stacks.'),
    ('vc-phil', 'VC-PHIL', 'School of Philosophy',
     'Analytic and continental, classical and contemporary — with a '
     'core sequence on philosophy of mind and philosophy of language.'),
    ('vc-math', 'VC-MATH', 'School of Mathematics',
     'Pure and applied, from foundations through category theory and '
     'mathematical logic; the Det and Casting apps supply our '
     'computational lab.'),
]


PROGRAMS = [
    ('vc-cs-ba',      'vc-cs',    'ba',  'Computer Science (BA)'),
    ('vc-cs-ma',      'vc-cs',    'ma',  'Computer Science (MA)'),
    ('vc-cs-phd',     'vc-cs',    'phd', 'Computer Science (PhD)'),
    ('vc-ling-ba',    'vc-ling',  'ba',  'Linguistics (BA)'),
    ('vc-ling-ma',    'vc-ling',  'ma',  'Linguistics (MA)'),
    ('vc-ling-phd',   'vc-ling',  'phd', 'Linguistics (PhD)'),
    ('vc-relig-ba',   'vc-relig', 'ba',  'Religious Studies (BA)'),
    ('vc-relig-ma',   'vc-relig', 'ma',  'Religious Studies (MA)'),
    ('vc-hist-ba',    'vc-hist',  'ba',  'History (BA)'),
    ('vc-hist-ma',    'vc-hist',  'ma',  'History (MA)'),
    ('vc-phil-ba',    'vc-phil',  'ba',  'Philosophy (BA)'),
    ('vc-phil-ma',    'vc-phil',  'ma',  'Philosophy (MA)'),
    ('vc-phil-phd',   'vc-phil',  'phd', 'Philosophy (PhD)'),
    ('vc-math-ba',    'vc-math',  'ba',  'Mathematics (BA)'),
    ('vc-math-ma',    'vc-math',  'ma',  'Mathematics (MA)'),
    ('vc-math-phd',   'vc-math',  'phd', 'Mathematics (PhD)'),
]


# Each course's code is unique within its department, so Velour can
# use short codes like CS100 without colliding with Leiden's LIACS100.
COURSES = [
    # CS
    ('vc-cs100',  'vc-cs', 'CS100', 'Thinking About Computation', 5,
     'A gentle introduction to what a computer is — from Turing machines '
     'through Lisp, lambdas, and what it means for a problem to be hard.'),
    ('vc-cs110',  'vc-cs', 'CS110', 'Systems Programming in C', 5,
     'Pointers, memory, processes, the kernel interface. Uses the '
     'Oneliner app as its reference library of classic programs.'),
    ('vc-cs210',  'vc-cs', 'CS210', 'Algorithms', 5,
     'Sorting, searching, graphs, dynamic programming; complexity '
     'intuitions through the Reckoner app.'),
    ('vc-cs220',  'vc-cs', 'CS220', 'Cellular Automata and Emergence', 5,
     'Rule 110, Conway, Langton, and the class-4 frontier. Uses Det '
     'and Automaton for its labs.'),
    ('vc-cs310',  'vc-cs', 'CS310', 'Type Theory', 5,
     'From simply typed lambda calculus to dependent types, with '
     'Camlfornia as the in-browser lab.'),
    ('vc-cs320',  'vc-cs', 'CS320', 'Machine Learning, Honestly', 5,
     'The usual models plus the unusual skill — honest evaluation, '
     'leakage, the replication crisis, and how to say "I don\'t know".'),

    # Linguistics
    ('vc-ling100','vc-ling', 'LING100', 'Introduction to Linguistics', 5,
     'Sound, structure, meaning, variation. Tree exercises via Muka.'),
    ('vc-ling210','vc-ling', 'LING210', 'Historical Linguistics', 5,
     'Comparative reconstruction, sound change, and the deep time of '
     'languages.'),
    ('vc-ling220','vc-ling', 'LING220', 'Endangered Language Documentation', 5,
     'Fieldwork methods, archiving, and the ethics of documentation.'),
    ('vc-ling310','vc-ling', 'LING310', 'Semantics', 5,
     'Compositionality, dynamic semantics, and what "meaning" means.'),
    ('vc-ling320','vc-ling', 'LING320', 'Linguistic Typology', 5,
     'Cross-linguistic variation as a constraint on universal grammar.'),

    # Religious Studies
    ('vc-rel100','vc-relig', 'REL100', 'Comparative Religion', 5,
     'The major traditions in conversation — text, practice, institution.'),
    ('vc-rel210','vc-relig', 'REL210', 'Hebrew Bible', 5,
     'Literary, historical, and archaeological approaches.'),
    ('vc-rel220','vc-relig', 'REL220', 'Buddhist Thought', 5,
     'From early Buddhism through Madhyamaka and Yogācāra.'),
    ('vc-rel230','vc-relig', 'REL230', 'Gnostic and Hermetic Traditions', 5,
     'Sethian, Valentinian, Hermetic currents in late antiquity and '
     'their medieval afterlives.'),
    ('vc-rel310','vc-relig', 'REL310', 'Ritual Theory', 5,
     'Durkheim, Turner, Bell — what rituals do and how we study them.'),

    # History
    ('vc-hist100','vc-hist', 'HIST100', 'World History Survey', 5,
     'From deep prehistory through the present, with a Velour-made '
     'emphasis on moments when knowledge systems transformed.'),
    ('vc-hist210','vc-hist', 'HIST210', 'The Scientific Revolution', 5,
     'Copernicus to Newton — and why it\'s controversial to say it was '
     'a revolution at all.'),
    ('vc-hist220','vc-hist', 'HIST220', 'Colonial and Global Histories', 5,
     'Empire, resistance, and the circulation of knowledge.'),
    ('vc-hist310','vc-hist', 'HIST310', 'History of the Book', 5,
     'Manuscript, print, digital — and the scholars who made each.'),
    ('vc-hist320','vc-hist', 'HIST320', 'Intellectual History', 5,
     'Ideas in their social worlds, from the presocratics to the present.'),

    # Philosophy
    ('vc-phil100','vc-phil', 'PHIL100', 'Introduction to Philosophy', 5,
     'Knowledge, ethics, mind, being — the perennial questions.'),
    ('vc-phil110','vc-phil', 'PHIL110', 'Logic', 5,
     'Propositional and first-order logic, natural deduction, soundness '
     'and completeness.'),
    ('vc-phil210','vc-phil', 'PHIL210', 'Philosophy of Mind', 5,
     'Dualism, functionalism, the hard problem, extended cognition.'),
    ('vc-phil220','vc-phil', 'PHIL220', 'Philosophy of Language', 5,
     'Frege, Russell, Kripke, and the problem of reference.'),
    ('vc-phil310','vc-phil', 'PHIL310', 'Metaphysics', 5,
     'Being, time, modality, identity — the subjects that won\'t stay '
     'dead.'),
    ('vc-phil320','vc-phil', 'PHIL320', 'Ethics', 5,
     'Virtue, duty, consequence — and the cases where they conflict.'),

    # Mathematics
    ('vc-math100','vc-math', 'MATH100', 'Calculus', 6,
     'Limits, derivatives, integrals, series.'),
    ('vc-math110','vc-math', 'MATH110', 'Linear Algebra', 6,
     'Vector spaces, linear maps, eigenstructure.'),
    ('vc-math210','vc-math', 'MATH210', 'Real Analysis', 6,
     'Metric spaces, continuity, compactness, Lebesgue integration.'),
    ('vc-math220','vc-math', 'MATH220', 'Abstract Algebra', 6,
     'Groups, rings, fields, Galois theory.'),
    ('vc-math310','vc-math', 'MATH310', 'Mathematical Logic', 6,
     'First-order logic, incompleteness, model theory.'),
    ('vc-math320','vc-math', 'MATH320', 'Category Theory', 6,
     'Categories, functors, natural transformations, adjunctions — '
     'and a look at topos theory.'),
]


def _term_for_today():
    today = date.today()
    if today.month >= 8:
        return (f'fall-{today.year}',
                f'Fall {today.year}',
                date(today.year, 9, 1),
                date(today.year, 12, 22))
    return (f'spring-{today.year}',
            f'Spring {today.year}',
            date(today.year, 2, 1),
            date(today.year, 6, 30))


class Command(BaseCommand):
    help = 'Seed Agora with Velour University (user interests edition).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-existing', action='store_true',
            help="Don't clear Velour University's existing data first.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if not opts['keep_existing']:
            u_existing = University.objects.filter(slug='velour').first()
            if u_existing:
                u_existing.departments.all().delete()
                self.stdout.write('  cleared Velour University data')

        u_velour, _ = University.objects.update_or_create(
            slug='velour',
            defaults={
                'code': 'VU',
                'name': 'Velour University',
                'tagline': 'Intensity with nap time — rigorous inquiry in soft fabric.',
                'description': 'A university imagined by Velour, shaped '
                    'around its maker\'s abiding interests: computers, '
                    'languages, religion, history, philosophy, and '
                    'mathematics. Its catalog cross-lists with other '
                    'Velour apps wherever natural.',
                'founded': 2026,
                'city': 'Everywhere and nowhere',
                'country': 'Velour',
            },
        )
        self.stdout.write(f'+ university: {u_velour.name}')

        depts = {}
        for slug, code, name, desc in DEPARTMENTS:
            obj, _ = Department.objects.update_or_create(
                university=u_velour, slug=slug,
                defaults={'code': code, 'name': name, 'description': desc},
            )
            depts[slug] = obj
        self.stdout.write(f'+ {len(depts)} departments')

        for slug, dept_slug, level, name in PROGRAMS:
            Program.objects.update_or_create(
                slug=slug,
                defaults={'department': depts[dept_slug],
                          'level': level, 'name': name},
            )
        self.stdout.write(f'+ {len(PROGRAMS)} programs')

        tslug, tname, tstart, tend = _term_for_today()
        term, _ = Term.objects.update_or_create(
            slug=tslug,
            defaults={'name': tname, 'start_date': tstart, 'end_date': tend},
        )
        self.stdout.write(f'+ term: {term.name}')

        courses = {}
        for slug, dept_slug, code, title, credits, desc in COURSES:
            obj, _ = Course.objects.update_or_create(
                slug=slug,
                defaults={'department': depts[dept_slug], 'code': code,
                          'title': title, 'credits': credits,
                          'description': desc},
            )
            courses[slug] = obj
        self.stdout.write(f'+ {len(courses)} courses')

        User = get_user_model()
        instructor = User.objects.filter(is_superuser=True).first()
        if instructor:
            for i, (slug, course) in enumerate(courses.items()):
                Section.objects.update_or_create(
                    course=course, term=term, section_number='01',
                    defaults={'instructor': instructor,
                              'meeting_pattern': (
                                  'Mon/Wed 10:00–12:00' if i % 3 == 0 else
                                  'Tue/Thu 14:00–16:00' if i % 3 == 1 else
                                  'Fri 13:00–17:00'),
                              'room': f'Velour Hall {100 + i}',
                              'capacity': 25},
                )
            self.stdout.write(f'+ {len(courses)} sections taught by '
                              f'{instructor.username}')
        else:
            self.stdout.write(self.style.WARNING(
                '  no superuser on record — sections skipped.'))

        self.stdout.write(self.style.SUCCESS(
            f'Velour University seeded. {len(depts)} departments, '
            f'{len(PROGRAMS)} programs, {len(courses)} courses.'
        ))
