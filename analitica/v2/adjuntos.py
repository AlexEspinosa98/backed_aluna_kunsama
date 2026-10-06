"""Adjuntos de un análisis (HU-101): documentos e imágenes de la jornada (`JornadaAsset`) que quien
pide el análisis suma a la entrada, eligiendo para cada uno cómo entra:

- **`fuente`** — evidencia secundaria. Va en `entrada.fuentes` como una fuente más, de tipo
  `resumen_secundario` (el tipo que el contrato ya prevé para material que no son las respuestas
  de los participantes), con el texto completo del adjunto en `datos.texto`. El modelo la puede
  poner en `fuente_ids` de un hallazgo y citarla con el localizador `/texto`; el backend verifica
  la cita contra ese texto como contra cualquier otra fuente. Nunca entra a los conteos: los
  agregados (`f-agg-m…`) y BERTopic se calculan solo sobre las respuestas.
- **`contexto`** — marco para interpretar. Va en `entrada.referencias`, fuera de `fuentes`: no
  tiene id de fuente, así que ningún hallazgo, cita, métrica ni visualización puede apuntar a
  ella (la validación de negocio lo rechazaría). Sirve para entender la normativa, los
  antecedentes o los objetivos institucionales, contrastar lo que dicen los participantes y
  alinear las recomendaciones.

Lo que se manda de cada adjunto es su `contenido_texto` (ver `jornadas/contenido_assets.py`): el
texto extraído de un documento o lo que se leyó con visión de una imagen o de un PDF escaneado.
Si un adjunto pedido no se puede leer, el análisis falla ANTES de llamar a la IA con el motivo —
quien lo pidió eligió ese adjunto, y un análisis que lo omite en silencio no es el que pidió.

Sin adjuntos la entrada queda idéntica a la de antes: no aparece la clave `referencias`.
"""
USO_FUENTE = 'fuente'
USO_CONTEXTO = 'contexto'
USO_CHOICES = [
    (USO_FUENTE, 'Fuente — evidencia secundaria, citable'),
    (USO_CONTEXTO, 'Contexto — marco para interpretar, nunca evidencia'),
]
MAX_ADJUNTOS = 15

# Viaja dentro de `entrada.referencias` para que la regla esté junto al material aunque el system
# prompt activo sea anterior a HU-101. Es metadato estructural del backend, no texto del usuario.
NOTA_REFERENCIAS = (
    'Material de CONTEXTO aportado por quien pide el análisis. Úsalo para entender el marco '
    '(normativa, antecedentes, objetivos institucionales, resultados previos), para interpretar y '
    'contrastar lo que dicen las fuentes y para alinear las recomendaciones. NO es evidencia: no '
    'lo incluyas en `fuente_ids`, no lo cites, no cuentes nada a partir de él ni atribuyas a los '
    'participantes algo que solo dice este material. Si lo usas para enmarcar un hallazgo, dilo '
    'en la redacción («según el documento X, …»).'
)

_TIPO_REFERENCIA = {'asset': 'imagen', 'system_design': 'guia_de_marca', 'documento': 'documento'}


def _como_se_leyo(asset):
    from jornadas.models import JornadaAsset

    return {
        JornadaAsset.METODO_TEXTO: 'texto extraído del archivo, sin resumir',
        JornadaAsset.METODO_VISION: (
            'leído con un modelo de visión (transcripción del texto visible y descripción de la '
            'imagen); puede contener errores de lectura'
        ),
        JornadaAsset.METODO_TEXTO_ESCRITO: 'texto escrito por el equipo organizador',
    }.get(asset.contenido_metodo, 'texto del adjunto')


def _es_imagen(asset):
    return asset.tipo == 'asset' or (
        asset.tipo == 'system_design' and asset.archivo
        and (asset.nombre_archivo_original or asset.archivo.name).lower().rsplit('.', 1)[-1] != 'pdf'
    )


def _fuente(asset, texto):
    clase = 'Imagen adjunta' if _es_imagen(asset) else 'Documento adjunto'
    metodo = f'Adjunto aportado por el equipo organizador ({_como_se_leyo(asset)}).'
    if asset.descripcion:
        metodo += f' Descripción de quien lo adjuntó: {asset.descripcion}'
    return {
        'id': f'f-adj{asset.id}',
        'tipo': 'resumen_secundario',
        'etiqueta': f'{clase} — {asset.nombre_legible}',
        'momento_ids': [],
        'pregunta_ids': [],
        'cobertura': 'desconocida',
        'datos': {
            'texto': texto,
            'fuentes_originales_ids': [],
            'metodo_resumen': metodo,
            'cobertura_original': 'desconocida',
        },
    }


def _referencia(asset, texto):
    return {
        'id': f'ref-adj{asset.id}',
        'tipo': 'imagen' if _es_imagen(asset) else _TIPO_REFERENCIA.get(asset.tipo, 'documento'),
        'titulo': asset.nombre_legible,
        'descripcion': asset.descripcion or '',
        'lectura': _como_se_leyo(asset),
        'texto': texto,
    }


def resolver_adjuntos(jornada, adjuntos, usos=(USO_FUENTE, USO_CONTEXTO)):
    """`(fuentes, referencias, notas)` para los `adjuntos` pedidos (`[{'asset': id, 'uso': …}]`),
    leyendo el contenido de los que todavía no lo tengan. Lanza `ValueError` con un motivo legible
    si alguno ya no existe, no es de la jornada o no se puede leer."""
    from jornadas.contenido_assets import ErrorLecturaAsset, asegurar_contenido
    from jornadas.models import JornadaAsset

    adjuntos = list(adjuntos or [])
    if not adjuntos:
        return [], [], []
    assets = {a.id: a for a in JornadaAsset.objects.filter(jornada=jornada, id__in=[int(x['asset']) for x in adjuntos])}
    fuentes, referencias, notas = [], [], []
    for item in adjuntos:
        asset = assets.get(int(item['asset']))
        if asset is None:
            raise ValueError(f'El adjunto {item["asset"]} ya no existe o no pertenece a esta jornada.')
        uso = item.get('uso') or USO_CONTEXTO
        if uso not in usos:
            raise ValueError(f'Uso de adjunto no admitido aquí: {uso!r}.')
        try:
            texto = asegurar_contenido(asset)
        except ErrorLecturaAsset as exc:
            raise ValueError(f'No se pudo leer el adjunto "{asset.nombre_legible}": {exc}') from exc
        if uso == USO_FUENTE:
            fuentes.append(_fuente(asset, texto))
        else:
            referencias.append(_referencia(asset, texto))
        notas.append({
            'asset': asset.id, 'uso': uso, 'metodo': asset.contenido_metodo, 'caracteres': len(texto),
        })
    return fuentes, referencias, notas


def bloque_referencias(referencias):
    return {'nota': NOTA_REFERENCIAS, 'documentos': referencias}


def anexar_adjuntos(entrada, jornada, adjuntos, diagnostico=None):
    """Suma los adjuntos a una entrada del análisis (in place) y la devuelve."""
    fuentes, referencias, notas = resolver_adjuntos(jornada, adjuntos)
    entrada['fuentes'].extend(fuentes)
    if referencias:
        entrada['referencias'] = bloque_referencias(referencias)
    if diagnostico is not None and notas:
        diagnostico['adjuntos'] = notas
    return entrada
