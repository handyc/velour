from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('nodes', '0004_firmware'),
    ]

    operations = [
        migrations.AddField(
            model_name='node',
            name='self_registered',
            field=models.BooleanField(
                default=False,
                help_text='True if this node was created via /api/nodes/register '
                          'rather than the admin UI. Useful for spotting '
                          'auto-provisioned fleet members in the node list.',
            ),
        ),
    ]
