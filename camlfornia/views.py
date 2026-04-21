import json
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from . import runner
from .models import Attempt, Lesson


def _render_md(text):
    """Minimal Markdown — headings, paragraphs, inline `code`, **bold**.
    Avoids pulling in a Markdown dependency for a teaching app."""
    out = []
    for para in re.split(r'\n\s*\n', text.strip()):
        para = para.strip()
        m = re.match(r'^(#{1,4})\s+(.*)', para)
        if m:
            level = len(m.group(1))
            out.append(f'<h{level + 1}>{_inline(m.group(2))}</h{level + 1}>')
            continue
        if para.startswith('```'):
            body = para.strip('`').strip()
            out.append(f'<pre class="cm-block"><code>{_esc(body)}</code></pre>')
            continue
        out.append(f'<p>{_inline(para)}</p>')
    return '\n'.join(out)


def _esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;')
             .replace('>', '&gt;'))


def _inline(s):
    s = _esc(s)
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    return s


@login_required
def index(request):
    lessons = list(Lesson.objects.all())
    passed_ids = set(Attempt.objects.filter(
        user=request.user, passed=True
    ).values_list('lesson_id', flat=True))
    for l in lessons:
        l.is_passed = l.pk in passed_ids
    return render(request, 'camlfornia/index.html', {
        'lessons':         lessons,
        'passed_count':    len(passed_ids),
        'ocaml_installed': runner.ocaml_installed(),
    })


@login_required
def lesson(request, slug):
    les = get_object_or_404(Lesson, slug=slug)
    last_attempt = (Attempt.objects.filter(lesson=les, user=request.user)
                    .first() if request.user.is_authenticated else None)
    passed_once = (Attempt.objects.filter(
        lesson=les, user=request.user, passed=True).exists()
        if request.user.is_authenticated else False)
    lessons_all = list(Lesson.objects.all())
    idx = [i for i, l in enumerate(lessons_all) if l.pk == les.pk][0]
    prev_lesson = lessons_all[idx - 1] if idx > 0 else None
    next_lesson = lessons_all[idx + 1] if idx + 1 < len(lessons_all) else None
    return render(request, 'camlfornia/lesson.html', {
        'lesson':          les,
        'prompt_html':     _render_md(les.prompt_md),
        'initial_code':    (last_attempt.code if last_attempt
                            else les.starter_code),
        'passed_once':     passed_once,
        'prev_lesson':     prev_lesson,
        'next_lesson':     next_lesson,
        'ocaml_installed': runner.ocaml_installed(),
    })


@login_required
@require_POST
def run_code(request, slug):
    les = get_object_or_404(Lesson, slug=slug)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Bad JSON body.'}, status=400)
    code = payload.get('code', '')
    stdin = payload.get('stdin', '')
    if not isinstance(code, str) or len(code) > 20_000:
        return JsonResponse({'error': 'Code missing or too large.'}, status=400)

    result = runner.run(code, stdin=stdin)

    passed = False
    if result['installed'] and result['exit_code'] == 0:
        if les.expected_output:
            got = result['stdout'].rstrip('\n')
            want = les.expected_output.rstrip('\n')
            passed = got == want
        else:
            passed = True

    Attempt.objects.create(
        lesson=les, user=request.user, code=code,
        stdout=result['stdout'], stderr=result['stderr'],
        exit_code=result['exit_code'] if result['exit_code'] is not None else -1,
        passed=passed,
    )

    return JsonResponse({
        **result,
        'passed': passed,
        'expected_output': les.expected_output,
    })
