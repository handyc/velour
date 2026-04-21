from django.contrib import admin

from .models import (Server, WorkloadClass, HostedProject, GrowthAssumption,
                     Candidate, Scenario, Snapshot)


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'status', 'ram_gb', 'storage_gb',
                    'cpu_cores', 'storage_used_gb')
    list_filter = ('role', 'status')
    search_fields = ('name', 'notes')


@admin.register(WorkloadClass)
class WorkloadClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'typical_ram_mb', 'peak_concurrency',
                    'active_fraction', 'new_per_year', 'saturation_count',
                    'current_count')
    search_fields = ('name', 'description')


@admin.register(HostedProject)
class HostedProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'server', 'workload_class', 'framework')
    list_filter = ('server', 'workload_class', 'framework')
    search_fields = ('name', 'notes')


@admin.register(GrowthAssumption)
class GrowthAssumptionAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'unit')
    search_fields = ('key', 'description')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('name', 'purpose', 'ram_gb', 'storage_gb', 'cpu_cores',
                    'approximate_cost_eur', 'monthly_cost_eur',
                    'five_year_tco_eur')
    list_filter = ('purpose',)
    search_fields = ('name', 'notes')


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_ram_gb', 'total_storage_gb',
                    'total_cpu_cores', 'total_cost_eur')
    filter_horizontal = ('candidates',)
    search_fields = ('name', 'description')


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name', 'notes')
    readonly_fields = ('payload', 'created_at')
