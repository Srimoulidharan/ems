from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ems', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='leaverequest',
            name='approved_on',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
