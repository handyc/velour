from django.contrib import admin

from .models import Constraint, Feature, FurniturePiece, Placement, Room


class FeatureInline(admin.TabularInline):
    model = Feature
    extra = 0


class PlacementInline(admin.TabularInline):
    model = Placement
    extra = 0
    autocomplete_fields = ('piece',)


class ConstraintInline(admin.TabularInline):
    model = Constraint
    extra = 0


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'width_cm', 'length_cm',
                    'north_direction', 'location_city', 'updated_at')
    list_filter = ('north_direction',)
    prepopulated_fields = {'slug': ('name',)}
    inlines = [FeatureInline, PlacementInline, ConstraintInline]


@admin.register(FurniturePiece)
class FurniturePieceAdmin(admin.ModelAdmin):
    list_display = ('kind', 'name', 'width_cm', 'depth_cm',
                    'heat_watts', 'needs_outlet')
    list_filter = ('kind', 'needs_outlet')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug')


@admin.register(Placement)
class PlacementAdmin(admin.ModelAdmin):
    list_display = ('room', 'piece', 'label', 'x_cm', 'y_cm', 'rotation_deg')
    list_filter = ('room',)
    autocomplete_fields = ('piece',)


@admin.register(Constraint)
class ConstraintAdmin(admin.ModelAdmin):
    list_display = ('kind', 'description', 'room', 'active')
    list_filter = ('kind', 'active')


admin.site.register(Feature)
