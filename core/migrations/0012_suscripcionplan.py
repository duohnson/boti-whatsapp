import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_empresa_bloqueado_hasta_empresa_ciclo_ia_hasta_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SuscripcionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('paypal_id', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('paypal_plan', models.CharField(max_length=128)),
                ('plan', models.CharField(max_length=16)),
                ('periodo', models.CharField(max_length=16)),
                ('importe', models.DecimalField(decimal_places=2, max_digits=8)),
                ('estado', models.CharField(default='pendiente', max_length=24)),
                ('aprobacion', models.URLField(blank=True, max_length=1000)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.empresa')),
            ],
            options={
                'constraints': [models.UniqueConstraint(condition=models.Q(('estado__in', ['pendiente', 'activo', 'suspendido'])), fields=('empresa',), name='una_suscripcion_vigente_empresa')],
            },
        ),
    ]
