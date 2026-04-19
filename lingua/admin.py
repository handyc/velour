from django.contrib import admin

from .models import Language, TranslationCache, UserLanguagePreference


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display  = ('code', 'name', 'endonym', 'script', 'rtl', 'low_resource')
    list_filter   = ('script', 'low_resource', 'rtl')
    search_fields = ('code', 'name', 'endonym')


@admin.register(TranslationCache)
class TranslationCacheAdmin(admin.ModelAdmin):
    list_display  = ('target_lang', 'source_lang', 'short', 'backend',
                     'confidence', 'reviewed_by_human', 'hit_count')
    list_filter   = ('target_lang', 'source_lang', 'backend', 'reviewed_by_human')
    search_fields = ('source_text', 'translation')
    readonly_fields = ('source_hash', 'tokens_in', 'tokens_out',
                       'hit_count', 'last_hit_at', 'created_at')

    def short(self, obj):
        head = (obj.source_text or '')[:60].replace('\n', ' ')
        return head + ('…' if len(obj.source_text) > 60 else '')


@admin.register(UserLanguagePreference)
class UserLanguagePreferenceAdmin(admin.ModelAdmin):
    list_display  = ('user', 'auto_translate', 'hover_modifier', 'updated_at')
    search_fields = ('user__username',)
