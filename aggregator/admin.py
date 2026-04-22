from django.contrib import admin
from .models import Article, Feed, Newspaper, NewspaperArticle


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display = ('name', 'url', 'kind', 'active', 'last_fetched',
                    'fetch_count')
    list_filter = ('active', 'kind')
    search_fields = ('name', 'url', 'topics')


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('title', 'feed', 'published_at', 'fetched_at')
    list_filter = ('feed',)
    search_fields = ('title', 'summary', 'author')
    date_hierarchy = 'published_at'


class NewspaperArticleInline(admin.TabularInline):
    model = NewspaperArticle
    extra = 0


@admin.register(Newspaper)
class NewspaperAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'created_at', 'article_count')
    inlines = [NewspaperArticleInline]
