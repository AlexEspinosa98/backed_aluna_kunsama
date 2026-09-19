# Migración de datos (D7-A): separada de 0016 (esquema) para poder revertir el backfill sin
# tocar los campos nuevos — ver docs/banco_instrumentos/03_modelo_de_datos.md §2.
from django.db import migrations


def backfill_creado_por(apps, schema_editor):
    """Los momentos existentes no tienen creador propio: se les atribuye quien creó la jornada,
    si existe, o se dejan en null. Es SOLO atribución (D3-A: el acceso sigue yendo por
    jornada.propietarios, no por creado_por), así que este backfill no cambia qué puede ver o
    editar nadie — solo lo que se muestra en el banco como "creado por"."""
    Momento = apps.get_model('jornadas', 'Momento')
    for momento in Momento.objects.select_related('jornada').iterator():
        if momento.jornada.creada_por_id:
            momento.creado_por_id = momento.jornada.creada_por_id
            momento.save(update_fields=['creado_por'])


def revertir_backfill(apps, schema_editor):
    """No-op a propósito: revertir no debe borrar una atribución que ya pudo haber sido
    corregida a mano después de aplicar esta migración — el campo lo sigue teniendo 0016."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('jornadas', '0016_momento_banco'),
    ]

    operations = [
        migrations.RunPython(backfill_creado_por, revertir_backfill),
    ]
