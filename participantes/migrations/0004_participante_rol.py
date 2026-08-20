from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('participantes', '0003_mesa_numerica'),
    ]

    operations = [
        migrations.AddField(
            model_name='participante',
            name='rol',
            # Valor único para las filas ya existentes (datos de prueba) — los registros nuevos
            # exigen `rol` de verdad porque el serializer de registro no manda default y el campo
            # no tiene blank=True.
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
    ]
