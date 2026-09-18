from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jornadas', '0010_alter_pregunta_tipo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pregunta',
            name='tipo',
            field=models.CharField(choices=[('abierta', 'Abierta'), ('unica', 'Selección única'), ('multiple', 'Selección múltiple'), ('matriz', 'Matriz comparativa (filas × columnas, cantidad fija)'), ('lista', 'Lista de registros (columnas fijas, filas las agrega quien responde)'), ('audio', 'Audio (el cliente transcribe; se guarda solo el texto)')], max_length=20),
        ),
    ]
