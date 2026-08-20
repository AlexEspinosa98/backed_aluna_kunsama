"""Convierte `mesa` de texto libre ("Mesa 3") a número entero (3) en Participante y Respuesta.

Se hace en tres pasos porque no se puede castear directo un valor existente como '' o 'Mesa 3' a
integer en una sola operación de columna:
1. Se permite NULL en Participante.mesa sin cambiar el tipo todavía (Respuesta.mesa ya lo permitía).
2. Se normalizan los valores existentes como texto: '' -> NULL, 'Mesa 3' -> '3' (se extrae el
   primer número que aparezca en el texto).
3. Recién ahí se cambia el tipo de columna a entero — con los valores ya limpios, el cast es trivial.
"""
import re

from django.db import migrations, models


def normalizar_mesa_participante(apps, schema_editor):
    Participante = apps.get_model('participantes', 'Participante')
    for p in Participante.objects.exclude(mesa=None):
        match = re.search(r'\d+', p.mesa or '')
        Participante.objects.filter(pk=p.pk).update(mesa=match.group() if match else None)


def normalizar_mesa_respuesta(apps, schema_editor):
    Respuesta = apps.get_model('participantes', 'Respuesta')
    for r in Respuesta.objects.exclude(mesa=None):
        match = re.search(r'\d+', r.mesa or '')
        Respuesta.objects.filter(pk=r.pk).update(mesa=match.group() if match else None)


class Migration(migrations.Migration):

    dependencies = [
        ('participantes', '0002_participante_es_vocero_participante_mesa'),
    ]

    operations = [
        migrations.AlterField(
            model_name='participante',
            name='mesa',
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.RunPython(normalizar_mesa_participante, migrations.RunPython.noop),
        migrations.RunPython(normalizar_mesa_respuesta, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='participante',
            name='mesa',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name='respuesta',
            name='mesa',
            field=models.PositiveIntegerField(null=True, blank=True),
        ),
    ]
