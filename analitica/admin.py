from django.contrib import admin, messages
from django.shortcuts import redirect

from .models import AnalisisV2, PlantillaAnalisis, PresentacionDiseno, Reporte, SystemPrompt


@admin.register(SystemPrompt)
class SystemPromptAdmin(admin.ModelAdmin):
    """Mismas reglas que la API (HU-92): una versión que ya estuvo activa es de solo lectura y no
    se borra; un borrador se edita libremente. Activar y partir de una versión existente son
    acciones de la lista (marcar la versión → elegir la acción)."""
    list_display = ['tipo', 'version', 'etiqueta', 'activo', 'inmutable', 'activado_en', 'creado_por']
    list_filter = ['tipo', 'activo']
    list_display_links = ['tipo', 'version']
    search_fields = ['etiqueta', 'notas', 'contenido']
    fields = ['tipo', 'version', 'etiqueta', 'notas', 'contenido', 'activo', 'activado_en',
              'activado_por', 'creado_por', 'creado_en']
    readonly_fields = ['version', 'activo', 'activado_en', 'activado_por', 'creado_por', 'creado_en']
    actions = ['activar_version', 'nueva_version_desde_esta']

    @admin.display(boolean=True, description='Inmutable')
    def inmutable(self, obj):
        return obj.inmutable

    def get_readonly_fields(self, request, obj=None):
        if obj is not None and obj.inmutable:
            return self.fields
        if obj is not None:
            # El tipo de un borrador tampoco cambia: sería otra numeración.
            return [*self.readonly_fields, 'tipo']
        return self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return obj is None or not obj.inmutable

    def get_actions(self, request):
        # El borrado masivo se saltaría la regla de inmutabilidad (borra con un queryset).
        acciones = super().get_actions(request)
        acciones.pop('delete_selected', None)
        return acciones

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description='Activar la versión seleccionada (una por tipo)')
    def activar_version(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Selecciona exactamente una versión para activar.', messages.ERROR)
            return
        prompt = queryset.get().activar(request.user)
        self.message_user(
            request, f'{prompt.referencia} quedó activa: los próximos {prompt.get_tipo_display().lower()} la usan.',
            messages.SUCCESS,
        )

    @admin.action(description='Crear una versión nueva a partir de la seleccionada')
    def nueva_version_desde_esta(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Selecciona exactamente una versión.', messages.ERROR)
            return
        base = queryset.get()
        nueva = SystemPrompt.objects.create(
            tipo=base.tipo, contenido=base.contenido, creado_por=request.user,
            notas=f'Basada en {base.referencia}.',
        )
        self.message_user(
            request, f'Se creó el borrador {nueva.referencia}: edítalo y actívalo cuando esté listo.',
            messages.SUCCESS,
        )
        return redirect('admin:analitica_systemprompt_change', nueva.pk)


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


@admin.register(PresentacionDiseno)
class PresentacionDisenoAdmin(admin.ModelAdmin):
    list_display = ['id', '__str__', 'modelo', 'creado', 'actualizado']
    readonly_fields = ['diseno', 'diapositivas', 'correcciones', 'assets', 'modelo']
