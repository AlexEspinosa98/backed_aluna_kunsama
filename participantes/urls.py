from django.urls import path

from .views import (
    JornadaDetalleView,
    JornadaListaView,
    LoginParticipanteView,
    MomentoDetalleView,
    MomentosIndiceView,
    RegistroParticipanteView,
    RespuestasMomentoView,
)

urlpatterns = [
    path('jornadas/', JornadaListaView.as_view(), name='jornada-lista'),
    path('jornadas/<slug:jornada_slug>/', JornadaDetalleView.as_view(), name='jornada-detalle'),
    path('jornadas/<slug:jornada_slug>/registro/', RegistroParticipanteView.as_view(), name='jornada-registro'),
    path('jornadas/<slug:jornada_slug>/login/', LoginParticipanteView.as_view(), name='jornada-login'),
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
]
