from django.contrib import admin

from .models import PlantillaAnalisis, Reporte


@admin.register(PlantillaAnalisis)
class PlantillaAnalisisAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'predeterminada', 'creada_por', 'actualizado_en']
    list_filter = ['predeterminada']


@admin.register(Reporte)
class ReporteAdmin(admin.ModelAdmin):
    list_display = ['id', 'jornada', 'alcance', 'estado', 'plantilla', 'creado_en']
    list_filter = ['jornada', 'alcance', 'estado']
    readonly_fields = [
        'estadisticas', 'topicos', 'texto_reporte', 'modelo_usado', 'error_mensaje', 'completado_en',
    ]
