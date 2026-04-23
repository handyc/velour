"""Seed Agora with the Faculty of Humanities (FGW) at Leiden University.

Populates seven institutes (LUCL, LUCAS, LIAS, History, Philosophy,
LUCSoR, ACPA) along with representative programs and a small catalog
of courses per institute. Idempotent on slug — re-run freely.

Run:    venv/bin/python manage.py seed_agora_leiden

Note on the acronym: at Leiden, FSW = Faculteit der Sociale
Wetenschappen (Social Sciences), while the Faculty of Humanities is
FGW (Faculteit der Geesteswetenschappen). This seed covers FGW; swap
in FSW departments (Psychology, Political Science, Cultural
Anthropology, Education & Child Studies, CADS) if that's what you
meant.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from agora.models import (
    Course, Department, Enrollment, Program, ResourceLink,
    Section, Term, University,
)


# (slug, code, name, description)
DEPARTMENTS = [
    ('lucl', 'LUCL', 'Leiden University Centre for Linguistics',
     'Theoretical and descriptive linguistics: phonology, syntax, '
     'semantics, language acquisition, sign languages, and the '
     'documentation of endangered languages.'),
    ('lucas', 'LUCAS', 'Leiden University Centre for the Arts in Society',
     'Literary studies, art history, film and photographic studies, '
     'comparative literature, and the arts broadly conceived in their '
     'historical and social contexts.'),
    ('lias', 'LIAS', 'Leiden Institute for Area Studies',
     'Regional studies — Asian, Middle Eastern, African, Latin '
     'American, Russian and Eurasian, and related interdisciplinary '
     'area programmes.'),
    ('hist', 'HIST', 'Institute for History',
     'European, global, colonial and economic history from antiquity '
     'through the present, with particular strength in early modern '
     'and colonial histories.'),
    ('phil', 'PHIL', 'Institute for Philosophy',
     'Theoretical philosophy (logic, epistemology, philosophy of mind), '
     'practical philosophy (ethics, political philosophy), and the '
     'history of philosophy, East and West.'),
    ('lucsor', 'LUCSOR', 'Leiden University Centre for the Study of Religion',
     'Religious studies across traditions — Christianity, Islam, '
     'Hinduism, Buddhism, Judaism, secularism — with a strongly '
     'comparative and historical orientation.'),
    ('acpa', 'ACPA', 'Academy of Creative and Performing Arts',
     'Doctoral-level programme tying artistic practice (music, fine '
     'arts, performance) to academic research, in collaboration with '
     'the Royal Academy of Art and Royal Conservatoire in The Hague.'),
    # Strictly speaking these two are Faculty of Science (FWN), not FGW,
    # but requested alongside the humanities institutes.
    ('math', 'MATH', 'Mathematical Institute',
     'Pure and applied mathematics: algebra, analysis, geometry, '
     'number theory, probability, statistics, and mathematical physics. '
     'Houses the Statistical Science programme jointly with LIACS.'),
    ('liacs', 'LIACS', 'Leiden Institute of Advanced Computer Science',
     'Algorithms, data science, artificial intelligence, software '
     'engineering, computer systems, and the interface between '
     'computer science and other disciplines (ICT in Business, Media '
     'Technology, Bioinformatics).'),
]


# (slug, dept_slug, level, name)
PROGRAMS = [
    # LUCL
    ('lucl-ba-ling',    'lucl', 'ba',  'Linguistics (BA)'),
    ('lucl-ma-ling',    'lucl', 'ma',  'Linguistics (MA)'),
    ('lucl-ma-lrt',     'lucl', 'ma',  'Linguistics: Language and Cognition (MA)'),
    ('lucl-ma-ls',      'lucl', 'ma',  'Language and Society (MA)'),
    ('lucl-phd',        'lucl', 'phd', 'Linguistics (PhD)'),
    # LUCAS
    ('lucas-ba-lit',    'lucas', 'ba',  'Literary Studies (BA)'),
    ('lucas-ma-lit',    'lucas', 'ma',  'Literary Studies (MA)'),
    ('lucas-ba-arts',   'lucas', 'ba',  'Arts, Media and Society (BA)'),
    ('lucas-ma-arthist','lucas', 'ma',  'Art History (MA)'),
    ('lucas-ma-film',   'lucas', 'ma',  'Film and Photographic Studies (MA)'),
    # LIAS
    ('lias-ba-asian',   'lias', 'ba',  'Asian Studies (BA)'),
    ('lias-ma-asian',   'lias', 'ma',  'Asian Studies (MA)'),
    ('lias-ba-mes',     'lias', 'ba',  'Middle Eastern Studies (BA)'),
    ('lias-ma-mes',     'lias', 'ma',  'Middle Eastern Studies (MA)'),
    ('lias-ma-afas',    'lias', 'ma',  'African Studies (MA)'),
    ('lias-ma-lacs',    'lias', 'ma',  'Latin American Studies (MA)'),
    ('lias-ma-rus',     'lias', 'ma',  'Russian and Eurasian Studies (MA)'),
    # History
    ('hist-ba',         'hist', 'ba',  'History (BA)'),
    ('hist-ma-gen',     'hist', 'ma',  'History (MA)'),
    ('hist-ma-cgh',     'hist', 'ma',  'Colonial and Global History (MA)'),
    ('hist-ma-erh',     'hist', 'ma',  'European Expansion and Globalisation (MA)'),
    # Philosophy
    ('phil-ba',         'phil', 'ba',  'Philosophy (BA)'),
    ('phil-ba-gcp',     'phil', 'ba',  'Philosophy: Global and Comparative (BA)'),
    ('phil-ma-gen',     'phil', 'ma',  'Philosophy (MA)'),
    ('phil-ma-polphil', 'phil', 'ma',  'Philosophy, Politics and Economics (MA)'),
    # LUCSoR
    ('lucsor-ma',       'lucsor', 'ma',  'Religious Studies (MA)'),
    ('lucsor-ma-ic',    'lucsor', 'ma',  'Islamic Studies (MA)'),
    # ACPA
    ('acpa-phd',        'acpa', 'phd', 'Creative and Performing Arts (PhD)'),
    # Mathematical Institute
    ('math-ba',         'math', 'ba',  'Mathematics (BSc)'),
    ('math-ma',         'math', 'ma',  'Mathematics (MSc)'),
    ('math-ma-stat',    'math', 'ma',  'Statistical Science for the Life and '
                                       'Behavioural Sciences (MSc)'),
    ('math-ma-applied', 'math', 'ma',  'Applied Mathematics (MSc)'),
    ('math-phd',        'math', 'phd', 'Mathematics (PhD)'),
    # LIACS
    ('liacs-ba-cs',     'liacs', 'ba',  'Computer Science (BSc)'),
    ('liacs-ba-dsai',   'liacs', 'ba',  'Data Science and Artificial '
                                        'Intelligence (BSc)'),
    ('liacs-ba-csecon', 'liacs', 'ba',  'Computer Science and Economics (BSc)'),
    ('liacs-ma-cs',     'liacs', 'ma',  'Computer Science (MSc)'),
    ('liacs-ma-ict',    'liacs', 'ma',  'ICT in Business and the Public '
                                        'Sector (MSc)'),
    ('liacs-ma-media',  'liacs', 'ma',  'Media Technology (MSc)'),
    ('liacs-phd',       'liacs', 'phd', 'Computer Science (PhD)'),
]


# (slug, dept_slug, code, title, credits, description)
COURSES = [
    # LUCL (course codes use 3-letter subject prefix inside LING family)
    ('lucl-intro',    'lucl', 'LUCL100', 'Introduction to General Linguistics', 5,
     'Core concepts across phonology, morphology, syntax, and semantics.'),
    ('lucl-phon',     'lucl', 'LUCL210', 'Phonology', 5,
     'Features, rules, and representations in phonological theory.'),
    ('lucl-syntax',   'lucl', 'LUCL220', 'Syntactic Theory', 5,
     'Constituency, movement, and generative syntax. Uses Muka for '
     'tree exercises.'),
    ('lucl-sem',      'lucl', 'LUCL230', 'Formal Semantics', 5,
     'Compositionality, lambda calculus, Montague grammar.'),
    ('lucl-typ',      'lucl', 'LUCL310', 'Linguistic Typology', 5,
     'Cross-linguistic variation and the universals that structure it.'),
    ('lucl-endang',   'lucl', 'LUCL340', 'Endangered Languages and Documentation', 5,
     'Fieldwork methods, archiving, and the ethics of documentation.'),

    # LUCAS
    ('lucas-intro-lit','lucas', 'LUCAS100', 'Introduction to Literary Studies', 5,
     'Close reading, genre, theory — a survey from antiquity to now.'),
    ('lucas-modlit',  'lucas', 'LUCAS220', 'Modernism and its Afterlives', 5,
     'Eliot, Joyce, Woolf, Borges, and their postwar inheritors.'),
    ('lucas-arthist', 'lucas', 'LUCAS210', 'Art History: Renaissance to Baroque', 5,
     'Italian and Northern traditions from Giotto to Rembrandt.'),
    ('lucas-film',    'lucas', 'LUCAS250', 'The Language of Film', 5,
     'Shot, montage, sound design; close analysis of key sequences.'),

    # LIAS
    ('lias-asia-intro','lias', 'LIAS100', 'Introduction to Asian Studies', 5,
     'Historical, political, and cultural overview of East, South and '
     'Southeast Asia.'),
    ('lias-china-hist','lias', 'LIAS210', 'Modern Chinese History', 5,
     'From the late Qing through the reform era.'),
    ('lias-mes-intro','lias', 'LIAS120', 'Introduction to Middle Eastern Studies', 5,
     'The region from the rise of Islam through the contemporary.'),
    ('lias-afric',    'lias', 'LIAS230', 'African Studies: Politics and Society', 5,
     'Post-colonial state formation, conflict, and development.'),
    ('lias-latam',    'lias', 'LIAS240', 'Latin America in the 20th Century', 5,
     'Revolutions, dictatorships, and the return of democracy.'),

    # History
    ('hist-ancient',  'hist', 'HIST120', 'The Ancient World', 5,
     'Mesopotamia, Egypt, Greece, and Rome through the fall of the '
     'Western Empire.'),
    ('hist-medieval', 'hist', 'HIST130', 'Medieval Europe', 5,
     'Late antiquity to the Black Death.'),
    ('hist-early-mod','hist', 'HIST210', 'Early Modern Europe', 5,
     'Reformation, scientific revolution, the rise of the nation state.'),
    ('hist-colonial', 'hist', 'HIST310', 'Colonial and Global History', 5,
     'The Dutch, British, and other empires in global context.'),
    ('hist-econ',     'hist', 'HIST340', 'Economic History', 5,
     'Long-run growth, trade, institutions, from 1500 to today.'),

    # Philosophy
    ('phil-intro',    'phil', 'PHIL100', 'Introduction to Philosophy', 5,
     'Core questions — knowledge, ethics, mind, being — across the tradition.'),
    ('phil-logic',    'phil', 'PHIL110', 'Classical Logic', 5,
     'Propositional and first-order logic, natural deduction.'),
    ('phil-mind',     'phil', 'PHIL220', 'Philosophy of Mind', 5,
     'Dualism, functionalism, consciousness, extended cognition.'),
    ('phil-ethics',   'phil', 'PHIL230', 'Moral Philosophy', 5,
     'Virtue ethics, deontology, consequentialism, metaethics.'),
    ('phil-chinese',  'phil', 'PHIL240', 'Chinese Philosophy', 5,
     'Confucian, Daoist, and Buddhist traditions in conversation.'),
    ('phil-political','phil', 'PHIL310', 'Political Philosophy', 5,
     'Justice, rights, democracy — Rawls and his critics.'),

    # LUCSoR
    ('lucsor-intro',  'lucsor', 'LUCSOR100', 'Comparative Religion', 5,
     'Survey of the major traditions in cross-cultural comparison.'),
    ('lucsor-islam',  'lucsor', 'LUCSOR210', 'Islam in the Contemporary World', 5,
     'Theology, law, politics, and everyday practice.'),
    ('lucsor-bible',  'lucsor', 'LUCSOR220', 'Hebrew Bible / Old Testament', 5,
     'Literary, historical, and archaeological approaches.'),

    # ACPA
    ('acpa-research', 'acpa', 'ACPA700', 'Artistic Research Methods', 5,
     'Practice-based inquiry, documentation, and academic writing '
     'for artists. Doctoral level.'),

    # Mathematical Institute
    ('math-calc',     'math', 'MATH101', 'Calculus', 6,
     'Single-variable calculus: limits, derivatives, integrals, '
     'sequences and series.'),
    ('math-linalg',   'math', 'MATH102', 'Linear Algebra', 6,
     'Vector spaces, matrices, eigenvalues, inner products, and the '
     'diagonalisation of symmetric operators.'),
    ('math-analysis', 'math', 'MATH210', 'Real Analysis', 6,
     'Rigorous foundations: metric spaces, continuity, compactness, '
     'Riemann and Lebesgue integration.'),
    ('math-algebra',  'math', 'MATH220', 'Abstract Algebra', 6,
     'Groups, rings, fields, and the first look at Galois theory.'),
    ('math-prob',     'math', 'MATH230', 'Probability Theory', 6,
     'Kolmogorov axioms, random variables, convergence, limit theorems.'),
    ('math-numth',    'math', 'MATH310', 'Number Theory', 6,
     'Divisibility, congruences, quadratic reciprocity, and an '
     'introduction to algebraic number theory.'),
    ('math-stat',     'math', 'MATH320', 'Mathematical Statistics', 6,
     'Estimation, hypothesis testing, regression, the bootstrap, and '
     'Bayesian inference.'),

    # LIACS
    ('liacs-intro',   'liacs', 'LIACS100', 'Introduction to Programming', 6,
     'First programming course — Python syntax, data structures, '
     'modular design, and test-driven development.'),
    ('liacs-alg',     'liacs', 'LIACS210', 'Algorithms and Data Structures', 6,
     'Sorting, searching, graphs, dynamic programming, complexity '
     'analysis. The Reckoner app is used for scale intuitions.'),
    ('liacs-os',      'liacs', 'LIACS220', 'Operating Systems', 6,
     'Processes, threads, memory management, file systems, '
     'scheduling, and the classic concurrency primitives.'),
    ('liacs-net',     'liacs', 'LIACS230', 'Computer Networks', 6,
     'The Internet protocol stack, from physical layer to application. '
     'Hands-on with TCP, DNS, HTTP, and routing.'),
    ('liacs-db',      'liacs', 'LIACS240', 'Databases', 6,
     'Relational theory, SQL, transactions, indexing, and a taste of '
     'NoSQL systems and OLAP.'),
    ('liacs-ml',      'liacs', 'LIACS310', 'Machine Learning', 6,
     'Linear models, kernel methods, decision trees, neural networks, '
     'and the practice of honest evaluation.'),
    ('liacs-ai',      'liacs', 'LIACS320', 'Artificial Intelligence', 6,
     'Search, planning, knowledge representation, reasoning under '
     'uncertainty, and the long arc from symbolic AI to LLMs.'),
    ('liacs-seng',    'liacs', 'LIACS330', 'Software Engineering', 6,
     'Requirements, design, testing, version control, and the social '
     'practice of building software together.'),
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
    help = 'Seed Agora with the seven FGW institutes at Leiden University.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--keep-existing', action='store_true',
            help="Don't clear existing Agora data before seeding. Default "
                 "behaviour deletes all departments/programs/courses/"
                 "sections/enrollments first so we end up with a clean "
                 "FGW catalog and no leftover rows from an earlier seed.",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        if not opts['keep_existing']:
            # Remove only THIS university's data — preserves other
            # modelled universities (e.g. Velour University).
            u_existing = University.objects.filter(slug='leiden').first()
            if u_existing:
                # Department.CASCADE takes Program/Course/Section etc.
                u_existing.departments.all().delete()
                self.stdout.write('  cleared Leiden University data')

        u_leiden, _ = University.objects.update_or_create(
            slug='leiden',
            defaults={
                'code': 'LEI',
                'name': 'Leiden University',
                'tagline': 'Praesidium Libertatis — Bastion of Liberty.',
                'description': 'The oldest university in the Netherlands, '
                    'founded in 1575 by William the Silent. Humanities and '
                    'Science faculties modelled here.',
                'founded': 1575,
                'city': 'Leiden',
                'country': 'Netherlands',
                'website': 'https://www.universiteitleiden.nl/',
            },
        )
        self.stdout.write(f'+ university: {u_leiden.name}')

        depts = {}
        for slug, code, name, desc in DEPARTMENTS:
            obj, _ = Department.objects.update_or_create(
                university=u_leiden, slug=slug,
                defaults={'code': code, 'name': name, 'description': desc},
            )
            depts[slug] = obj
        self.stdout.write(f'+ {len(depts)} departments '
                          f'(FGW humanities institutes + MATH + LIACS)')

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
                              'room': f'Lipsius {101 + i}',
                              'capacity': 30 if '100' in course.code else 20},
                )
            self.stdout.write(f'+ {len(courses)} sections taught by '
                              f'{instructor.username}')
        else:
            self.stdout.write(self.style.WARNING(
                '  no superuser on record — sections skipped.'))

        self.stdout.write(self.style.SUCCESS(
            f'Agora: Leiden catalog seeded. {len(depts)} institutes '
            f'(7 FGW + MATH + LIACS), {len(PROGRAMS)} programs, '
            f'{len(courses)} courses.'
        ))
