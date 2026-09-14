from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CaseInsensitiveModelBackend(ModelBackend):
    """Login por `username` sin distinguir mayúsculas/minúsculas — Postgres compara texto exacto
    por defecto, así que un usuario "John" no podía entrar escribiendo "john" (caso real reportado
    por un docente). La contraseña sigue siendo sensible a mayúsculas: eso no cambia, solo el
    campo username. Se usa tanto en /api/admin/login/ como en /api/instrumentos/login/ (ambos
    llaman al mismo obtain_auth_token, que a su vez pasa por este backend) y también en el login
    de /admin/ — todo Django auth pasa por AUTHENTICATION_BACKENDS."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = UserModel._default_manager.get(**{f'{UserModel.USERNAME_FIELD}__iexact': username})
        except UserModel.DoesNotExist:
            # Mismo truco que ModelBackend: corre el hash igual para no filtrar por timing si el
            # usuario existe o no.
            UserModel().set_password(password)
            return None
        except UserModel.MultipleObjectsReturned:
            user = UserModel._default_manager.filter(
                **{f'{UserModel.USERNAME_FIELD}__iexact': username}
            ).order_by('id').first()

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
