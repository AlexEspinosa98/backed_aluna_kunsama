from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token

from .media_views import servir_media_publica
from .views import healthcheck

# Rutas reales de la app — se montan DOS VECES (ver `urlpatterns` abajo): en la raíz, y bajo
# `api/aluna-kunsama/` para calzar con producción, donde nginx recibe ese prefijo y lo QUITA antes
# de pasarle la petición a Django (ver docs/INTEGRACION_FRONTEND_INFOGRAFIA.md §1). Django mismo
# nunca ve ese prefijo en producción — ahí siempre llega la ruta ya limpia — así que doblar el
# montaje acá es inofensivo ahí (esa rama de rutas simplemente no se usa) y es lo que hace falta
# en un servidor de pruebas que no tiene ese nginx por delante: cualquier URL que el equipo
# copie/pegue desde producción (¡incluidas las de `media/`, que Django arma con `MEDIA_URL` y por
# eso SÍ llevan el prefijo bakeado!) resuelve igual acá, sin tener que mantener dos formas de
# construir una URL según el entorno.
_rutas = [
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

urlpatterns = _rutas + [
    # Único costo del doble montaje: el admin de Django (`{% url 'admin:...' %}`, usado solo
    # dentro de sus propias plantillas, nunca por la API) queda registrado dos veces bajo el
    # mismo namespace — sus enlaces internos apuntan siempre a la raíz, sin importar por cuál de
    # las dos rutas se haya entrado. Irrelevante para la API REST, que nunca usa `reverse()` sobre
    # el admin.
    path('api/aluna-kunsama/', include(_rutas)),
]
