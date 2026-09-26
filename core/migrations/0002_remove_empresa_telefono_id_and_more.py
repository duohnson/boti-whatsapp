import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name='empresa',
            name='telefono_id',
        ),
        migrations.RemoveField(
            model_name='empresa',
            name='token_acceso',
        ),
        migrations.RemoveField(
            model_name='empresa',
            name='waba_id',
        ),
        migrations.AddField(
            model_name='empresa',
            name='propietario',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='empresa_whatsapp', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='sesionusuario',
            name='empresa',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='sesiones_chat', to='core.empresa'),
        ),
        migrations.AlterField(
            model_name='empresa',
            name='prompt_sistema_ia',
            field=models.TextField(default='Eres un asistente virtual'),
        ),
        migrations.CreateModel(
            name='SesionWhatsApp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('numero_telefono', models.CharField(blank=True, max_length=32)),
                ('estado', models.CharField(choices=[('desconectado', 'Desconectado'), ('esperando_qr', 'Esperando QR'), ('conectado', 'Conectado'), ('autenticando', 'Autenticando'), ('error', 'Error')], default='desconectado', max_length=20)),
                ('codigo_qr', models.TextField(blank=True)),
                ('fecha_conexion', models.DateTimeField(blank=True, null=True)),
                ('ultima_actividad', models.DateTimeField(blank=True, null=True)),
                ('empresa', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sesion_whatsapp', to='core.empresa')),
            ],
        ),
    ]
