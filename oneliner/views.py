from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import MAX_LINE, Oneliner


@login_required
def index(request):
    sort = request.GET.get('sort', 'name')
    lang = request.GET.get('lang', '')
    qs = Oneliner.objects.all()
    if lang in {'c', 'bash'}:
        qs = qs.filter(language=lang)
    programs = list(qs)
    if sort == 'size':
        programs.sort(key=lambda o: (o.last_binary_size or 10**9, o.name))
    elif sort == 'chars':
        programs.sort(key=lambda o: (o.char_count, o.name))
    else:
        programs.sort(key=lambda o: o.name.lower())
    return render(request, 'oneliner/index.html', {
        'programs': programs,
        'sort':     sort,
        'lang':     lang,
        'max_line': MAX_LINE,
    })


@login_required
def detail(request, slug):
    program = get_object_or_404(Oneliner, slug=slug)
    return render(request, 'oneliner/detail.html', {
        'program':  program,
        'max_line': MAX_LINE,
    })


@login_required
def create(request):
    if request.method == 'POST':
        return _save_from_post(request, program=None)
    return render(request, 'oneliner/form.html', {
        'program':  None,
        'max_line': MAX_LINE,
        'values':   _values_from(None),
    })


@login_required
def edit(request, slug):
    program = get_object_or_404(Oneliner, slug=slug)
    if request.method == 'POST':
        return _save_from_post(request, program=program)
    return render(request, 'oneliner/form.html', {
        'program':  program,
        'max_line': MAX_LINE,
        'values':   _values_from(program),
    })


def _values_from(program):
    if program is None:
        return {'name': '', 'slug': '', 'code': '',
                'purpose': '', 'language': 'c',
                'compile_flags': '-w', 'stdin_fixture': ''}
    return {
        'name':          program.name,
        'slug':          program.slug,
        'code':          program.code,
        'purpose':       program.purpose,
        'language':      program.language,
        'compile_flags': program.compile_flags,
        'stdin_fixture': program.stdin_fixture,
    }


def _save_from_post(request, program):
    language = (request.POST.get('language') or 'c').strip()
    if language not in {'c', 'bash'}:
        language = 'c'
    default_flags = '-w' if language == 'c' else ''
    values = {
        'name':          (request.POST.get('name') or '').strip(),
        'slug':          slugify((request.POST.get('slug')
                                 or request.POST.get('name') or '').strip()),
        'code':          request.POST.get('code') or '',
        'purpose':       (request.POST.get('purpose') or '').strip(),
        'language':      language,
        'compile_flags': (request.POST.get('compile_flags')
                          or default_flags).strip(),
        'stdin_fixture': request.POST.get('stdin_fixture') or '',
    }

    if not values['name'] or not values['slug']:
        messages.error(request, 'Name and slug are required.')
        return render(request, 'oneliner/form.html', {
            'program': program, 'max_line': MAX_LINE, 'values': values})

    if program is None:
        if Oneliner.objects.filter(slug=values['slug']).exists():
            messages.error(request,
                f'Slug "{values["slug"]}" already exists.')
            return render(request, 'oneliner/form.html', {
                'program': None, 'max_line': MAX_LINE, 'values': values})
        program = Oneliner(slug=values['slug'])

    for k, v in values.items():
        setattr(program, k, v)

    try:
        program.full_clean()
    except ValidationError as exc:
        for field, errs in exc.message_dict.items():
            for e in errs:
                messages.error(request, f'{field}: {e}')
        return render(request, 'oneliner/form.html', {
            'program': program if program.pk else None,
            'max_line': MAX_LINE, 'values': values})

    program.save()
    messages.success(request,
        f'Saved "{program.name}" ({program.char_count} ch longest line).')
    return redirect('oneliner:detail', slug=program.slug)


@login_required
@require_POST
def compile_view(request, slug):
    program = get_object_or_404(Oneliner, slug=slug)
    result = program.compile()
    if result['status'] == 'error':
        messages.error(request, 'Compile failed — see output below.')
    elif result['status'] == 'warn':
        messages.info(request,
            f'Compiled with warnings — binary is {result["binary_size"]} B.')
    elif program.language == 'bash':
        messages.success(request, 'Syntax clean — bash -n parsed the script.')
    else:
        messages.success(request,
            f'Compiled clean — binary is {result["binary_size"]} B.')
    return redirect('oneliner:detail', slug=program.slug)


@login_required
@require_POST
def run_view(request, slug):
    program = get_object_or_404(Oneliner, slug=slug)
    stdin = request.POST.get('stdin')
    if stdin is None or not stdin:
        stdin = program.stdin_fixture
    result = program.run(stdin=stdin)
    if result['exit'] is None:
        messages.error(request, 'Run failed — see output.')
    else:
        messages.success(request,
            f'Ran clean — exit {result["exit"]}.')
    return redirect('oneliner:detail', slug=program.slug)


@login_required
@require_POST
def delete(request, slug):
    program = get_object_or_404(Oneliner, slug=slug)
    name = program.name
    program.delete()
    messages.success(request, f'Deleted "{name}".')
    return redirect('oneliner:index')
