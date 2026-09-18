"""Sirve los archivos de `media/` que SÍ son públicos.

nginx tiene un `alias` para `static/` de esta app pero no para `media/` (agrohub sí lo tiene), y
agregarlo requiere root, que no está disponible. Así que los sirve Django. Para un puñado de
imágenes de marca e infografías el costo es irrelevante; si algún día crece, la solución buena
siguen siendo cuatro líneas de nginx (ver docs/INTEGRACION_FRONTEND_ASSETS_INFOGRAFIA.md).

IMPORTANTE — solo se expone la lista blanca. En `media/` también viven los documentos que suben
los participantes (`participantes/extracciones/`, `instrumentos/extracciones/`): datos personales
que nunca se pensaron para servirse por URL (ver el comentario de MEDIA_URL en settings.py).
Servir `media/` entero los publicaría a quien acierte la ruta, así que acá se sirve lo que es
público por diseño —los assets de marca de la jornada y las infografías generadas— y nada más.
"""
import posixpath

from django.conf import settings
from django.http import Http404
from django.views.static import serve

DIRECTORIOS_PUBLICOS = ('jornadas/assets/', 'analitica/infografias/')


def servir_media_publica(request, path):
    # Se normaliza ANTES de comparar: `jornadas/assets/../participantes/extracciones/x.pdf`
    # empieza por un directorio público pero apunta fuera de él, y `django.views.static.serve`
    # normaliza internamente — comparar el string crudo dejaría pasar justamente eso.
    ruta = posixpath.normpath(path).lstrip('/')
    if not ruta.startswith(DIRECTORIOS_PUBLICOS):
        raise Http404('Ese archivo no es público.')
    return serve(request, ruta, document_root=settings.MEDIA_ROOT)
