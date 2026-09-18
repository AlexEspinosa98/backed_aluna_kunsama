from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
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
]

# Hasta ahora ningún archivo subido se servía por URL pública (ver el comentario junto a MEDIA_URL
# en config/settings.py): todos los FileField existentes solo los leía el propio backend para
# mandarlos a OpenAI. Las imágenes de infografía (InfografiaImagen) son las primeras que sí
# necesita ver/descargar el frontend. `static()` únicamente sirve `/media/` cuando DEBUG=True — en
# producción falta decidir cómo se expone (nginx, whitenoise o un bucket S3 vía django-storages),
# eso queda fuera del alcance de este cambio.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
