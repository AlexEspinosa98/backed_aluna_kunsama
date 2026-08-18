"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_application = get_wsgi_application()


class ScriptNameMiddleware:
    """Honra el prefijo de ruta que agrega Nginx (header X-Script-Name) al
    exponer esta app bajo un subpath (p. ej. /api/aluna-kunsama/), para que
    Django genere URLs absolutas correctas (reverse(), Swagger, etc.)."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]
        return self.app(environ, start_response)


application = ScriptNameMiddleware(django_application)
