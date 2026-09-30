from django.db import migrations, models


def ajustar_cupos(apps, schema_editor):
    empresas = apps.get_model('core', 'Empresa').objects.using(schema_editor.connection.alias)
    empresas.filter(plan='corporativo').update(limite_respuestas_ia=1000)
    empresas.exclude(plan='corporativo').update(limite_respuestas_ia=0)


class Migration(migrations.Migration):
    dependencies = [('core', '0014_limiteacceso_codigocorreo_perfilusuario_avisoplan')]

    operations = [
        migrations.AlterField(
            model_name='empresa', name='limite_respuestas_ia',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(ajustar_cupos, migrations.RunPython.noop),
    ]
