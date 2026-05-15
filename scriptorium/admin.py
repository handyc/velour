from django.contrib import admin

from .models import PhilologyProject, SyncRun


@admin.register(PhilologyProject)
class PhilologyProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'kind', 'remote_host', 'updated_at')
    list_filter = ('kind',)
    search_fields = ('name', 'slug', 'remote_host', 'local_path')
    prepopulated_fields = {'slug': ('name',)}
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'kind', 'description')}),
        ('Local checkout', {'fields': (
            'local_path', 'venv_python', 'django_settings_module',
            'db_filename', 'local_backup_dir',
        )}),
        ('Data drops', {'fields': (
            'data_dir_glob', 'data_files_dir_env', 'ingest_command',
        )}),
        ('Remote / staging', {'fields': (
            'remote_host', 'remote_user', 'remote_path', 'remote_python',
            'ssh_key_path', 'deploy_script', 'public_url',
        )}),
    )


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'project', 'op', 'status', 'exit_code', 'data_dir')
    list_filter = ('op', 'status', 'project')
    readonly_fields = (
        'project', 'op', 'status', 'started_at', 'finished_at',
        'data_dir', 'exit_code', 'stdout', 'stderr', 'summary',
        'backup_path', 'triggered_by',
    )
    search_fields = ('data_dir',)
    date_hierarchy = 'started_at'
