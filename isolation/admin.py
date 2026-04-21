from django.contrib import admin

from .models import IsolationTarget, Pipeline, Stage


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0


class TargetInline(admin.TabularInline):
    model = IsolationTarget
    extra = 0


@admin.register(Pipeline)
class PipelineAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'apps_used', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [StageInline, TargetInline]


@admin.register(IsolationTarget)
class TargetAdmin(admin.ModelAdmin):
    list_display = ('pipeline', 'target', 'status', 'size_bytes', 'updated_at')
    list_filter = ('target', 'status')
