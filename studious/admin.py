from django.contrib import admin

from .models import Argument, ArgumentClaim, Claim, Domain, Scholar, Work


@admin.register(Scholar)
class ScholarAdmin(admin.ModelAdmin):
    list_display = ('name', 'affiliation', 'active_years', 'created_at')
    search_fields = ('name', 'affiliation', 'bio')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Work)
class WorkAdmin(admin.ModelAdmin):
    list_display = ('title', 'scholar', 'year', 'kind', 'ingested_at')
    list_filter = ('kind', 'scholar', 'domains')
    search_fields = ('title', 'abstract', 'full_text')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ('work', 'kind', 'score', 'auto_extracted', 'order')
    list_filter = ('kind', 'auto_extracted')
    search_fields = ('text',)


class ArgumentClaimInline(admin.TabularInline):
    model = ArgumentClaim
    extra = 0


@admin.register(Argument)
class ArgumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'kind', 'domain', 'modified_at')
    list_filter = ('kind', 'domain')
    search_fields = ('title', 'synthesis_text', 'premises_text')
    inlines = [ArgumentClaimInline]
    prepopulated_fields = {'slug': ('title',)}
