"""La infografía pasa a colgar de la Jornada y el Reporte queda opcional.

Se hace en tres pasos en vez de agregar el FK obligatorio de una: si alguna base ya tiene
infografías creadas (la vía vieja exigía un reporte), un `AddField` no nulo sin default las
rompería. Acá se agrega nullable, se rellena desde `reporte.jornada` —que es justamente de dónde
salía la jornada antes— y recién entonces se vuelve obligatorio.
"""
from django.db import migrations, models
import django.db.models.deletion


def poblar_jornada_desde_reporte(apps, schema_editor):
    InfografiaJornada = apps.get_model('analitica', 'InfografiaJornada')
    for infografia in InfografiaJornada.objects.select_related('reporte').all():
        infografia.jornada_id = infografia.reporte.jornada_id
        infografia.save(update_fields=['jornada'])


def revertir(apps, schema_editor):
    # El camino de vuelta no pierde nada: `reporte` sigue ahí y era la fuente de la jornada.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('jornadas', '0001_initial'),
        ('analitica', '0011_infografiajornada_infografiaimagen'),
    ]

    operations = [
        migrations.AddField(
            model_name='infografiajornada',
            name='jornada',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='infografias',
                to='jornadas.jornada',
            ),
        ),
        migrations.RunPython(poblar_jornada_desde_reporte, revertir),
        migrations.AlterField(
            model_name='infografiajornada',
            name='jornada',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='infografias',
                to='jornadas.jornada',
            ),
        ),
        migrations.AlterField(
            model_name='infografiajornada',
            name='reporte',
            field=models.ForeignKey(
                blank=True,
                help_text='Solo si se disparó desde un reporte concreto. Borrarlo no borra la infografía.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='infografias',
                to='analitica.reporte',
            ),
        ),
    ]
