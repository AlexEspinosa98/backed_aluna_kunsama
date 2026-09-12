from django.contrib import admin

from .models import (
    AplicacionInstrumento, ColumnaMatrizInstrumento, FilaMatrizInstrumento, Instrumento,
    OpcionPreguntaInstrumento, PreguntaInstrumento, PreregistroInstrumento, RespuestaInstrumento,
    SeccionInstrumento,
)


class OpcionPreguntaInstrumentoInline(admin.TabularInline):
    model = OpcionPreguntaInstrumento
    extra = 1


class FilaMatrizInline(admin.TabularInline):
    model = FilaMatrizInstrumento
    extra = 1


class ColumnaMatrizInline(admin.TabularInline):
    model = ColumnaMatrizInstrumento
    extra = 1


class PreguntaInstrumentoInline(admin.StackedInline):
    model = PreguntaInstrumento
    extra = 1


class SeccionInstrumentoInline(admin.StackedInline):
    model = SeccionInstrumento
    extra = 1


@admin.register(Instrumento)
class InstrumentoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'activo', 'encargados_display']
    list_filter = ['activo', 'encargados']
    filter_horizontal = ['encargados']
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [SeccionInstrumentoInline]

    @admin.display(description='Encargados')
    def encargados_display(self, obj):
        return ', '.join(str(u) for u in obj.encargados.all()) or '—'


@admin.register(SeccionInstrumento)
class SeccionInstrumentoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'instrumento', 'orden', 'tipo', 'activa']
    list_filter = ['instrumento', 'tipo']
    inlines = [PreguntaInstrumentoInline]


@admin.register(PreguntaInstrumento)
class PreguntaInstrumentoAdmin(admin.ModelAdmin):
    list_display = ['texto', 'seccion', 'tipo', 'orden', 'obligatoria']
    list_filter = ['seccion__instrumento', 'tipo']
    inlines = [OpcionPreguntaInstrumentoInline, FilaMatrizInline, ColumnaMatrizInline]


@admin.register(PreregistroInstrumento)
class PreregistroInstrumentoAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'instrumento', 'creado_por', 'creado_en']
    list_filter = ['instrumento']


@admin.register(AplicacionInstrumento)
class AplicacionInstrumentoAdmin(admin.ModelAdmin):
    list_display = ['preregistro', 'estado_visible', 'enviado_en', 'revisado_por', 'revisado_en']
    list_filter = ['estado']


admin.site.register(RespuestaInstrumento)
