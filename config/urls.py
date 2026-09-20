from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token

from .media_views import servir_media_publica
from .views import healthcheck

urlpatterns = [
    # Sin `/api/` a propósito: se pide poder confirmar que el servidor funciona entrando directo
    # a la URL base del dominio (ver config/views.py), sin tener que recordar ninguna ruta de la
    # API ni autenticarse.
    path('', healthcheck, name='healthcheck'),
    path('admin/', admin.site.urls),
    path('api/admin/login/', obtain_auth_token, name='admin-login'),
    path('api/admin/', include('jornadas.urls')),
    path('api/admin/', include('analitica.urls')),
    path('api/admin/', include('instrumentos.urls')),
    path('api/admin/', include('transcripciones.urls')),
    path('api/', include('participantes.urls')),
    path('api/', include('instrumentos.urls_participante')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # Los assets de marca y las infografías generadas son los primeros archivos subidos que el
    # frontend necesita VER por URL (el resto de `media/` solo lo lee el backend para mandarlo a
    # OpenAI). Se sirven desde Django y no desde nginx porque este despliegue no tiene un `alias`
    # para /media/ y agregarlo requiere root — ver config/media_views.py, que restringe qué se
    # expone. Va sin depender de DEBUG: en producción es justamente donde hace falta.
    re_path(r'^media/(?P<path>.*)$', servir_media_publica, name='media-publica'),
]
