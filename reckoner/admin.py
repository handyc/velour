from django.contrib import admin

from .models import AppProfile, AppTaskUsage, ComputeTask, EnergyComparable


@admin.register(EnergyComparable)
class EnergyComparableAdmin(admin.ModelAdmin):
    list_display = ('icon', 'name', 'energy_joules', 'slug')
    search_fields = ('name', 'slug')
    ordering = ('energy_joules',)


@admin.register(ComputeTask)
class ComputeTaskAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'category', 'energy_joules',
        'environmental_score', 'political_score',
        'economic_score', 'social_score',
    )
    list_filter = ('category',)
    search_fields = ('name', 'slug', 'description')
    ordering = ('energy_joules',)


class AppTaskUsageInline(admin.TabularInline):
    model = AppTaskUsage
    extra = 0
    autocomplete_fields = ('task',)


@admin.register(AppProfile)
class AppProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order')
    search_fields = ('name', 'slug', 'description')
    inlines = [AppTaskUsageInline]
