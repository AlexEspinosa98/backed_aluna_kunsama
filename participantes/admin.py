from django.contrib import admin

from .models import Participante, Respuesta


@admin.register(Participante)
class ParticipanteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'apellido', 'correo_institucional', 'jornada', 'telefono', 'creado_en']
    list_filter = ['jornada']
    search_fields = ['nombre', 'apellido', 'correo_institucional']


@admin.register(Respuesta)
class RespuestaAdmin(admin.ModelAdmin):
    list_display = ['pregunta', 'participante', 'mesa', 'actualizado_en']
    list_filter = ['pregunta__momento__jornada', 'pregunta__momento']
