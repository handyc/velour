from django.contrib import admin

from .models import Job, JobHandoff, JobTarget


@admin.register(JobTarget)
class JobTargetAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'host', 'priority', 'enabled')
    list_filter = ('kind', 'enabled')
    search_fields = ('slug', 'name', 'host')


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'status', 'target',
                    'requester', 'created_at')
    list_filter = ('status', 'kind')
    search_fields = ('slug', 'name')
    readonly_fields = ('created_at', 'dispatched_at', 'finished_at')


@admin.register(JobHandoff)
class JobHandoffAdmin(admin.ModelAdmin):
    list_display = ('job', 'status', 'external_id', 'submitted_by',
                    'submitted_at')
    list_filter = ('status',)
    search_fields = ('external_id', 'job__slug')
