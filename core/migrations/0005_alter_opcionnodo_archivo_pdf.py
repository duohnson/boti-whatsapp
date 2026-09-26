import core.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_empresa_ia_desde_primer_mensaje_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='opcionnodo',
            name='archivo_pdf',
            field=models.FileField(blank=True, upload_to='documentos_bot/', validators=[django.core.validators.FileExtensionValidator(['pdf']), core.models.validar_pdf]),
        ),
    ]
