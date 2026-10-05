from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("studio", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="generation",
            name="backend",
            field=models.CharField(default="comfy", max_length=12),
        ),
        migrations.AddField(
            model_name="generation",
            name="remote_job_id",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
