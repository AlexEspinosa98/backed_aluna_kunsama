import json

from django.contrib import admin
from django.utils.html import format_html

from .models import LlamadaOpenAI


@admin.register(LlamadaOpenAI)
class LlamadaOpenAIAdmin(admin.ModelAdmin):
    """Registro de auditoría: solo lectura, sin alta, edición ni borrado desde el admin."""
    list_display = [
        'iniciado_en', 'flujo', 'endpoint', 'modelo', 'status_code', 'duracion_ms',
        'tokens_entrada', 'tokens_salida', 'jornada', 'origen_resumen', 'usuario',
    ]
    list_filter = ['flujo', 'estado', 'modelo', 'endpoint', 'jornada']
    search_fields = ['request_id', 'origen_id', 'error']
    date_hierarchy = 'iniciado_en'
    list_select_related = ['jornada', 'usuario', 'origen_tipo']
    readonly_fields = ['peticion_formateada', 'respuesta_formateada']
    exclude = ['peticion', 'respuesta', 'peticion_cruda']

    @admin.display(description='Origen')
    def origen_resumen(self, obj):
        if obj.origen_tipo_id is None:
            return '—'
        return f'{obj.origen_tipo.model} #{obj.origen_id}'

    def _json(self, valor):
        if valor is None:
            return '—'
        return format_html(
            '<pre style="white-space:pre-wrap;max-height:40em;overflow:auto">{}</pre>',
            json.dumps(valor, ensure_ascii=False, indent=2),
        )

    @admin.display(description='Petición (JSON)')
    def peticion_formateada(self, obj):
        if obj.peticion is None and obj.peticion_cruda:
            return f'(cuerpo no JSON, {obj.peticion_bytes} bytes — ver peticion_cruda en la base)'
        return self._json(obj.peticion)

    @admin.display(description='Respuesta (JSON)')
    def respuesta_formateada(self, obj):
        return self._json(obj.respuesta)

    def get_readonly_fields(self, request, obj=None):
        campos = [f.name for f in self.model._meta.fields if f.name not in self.exclude]
        return [*campos, *self.readonly_fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
