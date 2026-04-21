"""Camlfornia — lessons and attempts for learning OCaml in the browser.

A Lesson is an ordered, self-contained unit with a short markdown
prompt, a starter program, and a reference solution. Running code
happens in views.py via a sandboxed `ocaml` subprocess.
"""

from django.db import models


class Lesson(models.Model):
    DIFFICULTIES = [
        ('intro',   'Intro'),
        ('basic',   'Basic'),
        ('interm',  'Intermediate'),
        ('advanced', 'Advanced'),
    ]

    slug = models.SlugField(max_length=80, unique=True)
    order = models.PositiveSmallIntegerField(default=100,
        help_text='Sort key for the curriculum listing.')
    title = models.CharField(max_length=160)
    difficulty = models.CharField(max_length=16, choices=DIFFICULTIES,
                                  default='intro')
    prompt_md = models.TextField(
        help_text='Lesson body in Markdown — explanation + task.')
    starter_code = models.TextField(
        help_text='The editor is prefilled with this.', blank=True)
    solution_code = models.TextField(
        help_text='Reference solution shown after the first attempt.',
        blank=True)
    expected_output = models.TextField(
        help_text='Optional exact-match stdout check; blank skips the check.',
        blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'slug']

    def __str__(self):
        return f'{self.order}. {self.title}'


class Attempt(models.Model):
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE,
                               related_name='attempts')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                             null=True, blank=True)
    code = models.TextField()
    stdout = models.TextField(blank=True)
    stderr = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    passed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
