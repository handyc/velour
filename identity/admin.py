from django.contrib import admin

from .models import Concern, Identity, Mood, Rule, Tick


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
