from django.contrib import admin

from .models import Database


@admin.register(Database)
class DatabaseAdmin(admin.ModelAdmin):
    list_display = ('nickname', 'engine', 'host', 'port', 'database_name',
                    'last_test_status', 'last_tested_at')
    list_filter = ('engine', 'last_test_status')
    search_fields = ('nickname', 'host', 'database_name')
