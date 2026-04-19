from django.contrib import admin

from .models import Circuit, CircuitPart, Part, PartPriceSnapshot


class CircuitPartInline(admin.TabularInline):
    model = CircuitPart
    extra = 1
    autocomplete_fields = ('part',)


@admin.register(Circuit)
class CircuitAdmin(admin.ModelAdmin):
    list_display = ('display_order', 'status', 'title', 'tagline', 'updated_at')
    list_display_links = ('title',)
    list_editable = ('display_order', 'status')
    list_filter = ('status',)
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('display_order',)
    inlines = [CircuitPartInline]


class PartPriceSnapshotInline(admin.TabularInline):
    model = PartPriceSnapshot
    extra = 0
    readonly_fields = ('observed_at',)


@admin.register(Part)
class PartAdmin(admin.ModelAdmin):
    list_display = (
        'category', 'name', 'mpn',
        'est_unit_price_usd', 'price_last_checked_at',
    )
    list_filter = ('category',)
    search_fields = ('name', 'mpn', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [PartPriceSnapshotInline]
