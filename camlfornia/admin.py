from django.contrib import admin

from .models import Attempt, Lesson


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('order', 'title', 'slug', 'difficulty', 'updated_at')
    list_editable = ('title', 'difficulty')
    list_display_links = ('order', 'slug')
    search_fields = ('slug', 'title', 'prompt_md')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('order',)


@admin.register(Attempt)
class AttemptAdmin(admin.ModelAdmin):
    list_display = ('lesson', 'user', 'passed', 'exit_code', 'created_at')
    list_filter = ('passed', 'lesson')
    readonly_fields = ('lesson', 'user', 'code', 'stdout', 'stderr',
                       'exit_code', 'passed', 'created_at')
