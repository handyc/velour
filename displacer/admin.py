"""Admin tuned for non-technical editors.

Goal: an editor who has never used Django before can find a story,
edit it, replace its hero image, and save — without ever touching
the model dropdowns by themselves.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Article, ArticleCredit, Category, MediaAsset, Page, Person,
    SiteSettings, Theme,
)


# --- Inlines --------------------------------------------------------


class ArticleCreditInline(admin.TabularInline):
    model = ArticleCredit
    extra = 1
    autocomplete_fields = ['person']
    fields = ['person', 'role', 'order']


# --- Article --------------------------------------------------------


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'thumb', 'published', 'featured',
                    'published_at', 'updated_at']
    list_display_links = ['title']
    list_filter = ['published', 'featured', 'themes', 'categories']
    list_editable = ['published', 'featured']
    search_fields = ['title', 'summary', 'body_html']
    date_hierarchy = 'published_at'
    prepopulated_fields = {'slug': ('title',)}
    autocomplete_fields = ['hero_image']
    filter_horizontal = ['themes', 'categories']
    inlines = [ArticleCreditInline]
    save_on_top = True

    fieldsets = [
        ('Story', {
            'fields': ['title', 'slug', 'summary', 'body_html'],
            'description': 'Title, lede paragraph, and the full story HTML.',
        }),
        ('Image', {
            'fields': ['hero_image'],
        }),
        ('Tags', {
            'fields': ['themes', 'categories'],
        }),
        ('Publishing', {
            'fields': ['published', 'published_at',
                       'featured', 'featured_order'],
        }),
        ('Source (advanced)', {
            'classes': ['collapse'],
            'fields': ['zotonic_id', 'original_url'],
            'description': 'Filled automatically when imported from displace.nl. '
                           'Leave alone unless you know what you are doing.',
        }),
    ]

    def thumb(self, obj):
        if obj.hero_image and obj.hero_image.file:
            return format_html(
                '<img src="{}" style="height:36px;border-radius:2px;"/>',
                obj.hero_image.file.url,
            )
        return ''
    thumb.short_description = 'Image'


# --- Theme ----------------------------------------------------------


@admin.register(Theme)
class ThemeAdmin(admin.ModelAdmin):
    list_display = ['title', 'order', 'published', 'updated_at']
    list_editable = ['order', 'published']
    list_filter = ['published']
    search_fields = ['title', 'summary', 'body_html']
    prepopulated_fields = {'slug': ('title',)}
    autocomplete_fields = ['hero_image']

    fieldsets = [
        ('Theme', {
            'fields': ['title', 'slug', 'subtitle', 'summary', 'body_html'],
        }),
        ('Image', {'fields': ['hero_image']}),
        ('Display', {'fields': ['order', 'published', 'published_at']}),
        ('Source (advanced)', {
            'classes': ['collapse'],
            'fields': ['zotonic_id', 'original_url'],
        }),
    ]


# --- Category, Person, MediaAsset ----------------------------------


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    search_fields = ['name']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ['name', 'email']
    search_fields = ['name', 'email', 'bio']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ['preview', 'title', 'caption_short', 'credit',
                    'created_at']
    list_display_links = ['preview', 'title']
    search_fields = ['title', 'caption', 'credit', 'alt_text', 'sha256']
    readonly_fields = ['sha256', 'created_at', 'updated_at']
    fieldsets = [
        ('Image', {'fields': ['title', 'file', 'alt_text']}),
        ('Caption', {'fields': ['caption', 'credit']}),
        ('Source (advanced)', {
            'classes': ['collapse'],
            'fields': ['original_url', 'sha256',
                       'created_at', 'updated_at'],
        }),
    ]

    def preview(self, obj):
        if obj.file:
            return format_html(
                '<img src="{}" style="height:48px;border-radius:2px;"/>',
                obj.file.url,
            )
        return ''
    preview.short_description = 'Preview'

    def caption_short(self, obj):
        c = (obj.caption or '').strip().replace('\n', ' ')
        return c[:80] + ('…' if len(c) > 80 else '')
    caption_short.short_description = 'Caption'


# --- Page -----------------------------------------------------------


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'show_in_menu', 'show_in_footer',
                    'order', 'published']
    list_editable = ['show_in_menu', 'show_in_footer', 'order', 'published']
    search_fields = ['title', 'body_html']
    prepopulated_fields = {'slug': ('title',)}

    fieldsets = [
        ('Page', {'fields': ['title', 'slug', 'body_html']}),
        ('Where it appears', {
            'fields': ['show_in_menu', 'show_in_footer', 'order', 'published'],
        }),
        ('Source (advanced)', {
            'classes': ['collapse'],
            'fields': ['zotonic_id', 'original_url'],
        }),
    ]


# --- Site settings (singleton) -------------------------------------


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ('Site', {'fields': ['site_name', 'home_intro', 'contact_email']}),
        ('Tracking', {'fields': ['ga_tracking_id']}),
    ]

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
