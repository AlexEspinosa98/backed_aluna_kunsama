from django.urls import path

from .views import (
    JornadaDetalleView,
    JornadaListaView,
    LoginParticipanteView,
    MeParticipanteView,
    MisExtraccionesMomentoView,
    MomentoCargarArchivoView,
    MomentoDetalleView,
    MomentosIndiceView,
    RegistroParticipanteView,
    RespuestasMomentoView,
    RolesJornadaView,
)

urlpatterns = [
    path('jornadas/', JornadaListaView.as_view(), name='jornada-lista'),
    path('jornadas/<slug:jornada_slug>/', JornadaDetalleView.as_view(), name='jornada-detalle'),
    path('jornadas/<slug:jornada_slug>/roles/', RolesJornadaView.as_view(), name='jornada-roles'),
    path('jornadas/<slug:jornada_slug>/registro/', RegistroParticipanteView.as_view(), name='jornada-registro'),
    path('jornadas/<slug:jornada_slug>/login/', LoginParticipanteView.as_view(), name='jornada-login'),
    path('jornadas/<slug:jornada_slug>/me/', MeParticipanteView.as_view(), name='jornada-me'),
    path('jornadas/<slug:jornada_slug>/momentos/', MomentosIndiceView.as_view(), name='momentos-indice'),
    path(
        'jornadas/<slug:jornada_slug>/momentos/<int:momento_id>/',
        MomentoDetalleView.as_view(),
        name='momento-detalle',
    ),
    path(
        'jornadas/<slug:jornada_slug>/momentos/<int:momento_id>/respuestas/',
        RespuestasMomentoView.as_view(),
        name='momento-respuestas',
    ),
    # Carga de un documento ya diligenciado por el propio participante (HU-56) — solo si el
    # momento tiene permite_carga_archivo encendido.
    path(
        'jornadas/<slug:jornada_slug>/momentos/<int:momento_id>/cargar-archivo/',
        MomentoCargarArchivoView.as_view(),
        name='momento-cargar-archivo',
    ),
    path(
        'jornadas/<slug:jornada_slug>/momentos/<int:momento_id>/mis-cargas/',
        MisExtraccionesMomentoView.as_view(),
        name='momento-mis-cargas',
    ),
]
