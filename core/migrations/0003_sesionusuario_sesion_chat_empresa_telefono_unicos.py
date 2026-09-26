from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_remove_empresa_telefono_id_and_more'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='sesionusuario',
            constraint=models.UniqueConstraint(fields=('empresa', 'telefono_cliente'), name='sesion_chat_empresa_telefono_unicos'),
        ),
    ]
