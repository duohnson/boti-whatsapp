from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_operacion_bot'),
    ]

    operations = [
        migrations.AddField(
            model_name='historialchat',
            name='adjunto_entrega',
            field=models.FileField(blank=True, upload_to='pdfs/'),
        ),
    ]
