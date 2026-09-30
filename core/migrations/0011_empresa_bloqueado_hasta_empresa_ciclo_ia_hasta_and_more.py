import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_historialchat_adjunto_entrega'),
    ]

    operations = [
        migrations.AddField(
            model_name='empresa',
            name='bloqueado_hasta',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='empresa',
            name='ciclo_ia_hasta',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='empresa',
            name='plan',
            field=models.CharField(choices=[('gratis', 'Gratuito'), ('premium', 'Premium'), ('corporativo', 'Corporativo')], default='gratis', max_length=16),
        ),
        migrations.AddField(
            model_name='empresa',
            name='plan_hasta',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='empresa',
            name='respuestas_gratis',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='empresa',
            name='respuestas_totales',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='PagoPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identificador', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('orden_paypal', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('captura_paypal', models.CharField(blank=True, max_length=128, null=True, unique=True)),
                ('plan', models.CharField(choices=[('premium', 'Premium'), ('corporativo', 'Corporativo')], max_length=16)),
                ('periodo', models.CharField(max_length=16)),
                ('importe', models.DecimalField(decimal_places=2, max_digits=8)),
                ('moneda', models.CharField(default='USD', max_length=3)),
                ('estado', models.CharField(choices=[('pendiente', 'Pendiente'), ('completado', 'Completado'), ('revisar', 'Revisar')], default='pendiente', max_length=16)),
                ('medio', models.CharField(default='paypal', max_length=16)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('inicio', models.DateTimeField(blank=True, null=True)),
                ('fin', models.DateTimeField(blank=True, null=True)),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.empresa')),
            ],
        ),
    ]
