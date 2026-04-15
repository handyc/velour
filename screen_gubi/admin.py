from django.contrib import admin

from .models import GubiWorld


@admin.register(GubiWorld)
class GubiWorldAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'updated_at', 'created_at')
    search_fields = ('title', 'text')
    prepopulated_fields = {'slug': ('title',)}
