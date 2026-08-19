# Segundo paso, en su propia transacción — ver el comentario en 0003_reporte_slug.py.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analitica', '0003_reporte_slug'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reporte',
            name='slug',
            field=models.SlugField(blank=True, help_text='Autogenerado: jornada + alcance + fecha/hora local de Colombia — para poder distinguir reportes a simple vista, no solo por id.', max_length=250, unique=True),
        ),
    ]
