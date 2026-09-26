from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_alter_opcionnodo_archivo_pdf'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='historialchat',
            name='mensaje_whatsapp_entrante_unico',
        ),
        migrations.AddConstraint(
            model_name='historialchat',
            constraint=models.UniqueConstraint(condition=models.Q(('identificador_mensaje', ''), _negated=True), fields=('sesion_usuario', 'identificador_mensaje'), name='mensaje_whatsapp_entrante_unico'),
        ),
    ]
