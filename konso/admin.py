from django.contrib import admin

from .models import Sentence


@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ('slug', 'konso', 'translation', 'source')
    list_filter = ('source',)
    search_fields = ('slug', 'konso', 'translation', 'gloss', 'notes')
    prepopulated_fields = {'slug': ('konso',)}
