from django.contrib import admin
from .models import Experiment, TrainedModel, HarnessProfile


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ('component', 'pact_slug', 'title', 'created_at')
    list_filter  = ('component',)
    search_fields = ('component', 'pact_slug', 'title', 'notes')


@admin.register(TrainedModel)
class TrainedModelAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'final_fitness', 'n_blocks',
                      'distinct_rules', 'mean_pairwise', 'created_at')
    list_filter  = ('n_blocks',)
    search_fields = ('slug', 'name', 'notes')
    readonly_fields = ('rule_diversity_pretty', 'created_at')
    fieldsets = (
        (None, {
            'fields': ('slug', 'name', 'notes', 'final_fitness',
                         'vocab_size', 'n_blocks', 'pop_size', 'generations',
                         'created_at'),
        }),
        ('Rule diversity', {
            'fields': ('rule_diversity_pretty',),
            'description': (
                'The architecture has 10 distinct rule slots (q, k, v, '
                'score, mix, merge, mlp, norm, output, embed).  The whole-'
                'stack GA can converge to solutions where several slots '
                'share one byte-identical LUT — see the groups below.'),
        }),
    )

    def distinct_rules(self, obj):
        return obj.rule_diversity()['distinct_count']
    distinct_rules.short_description = 'distinct LUTs / 10'

    def mean_pairwise(self, obj):
        return f'{obj.rule_diversity()["mean_pairwise_match"]:.3f}'
    mean_pairwise.short_description = 'mean ⩵ (0.25 baseline)'

    def rule_diversity_pretty(self, obj):
        d = obj.rule_diversity()
        lines = [
            f'distinct LUTs: {d["distinct_count"]} / 10',
            f'mean pairwise byte-equality: {d["mean_pairwise_match"]:.4f} '
            f'(0.25 = uncorrelated K=4, 1.00 = all collapsed)',
            '',
            'rule slot groups (rules within a group are byte-identical):',
        ]
        for g in d['groups']:
            lines.append(f'    {", ".join(g)}')
        return '\n'.join(lines)
    rule_diversity_pretty.short_description = 'rule diversity'


@admin.register(HarnessProfile)
class HarnessProfileAdmin(admin.ModelAdmin):
    list_display = ('slug', 'persona_name', 'prefilter_mode',
                    'is_default', 'updated_at')
    list_filter  = ('prefilter_mode', 'is_default',
                    'inject_cwd', 'inject_time', 'inject_git',
                    'inject_identity')
    search_fields = ('slug', 'persona_name', 'persona_description',
                     'notes')
    prepopulated_fields = {'slug': ('persona_name',)}
    fieldsets = (
        (None, {
            'fields': ('slug', 'persona_name', 'is_default',
                         'prefilter_mode'),
        }),
        ('Prompt', {
            'fields': ('persona_description', 'system_prompt_extra'),
        }),
        ('Context injection', {
            'fields': ('inject_cwd', 'inject_time',
                         'inject_git', 'inject_identity'),
        }),
        ('Spinner verbs', {
            'fields': ('spinner_verbs_json',),
            'description': (
                'Optional per-category verb overrides.  JSON map of '
                'category code (0-3 as strings) → list of verbs.  '
                'Leave null to use caformer.harness.verbs.DEFAULT_VERBS.'),
        }),
        ('Meta', {
            'fields': ('notes',),
        }),
    )
