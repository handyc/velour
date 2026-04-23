"""Views for Agora — the university master framework."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import GradeEntryForm, ResourceLinkForm
from .models import (
    Course, Department, Enrollment, ResourceLink,
    Section, Term, University,
)


@login_required
def index(request):
    """Dashboard: current term, my sections (taught or enrolled)."""
    current = Term.current()
    my_taught = (Section.objects
                 .filter(instructor=request.user)
                 .select_related('course', 'term')
                 .order_by('-term__start_date'))
    my_enrolled = (Enrollment.objects
                   .filter(student=request.user)
                   .select_related('section__course', 'section__term')
                   .order_by('-section__term__start_date'))

    if current:
        current_sections = (current.sections
                            .select_related('course', 'instructor')
                            .order_by('course__code'))
    else:
        current_sections = []

    return render(request, 'agora/index.html', {
        'current_term':    current,
        'current_sections': current_sections,
        'my_taught':       my_taught,
        'my_enrolled':     my_enrolled,
        'n_universities':  University.objects.count(),
        'n_departments':   Department.objects.count(),
        'n_courses':       Course.objects.count(),
        'n_terms':         Term.objects.count(),
        'universities':    University.objects.annotate(
            n_depts=Count('departments', distinct=True),
        ).order_by('name'),
    })


@login_required
def university_list(request):
    qs = (University.objects
          .annotate(n_depts=Count('departments', distinct=True),
                    n_courses=Count('departments__courses', distinct=True))
          .order_by('name'))
    return render(request, 'agora/university_list.html',
                  {'universities': qs})


@login_required
def university_detail(request, slug):
    u = get_object_or_404(University, slug=slug)
    departments = (u.departments
                   .annotate(n_courses=Count('courses', distinct=True),
                             n_programs=Count('programs', distinct=True))
                   .order_by('code'))
    return render(request, 'agora/university_detail.html',
                  {'u': u, 'departments': departments})


@login_required
def department_list(request):
    qs = (Department.objects.select_related('university')
          .annotate(n_courses=Count('courses', distinct=True),
                    n_programs=Count('programs', distinct=True))
          .order_by('university__code', 'code'))
    u_slug = (request.GET.get('u') or '').strip()
    selected_u = None
    if u_slug:
        selected_u = University.objects.filter(slug=u_slug).first()
        if selected_u:
            qs = qs.filter(university=selected_u)
    return render(request, 'agora/department_list.html', {
        'departments': qs,
        'universities': University.objects.order_by('name'),
        'selected_u': selected_u,
    })


@login_required
def department_detail(request, slug):
    dept = get_object_or_404(Department, slug=slug)
    courses = dept.courses.order_by('code')
    programs = dept.programs.order_by('level', 'name')
    return render(request, 'agora/department_detail.html', {
        'dept': dept, 'courses': courses, 'programs': programs,
    })


@login_required
def course_list(request):
    q = (request.GET.get('q') or '').strip()
    u_slug = (request.GET.get('u') or '').strip()
    qs = (Course.objects.select_related('department__university')
          .annotate(n_sections=Count('sections'))
          .order_by('department__university__code', 'code'))
    selected_u = None
    if u_slug:
        selected_u = University.objects.filter(slug=u_slug).first()
        if selected_u:
            qs = qs.filter(department__university=selected_u)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(title__icontains=q))
    return render(request, 'agora/course_list.html', {
        'courses': qs, 'q': q,
        'universities': University.objects.order_by('name'),
        'selected_u': selected_u,
    })


@login_required
def course_detail(request, slug):
    course = get_object_or_404(Course, slug=slug)
    sections = (course.sections
                .select_related('term', 'instructor')
                .order_by('-term__start_date', 'section_number'))
    return render(request, 'agora/course_detail.html',
                  {'course': course, 'sections': sections})


@login_required
def section_detail(request, pk):
    section = get_object_or_404(
        Section.objects.select_related('course__department', 'term', 'instructor'),
        pk=pk,
    )
    roster = (section.enrollments
              .select_related('student')
              .order_by('student__last_name', 'student__username'))
    resources = section.resources.order_by('kind', 'title')
    # Is the current user the instructor? Used to reveal grade-entry
    # and resource-attach controls.
    is_instructor = (request.user == section.instructor
                     or request.user.is_superuser)
    # Is the current user enrolled?
    my_enrollment = section.enrollments.filter(student=request.user).first()
    return render(request, 'agora/section_detail.html', {
        'section': section, 'roster': roster, 'resources': resources,
        'is_instructor': is_instructor,
        'my_enrollment': my_enrollment,
    })


@login_required
@require_POST
def section_enroll(request, pk):
    """Self-enroll the logged-in user in this section."""
    section = get_object_or_404(Section, pk=pk)
    enr, created = Enrollment.objects.get_or_create(
        section=section, student=request.user,
        defaults={'status': 'enrolled'},
    )
    if not created and enr.status != 'enrolled':
        enr.status = 'enrolled'
        enr.save(update_fields=['status'])
        messages.success(request, f'Re-enrolled in {section}.')
    elif created:
        messages.success(request, f'Enrolled in {section}.')
    else:
        messages.info(request, f'Already enrolled in {section}.')
    return redirect('agora:section_detail', pk=section.pk)


@login_required
@require_POST
def section_withdraw(request, pk):
    """Drop the logged-in user's enrollment (marks it withdrawn —
    never hard-deletes, so history survives)."""
    section = get_object_or_404(Section, pk=pk)
    enr = section.enrollments.filter(student=request.user).first()
    if enr and enr.status == 'enrolled':
        enr.status = 'withdrawn'
        enr.save(update_fields=['status'])
        messages.warning(request, f'Withdrawn from {section}.')
    return redirect('agora:section_detail', pk=section.pk)


@login_required
def resource_add(request, pk):
    """Instructor-only form to attach a new ResourceLink to a section."""
    section = get_object_or_404(Section, pk=pk)
    if request.user != section.instructor and not request.user.is_superuser:
        return HttpResponseForbidden("Only the section's instructor can add resources.")

    if request.method == 'POST':
        form = ResourceLinkForm(request.POST)
        if form.is_valid():
            r = form.save(commit=False)
            r.section = section
            r.save()
            messages.success(request, f'Added resource: {r.title}')
            return redirect('agora:section_detail', pk=section.pk)
    else:
        form = ResourceLinkForm()

    return render(request, 'agora/resource_add.html', {
        'section': section, 'form': form,
    })


@login_required
@require_POST
def resource_delete(request, pk, rpk):
    section = get_object_or_404(Section, pk=pk)
    if request.user != section.instructor and not request.user.is_superuser:
        return HttpResponseForbidden("Only the section's instructor can delete resources.")
    r = get_object_or_404(ResourceLink, pk=rpk, section=section)
    title = r.title
    r.delete()
    messages.warning(request, f'Removed resource: {title}')
    return redirect('agora:section_detail', pk=section.pk)


@login_required
def grades_edit(request, pk):
    """Bulk-edit grades and statuses for a section. Instructor-only."""
    section = get_object_or_404(
        Section.objects.select_related('course', 'term', 'instructor'), pk=pk,
    )
    if request.user != section.instructor and not request.user.is_superuser:
        return HttpResponseForbidden("Only the section's instructor can edit grades.")

    enrollments = list(
        section.enrollments.select_related('student')
        .order_by('student__last_name', 'student__username')
    )

    if request.method == 'POST':
        form = GradeEntryForm(request.POST, enrollments=enrollments)
        if form.is_valid():
            form.save()
            messages.success(request, 'Grades saved.')
            return redirect('agora:section_detail', pk=section.pk)
    else:
        form = GradeEntryForm(enrollments=enrollments)

    return render(request, 'agora/grades_edit.html', {
        'section': section, 'form': form,
    })


@login_required
def term_list(request):
    qs = (Term.objects
          .annotate(n_sections=Count('sections'))
          .order_by('-start_date'))
    return render(request, 'agora/term_list.html', {'terms': qs})
