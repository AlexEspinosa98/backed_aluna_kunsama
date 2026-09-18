"""Instrucciones libres por corrida de infografía.

Campo de texto opcional: vacío es el comportamiento de siempre, así que las filas existentes no
necesitan rellenarse ni cambian de comportamiento.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analitica', '0013_infografiajornada_momento'),
    ]

    operations = [
        migrations.AddField(
            model_name='infografiajornada',
            name='instrucciones',
            field=models.TextField(
                blank=True,
                help_text=(
                    'Instrucciones libres que se integran al prompt de esta corrida, con '
                    'precedencia sobre el estilo y la estructura por defecto. Sirven para cambiar '
                    'el tono, la composición o qué información aparece en las láminas, sin tocar '
                    'código. Por corrida y no por jornada a propósito: se prueban distintas y se '
                    'compara el resultado contra `prompt_usado`.'
                ),
            ),
        ),
    ]
