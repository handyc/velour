"""Seed Agora Phase 1 data — a few departments, one current term, a
handful of courses with illustrative sections.

Idempotent: uses update_or_create on slug for every row.

Run:    venv/bin/python manage.py seed_agora
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from agora.models import Course, Department, Program, Section, Term


DEPARTMENTS = [
    ('ling', 'LING', 'Linguistics',
     'Theoretical and empirical linguistics — syntax, phonology, '
     'semantics, language acquisition, typology.'),
    ('cs',   'CS',   'Computer Science',
     'Algorithms, systems, programming languages, and HCI.'),
    ('phil', 'PHIL', 'Philosophy',
     'Ancient through contemporary, logic, philosophy of mind, ethics.'),
    ('hist', 'HIST', 'History',
     'Regional and thematic history from antiquity to the present.'),
]

PROGRAMS = [
    ('ling-ba',  'ling', 'ba',  'Linguistics (BA)'),
    ('ling-ma',  'ling', 'ma',  'Linguistics (MA)'),
    ('cs-ba',    'cs',   'ba',  'Computer Science (BSc)'),
    ('phil-ba',  'phil', 'ba',  'Philosophy (BA)'),
    ('hist-ba',  'hist', 'ba',  'History (BA)'),
]

COURSES = [
    ('ling100', 'ling', 'LING100', 'Introduction to Linguistics', 5,
     'A survey of phonetics, phonology, morphology, syntax, semantics '
     'and pragmatics. No prerequisites.'),
    ('ling210', 'ling', 'LING210', 'Syntactic Theory', 5,
     'Constituency, trees, movement, and a gentle on-ramp to modern '
     'generative syntax. Uses Muka for tree exercises.'),
    ('ling310', 'ling', 'LING310', 'Historical Linguistics', 5,
     'Sound change, comparative reconstruction, and the classification '
     'of the world\'s language families.'),
    ('cs101',   'cs',   'CS101',   'Programming Fundamentals', 5,
     'Variables, control flow, functions, recursion, data structures. '
     'Students write small C programs — the Oneliner app provides '
     'reference classics.'),
    ('cs201',   'cs',   'CS201',   'Algorithms', 5,
     'Sorting, searching, graphs, dynamic programming. Complexity '
     'analysis from O(1) to O(n!).'),
    ('phil110', 'phil', 'PHIL110', 'Classical Logic', 5,
     'Propositional and first-order logic, natural deduction, soundness '
     'and completeness.'),
    ('phil220', 'phil', 'PHIL220', 'Philosophy of Mind', 5,
     'Dualism, functionalism, the hard problem, extended cognition.'),
    ('hist130', 'hist', 'HIST130', 'The Ancient World', 5,
     'From the Bronze Age through late antiquity; Mediterranean, Near '
     'East, and beyond.'),
]


def _term_for_today():
    """Pick a plausible current term covering today's date."""
    today = date.today()
    # Simple rule: if month >= 8 → Fall, else → Spring.
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
    help = 'Seed Agora with a small university catalog for demo purposes.'

    @transaction.atomic
    def handle(self, *args, **opts):
        # Departments
        depts = {}
        for slug, code, name, desc in DEPARTMENTS:
            obj, _ = Department.objects.update_or_create(
                slug=slug,
                defaults={'code': code, 'name': name, 'description': desc},
            )
            depts[slug] = obj
        self.stdout.write(f'+ {len(depts)} departments')

        # Programs
        for slug, dept_slug, level, name in PROGRAMS:
            Program.objects.update_or_create(
                slug=slug,
                defaults={'department': depts[dept_slug],
                          'level': level, 'name': name},
            )
        self.stdout.write(f'+ {len(PROGRAMS)} programs')

        # Current term
        tslug, tname, tstart, tend = _term_for_today()
        term, _ = Term.objects.update_or_create(
            slug=tslug,
            defaults={'name': tname, 'start_date': tstart, 'end_date': tend},
        )
        self.stdout.write(f'+ term: {term.name}')

        # Courses
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

        # Sections — one per course, taught by the first superuser we
        # can find. If none exists, skip (seed is safe on a virgin DB).
        User = get_user_model()
        instructor = User.objects.filter(is_superuser=True).first()
        if instructor:
            for slug, course in courses.items():
                Section.objects.update_or_create(
                    course=course, term=term, section_number='01',
                    defaults={'instructor': instructor,
                              'meeting_pattern':
                                'Mon/Wed 10:00–12:00' if slug.endswith('0') else
                                'Tue/Thu 14:00–16:00',
                              'room': f'Zaal {1 + hash(slug) % 12}',
                              'capacity': 30},
                )
            self.stdout.write(f'+ {len(courses)} sections (taught by '
                              f'{instructor.username})')
        else:
            self.stdout.write(self.style.WARNING(
                '  no superuser on record — sections skipped. '
                'Create one and re-run.'))

        self.stdout.write(self.style.SUCCESS('Agora seed complete.'))
