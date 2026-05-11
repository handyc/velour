from django.contrib import admin

from .models import World, Block, Sentence


class BlockInline(admin.TabularInline):
    model = Block
    extra = 0


class SentenceInline(admin.TabularInline):
    model = Sentence
    extra = 0
    fields = ('position', 'text', 'target_mode', 'parse_error')
    readonly_fields = ('parse_error',)


@admin.register(World)
class WorldAdmin(admin.ModelAdmin):
    list_display = ('name', 'mode', 'dim', 'updated_at')
    list_filter  = ('mode',)
    search_fields = ('name',)
    inlines = [BlockInline, SentenceInline]


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ('world', 'name', 'shape', 'size', 'x', 'y')
    list_filter  = ('shape', 'size')
    search_fields = ('name',)


@admin.register(Sentence)
class SentenceAdmin(admin.ModelAdmin):
    list_display = ('world', 'position', 'short', 'target_mode')
    list_filter  = ('target_mode',)
    search_fields = ('text',)

    @admin.display(description='text')
    def short(self, obj):
        return (obj.text or '')[:80]
