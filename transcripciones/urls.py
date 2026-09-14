from rest_framework.routers import DefaultRouter

from .views import (
    FragmentoTranscripcionAdminViewSet, InformeTranscripcionAdminViewSet,
    SesionTranscripcionAdminViewSet,
)

router = DefaultRouter()
router.register('transcripciones', SesionTranscripcionAdminViewSet, basename='admin-transcripcion')
router.register(
    'transcripcion-fragmentos', FragmentoTranscripcionAdminViewSet, basename='admin-transcripcion-fragmento'
)
router.register(
    'transcripcion-informes', InformeTranscripcionAdminViewSet, basename='admin-transcripcion-informe'
)

urlpatterns = router.urls
