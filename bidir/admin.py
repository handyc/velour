from django.contrib import admin

from .models import Build, Feature, PortStatus, Variant


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'runtime_kind', 'is_canonical',
                    'sort_order')
    list_filter = ('runtime_kind', 'is_canonical')
    search_fields = ('slug', 'name')


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'introduced_in', 'sort_order')
    search_fields = ('slug', 'name', 'description')


@admin.register(PortStatus)
class PortStatusAdmin(admin.ModelAdmin):
    list_display = ('feature', 'variant', 'state', 'updated_at')
    list_filter = ('state', 'variant')
    search_fields = ('feature__slug', 'variant__slug')


@admin.register(Build)
class BuildAdmin(admin.ModelAdmin):
    list_display = ('variant', 'label', 'bytes_size', 'created_at')
    list_filter = ('variant',)
    search_fields = ('label', 'file_path', 'git_commit')
