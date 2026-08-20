from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import (
    AnalisisMomentoIAViewSet, EstadisticasPreguntasView, MesasView, PlantillaAnalisisViewSet,
    ProgresoParticipantesView, ReporteViewSet,
)

router = DefaultRouter()
router.register('plantillas-analisis', PlantillaAnalisisViewSet, basename='admin-plantilla-analisis')
router.register('reportes', ReporteViewSet, basename='admin-reporte')
router.register('analisis-momento-ia', AnalisisMomentoIAViewSet, basename='admin-analisis-momento-ia')

urlpatterns = router.urls + [
    path('estadisticas-preguntas/', EstadisticasPreguntasView.as_view(), name='admin-estadisticas-preguntas'),
    path('progreso-participantes/', ProgresoParticipantesView.as_view(), name='admin-progreso-participantes'),
    path('mesas/', MesasView.as_view(), name='admin-mesas'),
]
