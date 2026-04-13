from django.contrib import admin
from .models import ExactRule, Rule, RuleSet, Simulation


class RuleInline(admin.TabularInline):
    model = Rule
    extra = 1


class ExactRuleInline(admin.TabularInline):
    model = ExactRule
    extra = 0
    fields = ('priority', 'self_color', 'n0_color', 'n1_color', 'n2_color',
              'n3_color', 'n4_color', 'n5_color', 'result_color')


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ('name', 'n_colors', 'source', 'created_at')
    inlines = [RuleInline, ExactRuleInline]


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = ('name', 'ruleset', 'width', 'height', 'tick_count', 'created_at')
