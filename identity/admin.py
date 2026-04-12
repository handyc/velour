from django.contrib import admin

from .models import (
    Concern, CronRun, Identity, IdentityAssertion, IdentityToggles,
    Meditation, Mood, Reflection, Rule, Tick,
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


@admin.register(IdentityToggles)
class IdentityTogglesAdmin(admin.ModelAdmin):
    list_display = ('ticks_enabled', 'reflections_enabled',
                    'meditations_enabled', 'oracle_enabled', 'updated_at')


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
