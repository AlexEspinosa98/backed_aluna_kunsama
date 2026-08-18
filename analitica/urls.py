from rest_framework.routers import DefaultRouter

from .admin_views import PlantillaAnalisisViewSet, ReporteViewSet

router = DefaultRouter()
router.register('plantillas-analisis', PlantillaAnalisisViewSet, basename='admin-plantilla-analisis')
router.register('reportes', ReporteViewSet, basename='admin-reporte')

urlpatterns = router.urls
