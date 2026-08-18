from django.contrib import admin
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/admin/login/', obtain_auth_token, name='admin-login'),
    path('api/admin/', include('jornadas.urls')),
    path('api/', include('participantes.urls')),
]
