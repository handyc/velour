from django.contrib import admin

from .models import (
    Course, Department, Enrollment, Program, ResourceLink,
    Section, Term, University,
)


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'city', 'country', 'founded')
    search_fields = ('code', 'name', 'city')
    prepopulated_fields = {'slug': ('code',)}


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'university')
    list_filter = ('university',)
    search_fields = ('code', 'name')
    prepopulated_fields = {'slug': ('code',)}


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('name', 'department', 'level')
    list_filter = ('department', 'level')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'department', 'credits')
    list_filter = ('department',)
    search_fields = ('code', 'title')
    prepopulated_fields = {'slug': ('code',)}


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('course', 'term', 'section_number',
                    'instructor', 'enrolled_count', 'capacity')
    list_filter = ('term', 'course__department')
    search_fields = ('course__code', 'course__title')
    raw_id_fields = ('instructor',)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'section', 'status', 'grade', 'enrolled_at')
    list_filter = ('status', 'section__term')
    raw_id_fields = ('student', 'section')


@admin.register(ResourceLink)
class ResourceLinkAdmin(admin.ModelAdmin):
    list_display = ('section', 'kind', 'title')
    list_filter = ('kind', 'section__term')
