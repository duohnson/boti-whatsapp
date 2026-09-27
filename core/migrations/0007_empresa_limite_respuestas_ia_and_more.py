from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_remove_historialchat_mensaje_whatsapp_entrante_unico_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='limite_respuestas_ia',
            field=models.PositiveIntegerField(default=100),
        ),
        migrations.AddField(
            model_name='empresa',
            name='respuestas_ia_utilizadas',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name='ciclofacturacion',
            constraint=models.UniqueConstraint(fields=('empresa', 'mes', 'anio'), name='ciclo_ia_empresa_mes_unico'),
        ),
    ]