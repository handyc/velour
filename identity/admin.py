from django.contrib import admin

from .models import Identity, Mood, Tick


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
