from django.contrib import admin

from .models import Article, Section, SiteSettings


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'order', 'visible')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'section', 'is_featured', 'is_published', 'author', 'created_at')
    list_filter = ('section', 'is_featured', 'is_published')
    search_fields = ('title', 'body')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    pass
