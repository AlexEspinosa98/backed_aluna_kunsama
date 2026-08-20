from rest_framework.routers import DefaultRouter

from .admin_views import AnalisisMomentoIAViewSet, PlantillaAnalisisViewSet, ReporteViewSet

router = DefaultRouter()
router.register('plantillas-analisis', PlantillaAnalisisViewSet, basename='admin-plantilla-analisis')
router.register('reportes', ReporteViewSet, basename='admin-reporte')
router.register('analisis-momento-ia', AnalisisMomentoIAViewSet, basename='admin-analisis-momento-ia')

urlpatterns = router.urls
