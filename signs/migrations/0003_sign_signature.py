from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('signs', '0002_reslug_signs')]
    operations = [
        migrations.AddField(
            model_name='sign',
            name='signature',
            field=models.JSONField(
                blank=True, null=True,
                help_text='K_SIGNATURE_KEYFRAMES × 90-float pose signature, '
                          'L2-normalised. Recomputed whenever frames change.'),
        ),
    ]
