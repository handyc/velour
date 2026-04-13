from django.contrib import admin

from .models import (
    ClaudeHook, Concern, ContinuityMarker, CronRun, DwellingState,
    Identity, IdentityAssertion, IdentityToggles, InternalDialogue,
    Intervention, IntrospectiveLayer, LLMExchange, LLMProvider,
    LoopTraversal, Meditation, MentalHealthDiagnosis, Mood, Reflection,
    Rule, StrangeLoop, TemplateContribution, ThoughtExperiment, Tick,
)


@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ('name', 'mood', 'mood_intensity', 'hostname', 'last_reflection')
    readonly_fields = ('birth_date', 'last_reflection')


@admin.register(Mood)
class MoodAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'mood', 'intensity', 'trigger')
    list_filter = ('mood',)
    date_hierarchy = 'timestamp'
    readonly_fields = ('timestamp',)


@admin.register(Tick)
class TickAdmin(admin.ModelAdmin):
    list_display = ('at', 'mood', 'mood_intensity', 'rule_label', 'triggered_by')
    list_filter = ('mood', 'triggered_by')
    date_hierarchy = 'at'
    readonly_fields = ('at', 'snapshot', 'aspects')
    search_fields = ('thought', 'rule_label')
    inlines = []  # InterventionInline added after definition below


@admin.register(Concern)
class ConcernAdmin(admin.ModelAdmin):
    list_display = ('aspect', 'name', 'severity', 'reconfirm_count',
                    'opened_at', 'closed_at')
    list_filter = ('aspect', 'closed_at')
    readonly_fields = ('opened_at', 'last_seen_at', 'origin_tick')
    search_fields = ('aspect', 'name', 'description')


@admin.register(Meditation)
class MeditationAdmin(admin.ModelAdmin):
    list_display = ('title', 'depth', 'voice', 'composed_at', 'recursive_of')
    list_filter = ('depth', 'voice')
    date_hierarchy = 'composed_at'
    readonly_fields = ('composed_at', 'sources', 'codex_section_slug')
    search_fields = ('title', 'body')


@admin.register(IdentityAssertion)
class IdentityAssertionAdmin(admin.ModelAdmin):
    list_display = ('frame', 'title', 'kind', 'source', 'strength',
                    'is_active')
    list_filter = ('frame', 'source', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('title', 'body', 'kind')
    readonly_fields = ('first_asserted_at', 'last_confirmed_at')
    fieldsets = (
        (None, {'fields': ('frame', 'kind', 'title', 'body', 'is_active')}),
        ('Provenance', {'fields': ('source', 'strength',
                                   'first_asserted_at', 'last_confirmed_at')}),
    )


@admin.register(ContinuityMarker)
class ContinuityMarkerAdmin(admin.ModelAdmin):
    list_display = ('at', 'kind', 'title', 'source_model')
    list_filter = ('kind',)
    date_hierarchy = 'at'
    readonly_fields = ('at',)
    search_fields = ('title', 'description')


@admin.register(DwellingState)
class DwellingStateAdmin(admin.ModelAdmin):
    list_display = ('topic', 'is_active', 'depth', 'opened_at')
    readonly_fields = ('last_touched_at', 'updated_at')


@admin.register(InternalDialogue)
class InternalDialogueAdmin(admin.ModelAdmin):
    list_display = ('topic', 'speaker_a', 'speaker_b', 'created_at')
    date_hierarchy = 'created_at'


@admin.register(IdentityToggles)
class IdentityTogglesAdmin(admin.ModelAdmin):
    list_display = ('ticks_enabled', 'reflections_enabled',
                    'meditations_enabled', 'oracle_enabled', 'updated_at')


@admin.register(ClaudeHook)
class ClaudeHookAdmin(admin.ModelAdmin):
    list_display = ('kind', 'title', 'status', 'composed_by', 'created_at')
    list_filter = ('kind', 'status')
    list_editable = ('status',)
    readonly_fields = ('created_at', 'context')
    search_fields = ('title', 'body', 'resolution')


@admin.register(TemplateContribution)
class TemplateContributionAdmin(admin.ModelAdmin):
    list_display = ('template', 'status', 'source', 'is_active', 'created_at')
    list_filter = ('status', 'is_active')
    list_editable = ('status', 'is_active')
    search_fields = ('template', 'source')


@admin.register(LLMProvider)
class LLMProviderAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'model', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug', 'model', 'base_url')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(LLMExchange)
class LLMExchangeAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'provider', 'tokens_in', 'tokens_out',
                    'latency_ms', 'ingested_as_assertion')
    list_filter = ('provider', 'ingested_as_assertion')
    readonly_fields = ('created_at', 'prompt', 'system_prompt',
                       'response', 'tokens_in', 'tokens_out',
                       'latency_ms', 'error')


