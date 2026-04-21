from django.contrib import admin

from .models import Server, WorkloadClass, HostedProject, GrowthAssumption


@admin.register(Server)
class ServerAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'status', 'ram_gb', 'storage_gb',
                    'cpu_cores', 'storage_used_gb')
    list_filter = ('role', 'status')
    search_fields = ('name', 'notes')


@admin.register(WorkloadClass)
class WorkloadClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'typical_ram_mb', 'new_per_year',
                    'saturation_count', 'current_count')
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
