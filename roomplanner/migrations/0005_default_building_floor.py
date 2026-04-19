from django.db import migrations


def populate_default_building(apps, schema_editor):
    Building = apps.get_model('roomplanner', 'Building')
    Floor = apps.get_model('roomplanner', 'Floor')
    Room = apps.get_model('roomplanner', 'Room')

    orphans = list(Room.objects.filter(floor__isnull=True))
    if not orphans:
        return

    building, _ = Building.objects.get_or_create(
        slug='default-building',
        defaults={
            'name': 'Unassigned',
            'notes': (
                'Auto-created when multi-floor support landed. Move '
                'rooms into their real building/floor from the admin.'
            ),
        },
    )
    floor, _ = Floor.objects.get_or_create(
        building=building, level=0,
        defaults={'name': 'Ground floor'},
    )
    for r in orphans:
        r.floor = floor
        r.save(update_fields=['floor'])


def reverse(apps, schema_editor):
    # Non-destructive: leave the default building in place; clearing
    # Room.floor is a schema-level operation handled by the previous
    # migration if it gets reverted.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('roomplanner', '0004_building_floor_room_floor'),
    ]

    operations = [
        migrations.RunPython(populate_default_building, reverse),
    ]