@admin.register(Reflection)
class ReflectionAdmin(admin.ModelAdmin):
    list_display = ('title', 'period', 'period_start', 'ticks_referenced',
                    'composed_at')
    list_filter = ('period',)
    date_hierarchy = 'period_start'
    readonly_fields = ('composed_at', 'metrics', 'codex_section_slug')
    search_fields = ('title', 'body')


@admin.register(CronRun)
class CronRunAdmin(admin.ModelAdmin):
    list_display = ('at', 'kind', 'status', 'summary')
    list_filter = ('kind', 'status')
    date_hierarchy = 'at'
    readonly_fields = ('at', 'kind', 'status', 'summary', 'details')
    search_fields = ('summary', 'details')


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ('priority', 'name', 'aspect', 'mood', 'intensity',
                    'opens_concern', 'is_active')
    list_display_links = ('name',)
    list_filter = ('is_active', 'mood', 'opens_concern')
    list_editable = ('priority', 'is_active')
    search_fields = ('name', 'aspect')
    fieldsets = (
        (None, {
            'fields': ('name', 'aspect', 'priority', 'is_active'),
        }),
        ('When it fires', {
            'fields': ('condition',),
            'description': 'JSON condition. Leaf: {"metric": "path.to.value", '
                           '"op": ">", "value": 0.95}. Compound: {"all": [...]} '
                           'or {"any": [...]}.',
        }),
        ('What it produces', {
            'fields': ('mood', 'intensity', 'opens_concern'),
        }),
    )


# =====================================================================
# Hofstadter admin — absorbed from the standalone hofstadter app.
# =====================================================================

@admin.register(StrangeLoop)
class StrangeLoopAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'discovered_by', 'is_active')
    list_filter = ('kind', 'discovered_by', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(LoopTraversal)
class LoopTraversalAdmin(admin.ModelAdmin):
    list_display = ('loop', 'started_at', 'steps_taken', 'exit_reason')
    list_filter = ('loop', 'exit_reason')
    readonly_fields = ('started_at', 'completed_at', 'steps')


@admin.register(ThoughtExperiment)
class ThoughtExperimentAdmin(admin.ModelAdmin):
    list_display = ('name', 'seed_layer', 'status', 'exit_reason',
                    'created_at')
    list_filter = ('status', 'seed_layer', 'exit_reason')
    search_fields = ('name', 'premise', 'conclusion')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('started_at', 'completed_at', 'trace', 'exit_reason',
                       'conclusion', 'status')


@admin.register(IntrospectiveLayer)
class IntrospectiveLayerAdmin(admin.ModelAdmin):
    list_display = ('layer', 'title', 'source', 'strength', 'is_active')
    list_filter = ('layer', 'source', 'is_active')
    search_fields = ('title', 'body')


@admin.register(MentalHealthDiagnosis)
class MentalHealthDiagnosisAdmin(admin.ModelAdmin):
    list_display = ('at', 'health_score', 'avg_valence', 'negative_ratio',
                    'dominant_mood', 'concern_count')
    list_filter = ('dominant_mood',)
    readonly_fields = ('at',)


class InterventionInline(admin.TabularInline):
    model = Intervention
    extra = 0
    readonly_fields = ('technique', 'description', 'delta_valence',
                       'delta_arousal', 'original_mood', 'corrected_mood')


@admin.register(Intervention)
class InterventionAdmin(admin.ModelAdmin):
    list_display = ('at', 'tick', 'technique', 'delta_valence',
                    'delta_arousal', 'original_mood', 'corrected_mood')
    list_filter = ('technique',)


# Wire InterventionInline into TickAdmin (defined earlier)
TickAdmin.inlines = [InterventionInline]
