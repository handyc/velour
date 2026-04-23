"""Agora — university master framework.

A Velour meta-app that models a university at the level of
departments, programs, terms, courses, sections, and enrollments —
and then delegates the actual coursework (assignments, readings,
simulations, labs) to other Velour apps via ``ResourceLink``.

Intentionally *not* an LMS. Think of Agora as the registrar + catalog
+ schedule + roster plumbing. A linguistics section might link out
to Studious for assigned readings, Muka for syntax-tree exercises,
Lingua for translation drills, Oneliner for CS students, and so on.
What Agora owns is "who is taking what, when, with whom".

Phase 1 models:

  Department   — academic unit that owns programs and courses.
  Program      — a degree track within a department.
  Term         — an academic period (Fall 2026, Spring 2027).
  Course       — a catalog item (LING100: Introduction to Linguistics).
  Section      — one offering of a course in a specific term,
                 with instructor and meeting pattern.
  Enrollment   — a student enrolled in a section.
  ResourceLink — a pointer from a section to another Velour app's
                 model (via GenericForeignKey), so "this section uses
                 Studious scholar 42" is expressible without a hard
                 dependency from Agora to every other app.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class University(models.Model):
    """A modelled university. Agora is a meta-university: it holds
    many universities, each with its own departments, programs, and
    courses. Leiden is one; a Velour-made university (shaped around
    the user's own subject interests) is another.
    """
    slug = models.SlugField(unique=True, max_length=40)
    code = models.CharField(
        max_length=16, unique=True,
        help_text='Short code, e.g. "LEI" for Leiden, "VU" for Velour University.',
    )
    name = models.CharField(max_length=200)
    tagline = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    founded = models.PositiveIntegerField(null=True, blank=True,
        help_text='Year founded; 1575 for Leiden.')
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, blank=True)
    website = models.URLField(blank=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'universities'

    def __str__(self):
        return self.name


class Department(models.Model):
    university = models.ForeignKey(
        University, on_delete=models.CASCADE, related_name='departments',
        null=True, blank=True,
        help_text='Which university this department belongs to.',
    )
    slug = models.SlugField(max_length=40)
    code = models.CharField(
        max_length=16,
        help_text='Short dept code used in course codes (LING, CS, PHIL).',
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['university__code', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['university', 'slug'],
                name='agora_dept_university_slug_unique'),
            models.UniqueConstraint(
                fields=['university', 'code'],
                name='agora_dept_university_code_unique'),
        ]

    def __str__(self):
        if self.university:
            return f'{self.university.code}/{self.code} — {self.name}'
        return f'{self.code} — {self.name}'


class Program(models.Model):
    LEVEL_CHOICES = [
        ('ba',  "Bachelor's (BA/BSc)"),
        ('ma',  "Master's (MA/MSc)"),
        ('phd', 'Doctorate (PhD)'),
        ('cert', 'Certificate'),
    ]
    slug = models.SlugField(unique=True, max_length=60)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name='programs'
    )
    name = models.CharField(max_length=160)
    level = models.CharField(max_length=8, choices=LEVEL_CHOICES)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['department__code', 'level', 'name']

    def __str__(self):
        return f'{self.get_level_display()} — {self.name}'


class Term(models.Model):
    slug = models.SlugField(unique=True, max_length=20,
        help_text='e.g. "fall-2026", "spring-2027".')
    name = models.CharField(max_length=40)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    @property
    def is_current(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date

    @classmethod
    def current(cls):
        today = timezone.now().date()
        return (cls.objects
                .filter(start_date__lte=today, end_date__gte=today)
                .order_by('-start_date').first())


class Course(models.Model):
    """A catalog entry. Lives independently of any term; a ``Section``
    is the concrete instance offered in a given term.
    """
    slug = models.SlugField(unique=True, max_length=60)
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name='courses'
    )
    code = models.CharField(
        max_length=16,
        help_text='Full course code, e.g. LING100, CS201, PHIL305. '
                  'Unique within a department (two universities may '
                  'both have a "CS101").',
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    credits = models.PositiveSmallIntegerField(default=5,
        help_text='ECTS credits (5 is the usual Leiden default).')

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(
                fields=['department', 'code'],
                name='agora_course_department_code_unique'),
        ]

    def __str__(self):
        return f'{self.code} — {self.title}'


class Section(models.Model):
    """One offering of a course in a specific term."""
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='sections'
    )
    term = models.ForeignKey(
        Term, on_delete=models.PROTECT, related_name='sections'
    )
    section_number = models.CharField(
        max_length=6, default='01',
        help_text='Distinguishes parallel sections of the same course in '
                  'the same term (01, 02, ...).',
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='agora_sections_taught',
    )
    meeting_pattern = models.CharField(max_length=80, blank=True,
        help_text='e.g. "Mon/Wed 10:00–12:00"')
    room = models.CharField(max_length=60, blank=True)
    capacity = models.PositiveIntegerField(default=30)

    class Meta:
        unique_together = [('course', 'term', 'section_number')]
        ordering = ['-term__start_date', 'course__code', 'section_number']

    def __str__(self):
        return f'{self.course.code}-{self.section_number} ({self.term.name})'

    @property
    def enrolled_count(self):
        return self.enrollments.filter(status='enrolled').count()


class Enrollment(models.Model):
    STATUS_CHOICES = [
        ('enrolled',  'Enrolled'),
        ('waitlist',  'Waitlist'),
        ('withdrawn', 'Withdrawn'),
        ('completed', 'Completed'),
    ]
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='enrollments'
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='agora_enrollments',
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default='enrolled')
    grade = models.CharField(max_length=4, blank=True,
        help_text='Letter or numeric grade (A, B, 7.5, etc.). '
                  'Blank until the section ends.')

    class Meta:
        unique_together = [('section', 'student')]
        ordering = ['-enrolled_at']

    def __str__(self):
        return f'{self.student} in {self.section}'


class ResourceLink(models.Model):
    """A section's link to something in another Velour app.

    Uses GenericForeignKey so Agora does not need to import every
    other app. The instructor or TA can attach any kind of object —
    a Studious ``Work`` for a reading, a Muka ``Sentence`` for a
    tree-parsing exercise, an Oneliner snippet for a CS demo, a
    Reckoner task for a scale comparison, and so on.
    """
    KIND_CHOICES = [
        ('reading',    'Reading'),
        ('exercise',   'Exercise'),
        ('demo',       'Demo / simulation'),
        ('reference',  'Reference material'),
        ('assignment', 'Graded assignment'),
        ('other',      'Other'),
    ]
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name='resources'
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='reference')
    title = models.CharField(max_length=200,
        help_text='Human-readable label shown to students.')
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, null=True, blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    target = GenericForeignKey('content_type', 'object_id')
    external_url = models.URLField(blank=True,
        help_text='Fallback pointer when the resource lives outside '
                  'Velour (journal article, dataset, video).')
    notes = models.TextField(blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['section', 'kind', 'title']

    def __str__(self):
        return f'{self.section} — {self.get_kind_display()}: {self.title}'
