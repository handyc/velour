from django.contrib import admin

from .models import PlantSpecies


@admin.register(PlantSpecies)
class PlantSpeciesAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'axiom', 'iterations', 'featured', 'updated_at']
    list_filter = ['category', 'featured']
    search_fields = ['name', 'tags']
    prepopulated_fields = {'slug': ('name',)}
