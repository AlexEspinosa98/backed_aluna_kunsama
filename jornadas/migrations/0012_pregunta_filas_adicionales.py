from django.db import migrations, models


def encender_en_listas_existentes(apps, schema_editor):
    """Las preguntas tipo lista que ya existen siempre permitieron que quien responde agregara
    filas — es la definición del tipo. El campo nace en False para todas, así que hay que
    ponerlas en True o el flag que lee el front contradiría lo que esas preguntas ya hacen."""
    Pregunta = apps.get_model('jornadas', 'Pregunta')
    Pregunta.objects.filter(tipo='lista').update(filas_adicionales=True)


def apagar_en_listas_existentes(apps, schema_editor):
    Pregunta = apps.get_model('jornadas', 'Pregunta')
    Pregunta.objects.filter(tipo='lista').update(filas_adicionales=False)


class Migration(migrations.Migration):

    dependencies = [
        ('jornadas', '0011_alter_pregunta_tipo'),
    ]

    operations = [
        migrations.AddField(
            model_name='pregunta',
            name='filas_adicionales',
            field=models.BooleanField(default=False, help_text='Si quien responde puede agregar filas además de las definidas por el admin. Solo aplica a preguntas matriz (por defecto no) y lista (siempre sí).'),
        ),
        migrations.RunPython(encender_en_listas_existentes, apagar_en_listas_existentes),
    ]
