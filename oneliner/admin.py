from django.contrib import admin

from .models import Oneliner


@admin.register(Oneliner)
class OnelinerAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'language', 'char_count', 'n_lines',
                    'last_status', 'last_binary_size')
    list_filter = ('language', 'last_status')
    search_fields = ('name', 'slug', 'purpose', 'code')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('last_status', 'last_compile_output',
                       'last_binary_size', 'last_run_stdout',
                       'last_run_exit', 'created_at', 'updated_at')
