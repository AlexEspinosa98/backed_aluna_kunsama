from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

Usuario = get_user_model()


class EsUsuarioDelSistema(BasePermission):
    """Para endpoints de instrumentos que no resuelven un instrumento puntual en la URL (ej. el
    listado de 'mis instrumentos asignados'). isinstance(user, Usuario) es necesario porque
    Participante también fuerza is_authenticated=True vía sus atributos falsos (ver
    participantes/models.py) y no tiene los related_name que este módulo usa sobre User — sin
    este chequeo, un token de Participante haría un AttributeError (500) en vez de un 403 limpio,
    el mismo riesgo que ya se documenta para Participante contra /api/admin/**."""
    message = 'Debes autenticarte con una cuenta de usuario del sistema.'

    def has_permission(self, request, view):
        return isinstance(request.user, Usuario) and request.user.is_authenticated


class EsPreregistradoDeInstrumento(BasePermission):
    """Mismo patrón que participantes.permissions.EsParticipanteDeLaJornada — el usuario debe ser
    un User real (no un Participante, que también pasa is_authenticated=True gracias a sus
    atributos falsos) y estar preregistrado específicamente para el instrumento de la URL."""
    message = 'Debes autenticarte como usuario preregistrado de este instrumento.'

    def has_permission(self, request, view):
        user = request.user
        if not isinstance(user, Usuario) or not user.is_authenticated:
            return False

        instrumento_slug = view.kwargs.get('instrumento_slug')
        return user.instrumentos_asignados.filter(instrumento__slug=instrumento_slug).exists()
