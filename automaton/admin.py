from django.contrib import admin
from .models import Rule, RuleSet, Simulation


class RuleInline(admin.TabularInline):
    model = Rule
    extra = 1


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ('name', 'n_colors', 'source', 'created_at')
    inlines = [RuleInline]


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = ('name', 'ruleset', 'width', 'height', 'tick_count', 'created_at')
