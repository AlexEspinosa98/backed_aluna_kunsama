"""La infografía puede ser de UN momento, no solo de la jornada completa.

`momento` es nullable y no necesita rellenarse: null significa "infografía de jornada", que es lo
que eran todas las filas existentes. `jornada` se conserva obligatoria en ambos casos —para las de
momento se deriva de `momento.jornada`— porque es el campo sobre el que se apoya el scoping por
propietario.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('jornadas', '0001_initial'),
        ('analitica', '0012_infografia_cuelga_de_jornada'),
    ]

    operations = [
        migrations.AddField(
            model_name='infografiajornada',
            name='momento',
            field=models.ForeignKey(
                blank=True,
                help_text='Solo si la infografía es de UN momento. Null = es de la jornada completa.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='infografias',
                to='jornadas.momento',
            ),
        ),
    ]
