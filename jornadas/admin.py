from django.contrib import admin

from .models import Jornada, Momento, OpcionPregunta, PerfilUsuario, Pregunta


class OpcionPreguntaInline(admin.TabularInline):
    model = OpcionPregunta
    extra = 1


class PreguntaInline(admin.StackedInline):
    model = Pregunta
    extra = 1


class MomentoInline(admin.StackedInline):
    model = Momento
    extra = 1


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ['user', 'rol']
    list_filter = ['rol']


@admin.register(Jornada)
class JornadaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'fecha_inicio', 'fecha_fin', 'activa', 'propietarios_display']
    list_filter = ['activa', 'propietarios']
    filter_horizontal = ['propietarios']
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [MomentoInline]

    @admin.display(description='Propietarios')
    def propietarios_display(self, obj):
        return ', '.join(str(u) for u in obj.propietarios.all()) or '—'


@admin.register(Momento)
class MomentoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'jornada', 'orden', 'tipo', 'mesas_permitidas', 'activo']
    list_filter = ['jornada', 'tipo']
    inlines = [PreguntaInline]


@admin.register(Pregunta)
class PreguntaAdmin(admin.ModelAdmin):
    list_display = ['texto', 'momento', 'tipo', 'orden', 'obligatoria', 'mesas_permitidas']
    list_filter = ['momento__jornada', 'tipo']
    inlines = [OpcionPreguntaInline]
