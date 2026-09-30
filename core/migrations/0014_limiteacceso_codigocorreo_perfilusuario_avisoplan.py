import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_alter_empresa_limite_respuestas_ia'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LimiteAcceso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('clave', models.CharField(max_length=64, unique=True)),
                ('inicio', models.DateTimeField()),
                ('intentos', models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='CodigoCorreo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('correo', models.EmailField(max_length=254)),
                ('proposito', models.CharField(max_length=20)),
                ('huella', models.CharField(max_length=64)),
                ('vinculo', models.CharField(max_length=64)),
                ('datos', models.JSONField(default=dict)),
                ('intentos', models.PositiveSmallIntegerField(default=0)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('vence', models.DateTimeField()),
                ('usado', models.BooleanField(default=False)),
                ('usuario', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='PerfilUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('correo_verificado', models.EmailField(blank=True, max_length=254, null=True, unique=True)),
                ('telefono', models.CharField(blank=True, max_length=30)),
                ('ubicacion', models.CharField(blank=True, max_length=200)),
                ('organizacion', models.CharField(blank=True, max_length=150)),
                ('cedula_juridica', models.CharField(blank=True, max_length=60)),
                ('codigo_postal', models.CharField(blank=True, max_length=20)),
                ('pais', models.CharField(blank=True, max_length=80)),
                ('direccion', models.CharField(blank=True, max_length=250)),
                ('usuario', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='perfil_boti', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='AvisoPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('vencimiento', models.DateTimeField()),
                ('estado', models.CharField(default='pendiente', max_length=16)),
                ('enviado', models.DateTimeField(blank=True, null=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.empresa')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('empresa', 'vencimiento'), name='aviso_unico_periodo')],
            },
        ),
    ]
