import core.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_sesionusuario_sesion_chat_empresa_telefono_unicos'),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='ia_desde_primer_mensaje',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='historialchat',
            name='identificador_mensaje',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='opcionnodo',
            name='archivo_pdf',
            field=models.FileField(blank=True, upload_to='documentos_bot/', validators=[core.models.validar_pdf]),
        ),
        migrations.AddField(
            model_name='opcionnodo',
            name='etiqueta',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='sesionusuario',
            name='estado',
            field=models.CharField(choices=[('bot', 'Bot'), ('humano', 'Atención humana'), ('cerrada', 'Cerrada')], default='bot', max_length=12),
        ),
        migrations.AlterField(
            model_name='historialchat',
            name='rol',
            field=models.CharField(choices=[('user', 'Usuario'), ('assistant', 'Asistente'), ('agent', 'Agente humano')], max_length=50),
        ),
        migrations.AlterField(
            model_name='nodobot',
            name='tipo_nodo',
            field=models.CharField(choices=[('MENU', 'Menu'), ('TEXT', 'Texto'), ('AI_AGENT', 'Agente IA'), ('HUMAN_AGENT', 'Atención humana'), ('END', 'Finalizar conversación')], max_length=50),
        ),
        migrations.AddConstraint(
            model_name='historialchat',
            constraint=models.UniqueConstraint(condition=models.Q(('identificador_mensaje', ''), _negated=True), fields=('identificador_mensaje',), name='mensaje_whatsapp_entrante_unico'),
        ),
        migrations.AddConstraint(
            model_name='nodobot',
            constraint=models.UniqueConstraint(condition=models.Q(('es_nodo_inicial', True)), fields=('empresa',), name='un_nodo_inicial_por_empresa'),
        ),
    ]
