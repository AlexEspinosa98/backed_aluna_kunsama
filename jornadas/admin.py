from django.contrib import admin

from .models import Jornada, Momento, OpcionPregunta, Pregunta


class OpcionPreguntaInline(admin.TabularInline):
    model = OpcionPregunta
    extra = 1


class PreguntaInline(admin.StackedInline):
    model = Pregunta
    extra = 1


class MomentoInline(admin.StackedInline):
    model = Momento
    extra = 1


@admin.register(Jornada)
class JornadaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'slug', 'fecha_inicio', 'fecha_fin', 'activa']
    prepopulated_fields = {'slug': ('nombre',)}
    inlines = [MomentoInline]


@admin.register(Momento)
class MomentoAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'jornada', 'orden', 'tipo', 'activo']
    list_filter = ['jornada', 'tipo']
    inlines = [PreguntaInline]


@admin.register(Pregunta)
class PreguntaAdmin(admin.ModelAdmin):
    list_display = ['texto', 'momento', 'tipo', 'orden', 'obligatoria']
    list_filter = ['momento__jornada', 'tipo']
    inlines = [OpcionPreguntaInline]
