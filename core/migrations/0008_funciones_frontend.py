import datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_empresa_limite_respuestas_ia_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='bienvenida',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='empresa',
            name='derivar_auto',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='empresa',
            name='despedida',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='empresa',
            name='fuera_horario',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='empresa',
            name='horario_fin',
            field=models.TimeField(default=datetime.time(17, 0)),
        ),
        migrations.AddField(
            model_name='empresa',
            name='horario_inicio',
            field=models.TimeField(default=datetime.time(8, 0)),
        ),
        migrations.AddField(
            model_name='empresa',
            name='idioma',
            field=models.CharField(choices=[('es', 'Español'), ('en', 'Inglés'), ('pt', 'Portugués')], default='es', max_length=5),
        ),
        migrations.AddField(
            model_name='empresa',
            name='mensaje_fuera_horario',
            field=models.TextField(default='Estamos fuera de horario. Te responderemos cuando volvamos.'),
        ),
        migrations.AddField(
            model_name='empresa',
            name='palabras_clave',
            field=models.CharField(blank=True, default='persona, agente, humano', max_length=500),
        ),
        migrations.AddField(
            model_name='empresa',
            name='tono',
            field=models.CharField(choices=[('neutral', 'Neutral'), ('cercano', 'Cercano'), ('formal', 'Formal')], default='neutral', max_length=12),
        ),
        migrations.AddField(
            model_name='empresa',
            name='zona_horaria',
            field=models.CharField(default='America/Costa_Rica', max_length=64),
        ),
        migrations.AddField(
            model_name='sesionwhatsapp',
            name='codigo_manual',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AlterField(
            model_name='sesionwhatsapp',
            name='estado',
            field=models.CharField(choices=[('desconectado', 'Desconectado'), ('esperando_qr', 'Esperando QR'), ('esperando_codigo', 'Esperando código manual'), ('conectado', 'Conectado'), ('autenticando', 'Autenticando'), ('error', 'Error')], default='desconectado', max_length=20),
        ),
    ]
