from django.contrib import admin

from .models import Language, Variety, Lemma, Sign, Frame, Source


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'iso639_3', 'region', 'family')
    search_fields = ('name', 'iso639_3', 'region', 'family')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Variety)
class VarietyAdmin(admin.ModelAdmin):
    list_display = ('name', 'language')
    list_filter = ('language',)
    search_fields = ('name',)


@admin.register(Lemma)
class LemmaAdmin(admin.ModelAdmin):
    list_display = ('gloss', 'semantic_field')
    search_fields = ('gloss', 'semantic_field')
    prepopulated_fields = {'slug': ('gloss',)}


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('name', 'doi', 'license_text')
    search_fields = ('name', 'citation', 'doi')
    prepopulated_fields = {'slug': ('name',)}


class FrameInline(admin.TabularInline):
    model = Frame
    extra = 0
    fields = ('index', 'duration_ms')
    readonly_fields = ('index', 'duration_ms')
    show_change_link = True


@admin.register(Sign)
class SignAdmin(admin.ModelAdmin):
    list_display = ('lemma', 'variety', 'signer', 'fps', 'n_frames', 'recorded_at')
    list_filter = ('variety__language', 'variety')
    search_fields = ('lemma__gloss', 'signer', 'notes')
    inlines = [FrameInline]


@admin.register(Frame)
class FrameAdmin(admin.ModelAdmin):
    list_display = ('sign', 'index', 'duration_ms')
    list_filter = ('sign__variety',)
