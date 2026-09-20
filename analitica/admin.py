from django.contrib import admin

from .models import AnalisisV2, PlantillaAnalisis, Reporte


@admin.register(PlantillaAnalisis)
class PlantillaAnalisisAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'predeterminada', 'creada_por', 'actualizado_en']
    list_filter = ['predeterminada']


@admin.register(Reporte)
class ReporteAdmin(admin.ModelAdmin):
    list_display = ['id', 'jornada', 'alcance', 'estado', 'plantilla', 'creado_en']
    list_filter = ['jornada', 'alcance', 'estado']
    readonly_fields = [
        'analisis', 'texto_reporte', 'modelo_usado', 'error_mensaje', 'completado_en',
    ]


@admin.register(AnalisisV2)
class AnalisisV2Admin(admin.ModelAdmin):
    list_display = ['id', 'jornada', 'modo', 'pipeline', 'estado', 'creado_en', 'completado_en']
    list_filter = ['modo', 'pipeline', 'estado']
    readonly_fields = [
        'entrada', 'resultado', 'diagnostico', 'prompt_usado', 'modelo_usado', 'error_mensaje',
        'version_prompt', 'version_esquema', 'completado_en',
    ]
