from django.contrib import admin

from .models import FragmentoTranscripcion, InformeTranscripcion, SesionTranscripcion


class FragmentoTranscripcionInline(admin.TabularInline):
    model = FragmentoTranscripcion
    extra = 0
    ordering = ['secuencia']


@admin.register(SesionTranscripcion)
class SesionTranscripcionAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'estado', 'encargados_display', 'creado_en']
    list_filter = ['estado', 'encargados']
    filter_horizontal = ['encargados']
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [FragmentoTranscripcionInline]

    @admin.display(description='Encargados')
    def encargados_display(self, obj):
        return ', '.join(str(u) for u in obj.encargados.all()) or '—'


@admin.register(InformeTranscripcion)
class InformeTranscripcionAdmin(admin.ModelAdmin):
    list_display = ['sesion', 'estado', 'presentacion_estado', 'completado_en']
    list_filter = ['estado', 'presentacion_estado']
