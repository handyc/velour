from django.contrib import admin

from .models import Stage, StageType, System, TestRun, WaterProfile


@admin.register(StageType)
class StageTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'flow_lpm', 'energy_watts',
                    'maintenance_days')
    list_filter = ('kind',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug', 'description')


@admin.register(WaterProfile)
class WaterProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'scope')
    list_filter = ('scope',)
    prepopulated_fields = {'slug': ('name',)}


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0
    autocomplete_fields = ('stage_type',)


@admin.register(System)
class SystemAdmin(admin.ModelAdmin):
    list_display = ('name', 'source', 'target', 'updated_at')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [StageInline]


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ('system', 'source', 'target', 'passed', 'created_at')
    list_filter = ('passed',)
    readonly_fields = ('created_at', 'trace', 'output', 'failures')
