from rest_framework.routers import DefaultRouter

from participantes.admin_views import ExtraccionMomentoViewSet, ParticipanteAdminViewSet, RespuestaAdminViewSet

from .views import (
    ColumnaMatrizAdminViewSet, FilaMatrizAdminViewSet, JornadaAdminViewSet, MomentoAdminViewSet,
    OpcionAdminViewSet, PreguntaAdminViewSet, RolJornadaAdminViewSet, UsuarioAdminViewSet,
)

router = DefaultRouter()
router.register('jornadas', JornadaAdminViewSet, basename='admin-jornada')
router.register('jornadas-roles', RolJornadaAdminViewSet, basename='admin-jornada-rol')
router.register('momentos', MomentoAdminViewSet, basename='admin-momento')
router.register('preguntas', PreguntaAdminViewSet, basename='admin-pregunta')
router.register('opciones', OpcionAdminViewSet, basename='admin-opcion')
router.register('preguntas-filas-matriz', FilaMatrizAdminViewSet, basename='admin-pregunta-fila')
router.register('preguntas-columnas-matriz', ColumnaMatrizAdminViewSet, basename='admin-pregunta-columna')
router.register('participantes', ParticipanteAdminViewSet, basename='admin-participante')
router.register('respuestas', RespuestaAdminViewSet, basename='admin-respuesta')
router.register('momento-extracciones', ExtraccionMomentoViewSet, basename='admin-momento-extraccion')
router.register('usuarios', UsuarioAdminViewSet, basename='admin-usuario')

urlpatterns = router.urls
