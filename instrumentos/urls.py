from rest_framework.routers import DefaultRouter

from .views import (
    AplicacionInstrumentoAdminViewSet, ColumnaMatrizAdminViewSet, FilaMatrizAdminViewSet,
    InstrumentoAdminViewSet, OpcionInstrumentoAdminViewSet, PreguntaInstrumentoAdminViewSet,
    PreregistroInstrumentoAdminViewSet, SeccionInstrumentoAdminViewSet,
)

router = DefaultRouter()
router.register('instrumentos', InstrumentoAdminViewSet, basename='admin-instrumento')
router.register('instrumento-secciones', SeccionInstrumentoAdminViewSet, basename='admin-instrumento-seccion')
router.register('instrumento-preguntas', PreguntaInstrumentoAdminViewSet, basename='admin-instrumento-pregunta')
router.register('instrumento-opciones', OpcionInstrumentoAdminViewSet, basename='admin-instrumento-opcion')
router.register('instrumento-filas-matriz', FilaMatrizAdminViewSet, basename='admin-instrumento-fila')
router.register('instrumento-columnas-matriz', ColumnaMatrizAdminViewSet, basename='admin-instrumento-columna')
router.register(
    'instrumento-preregistrados', PreregistroInstrumentoAdminViewSet, basename='admin-instrumento-preregistro'
)
router.register(
    'instrumento-aplicaciones', AplicacionInstrumentoAdminViewSet, basename='admin-instrumento-aplicacion'
)

urlpatterns = router.urls
