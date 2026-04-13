from django.contrib import admin

from .models import LiftJob


@admin.register(LiftJob)
class LiftJobAdmin(admin.ModelAdmin):
    list_display = ['name', 'job_type', 'status', 'tables_found', 'rows_converted', 'created_at']
    list_filter = ['job_type', 'status']
    search_fields = ['name']
