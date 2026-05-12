# Hand-edited to use RenameModel for the corpuslab→sealedlex transition
# so existing session rows survive.  The original auto-generated migration
# did Create + Delete, which would drop the data.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('umbra', '0004_corpuslabsession_language_profile'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='CorpusLabSession',
            new_name='SealedLexSession',
        ),
        migrations.DeleteModel(
            name='CsvLabSession',
        ),
    ]
