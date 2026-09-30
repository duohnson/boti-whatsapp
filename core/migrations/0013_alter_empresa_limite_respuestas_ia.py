from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_suscripcionplan'),
    ]

    operations = [
        migrations.AlterField(
            model_name='empresa',
            name='limite_respuestas_ia',
            field=models.PositiveIntegerField(default=50),
        ),
    ]
