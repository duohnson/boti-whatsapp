import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def identificar_historial(apps, schema_editor):
    historial = apps.get_model('core', 'HistorialChat')
    for mensaje in historial.objects.using(schema_editor.connection.alias).all().iterator():
        mensaje.id_envio = uuid.uuid4()
        if mensaje.rol != 'user':
            mensaje.estado_entrega = 'historico'
        mensaje.save(update_fields=['id_envio', 'estado_entrega'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_funciones_frontend'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='accion_limite_ia',
            field=models.CharField(choices=[('aviso', 'Mostrar aviso'), ('humano', 'Pasar a una persona')], default='aviso', max_length=10),
        ),
        migrations.AddField(
            model_name='empresa',
            name='max_mensajes_ia',
            field=models.PositiveSmallIntegerField(default=20, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(50)]),
        ),
        migrations.AddField(
            model_name='empresa',
            name='mensaje_limite_ia',
            field=models.TextField(default='Se alcanzó el límite de respuestas de IA para esta cuenta.'),
        ),
        migrations.AddField(
            model_name='empresa',
            name='reabrir_conversaciones',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='error_entrega',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='estado_entrega',
            field=models.CharField(choices=[('recibido', 'Recibido'), ('historico', 'Sin estado anterior'), ('generado', 'Generado'), ('enviando', 'Enviando'), ('enviado', 'Enviado'), ('fallido', 'Fallido'), ('incierto', 'Sin confirmación')], default='recibido', max_length=12),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='id_envio',
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(identificar_historial, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='historialchat',
            name='id_envio',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='intento_entrega',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='opcion_pdf',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.opcionnodo'),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='respuesta_a',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='respuestas', to='core.historialchat'),
        ),
        migrations.AddField(
            model_name='sesionusuario',
            name='asignado_a',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='sesionusuario',
            name='destino_chat',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.CreateModel(
            name='AgenteEmpresa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agentes', to='core.empresa')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('empresa', 'usuario'), name='agente_empresa_unico')],
            },
        ),
    ]
