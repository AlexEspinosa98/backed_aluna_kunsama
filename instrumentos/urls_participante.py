from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from .views_participante import (
    InstrumentoDescargarPropioView,
    InstrumentoDetalleParticipanteView,
    InstrumentoListaAsignadosView,
    InstrumentoRespuestasView,
)

urlpatterns = [
    # Mismo obtain_auth_token que /api/admin/login/ — el preregistrado es un User Django normal,
    # solo que is_staff=False, así que no necesita lógica de auth propia (ver
    # instrumentos/permissions.py). Montado en su propia URL para no confundirlo con el login admin.
    path('instrumentos/login/', obtain_auth_token, name='instrumento-login'),
    path('instrumentos/', InstrumentoListaAsignadosView.as_view(), name='instrumento-lista'),
    path(
        'instrumentos/<slug:instrumento_slug>/',
        InstrumentoDetalleParticipanteView.as_view(),
        name='instrumento-detalle',
    ),
    path(
        'instrumentos/<slug:instrumento_slug>/respuestas/',
        InstrumentoRespuestasView.as_view(),
        name='instrumento-respuestas',
    ),
    path(
        'instrumentos/<slug:instrumento_slug>/descargar/',
        InstrumentoDescargarPropioView.as_view(),
        name='instrumento-descargar',
    ),
]
