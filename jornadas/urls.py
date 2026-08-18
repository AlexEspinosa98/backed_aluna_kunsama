from rest_framework.routers import DefaultRouter

from participantes.admin_views import ParticipanteAdminViewSet, RespuestaAdminViewSet

from .views import JornadaAdminViewSet, MomentoAdminViewSet, OpcionAdminViewSet, PreguntaAdminViewSet

router = DefaultRouter()
router.register('jornadas', JornadaAdminViewSet, basename='admin-jornada')
router.register('momentos', MomentoAdminViewSet, basename='admin-momento')
router.register('preguntas', PreguntaAdminViewSet, basename='admin-pregunta')
router.register('opciones', OpcionAdminViewSet, basename='admin-opcion')
router.register('participantes', ParticipanteAdminViewSet, basename='admin-participante')
router.register('respuestas', RespuestaAdminViewSet, basename='admin-respuesta')

urlpatterns = router.urls
