"""Informe de una SesionTranscripcion vía OpenAI — mismo espíritu que
`analitica/analisis_ia_openai.py` (una lectura de corrido, no un análisis mecánico pregunta por
pregunta), pero acá no hay preguntas ni conteos reales que proteger: es una conversación libre, así
que el resultado son hallazgos en prosa respaldados por citas textuales, nunca cifras inventadas.

Sesiones de hasta 4 horas (~35-40 mil palabras) no caben con margen de seguridad en una sola
llamada sin arriesgar timeout y, peor, perder TODO el análisis si esa única llamada falla. En vez
de eso, se resume por mapa-reducción — mismo principio jerárquico que ya usa `analysis.py`
(pregunta → momento → jornada) para que el contexto de cada llamada nunca escale con el tamaño de
la sesión:

    MAPA (paralelo, por tramo cronológico) → REDUCE (una síntesis final)

Un tramo que falla no tumba el informe completo — se reintenta ese tramo por separado o, si sigue
fallando, se sintetiza con los tramos que sí funcionaron y se deja constancia en `resultado`."""
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.utils import timezone

DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o')
REASONING_EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'medium')
GENERATION_TIMEOUT_SECONDS_TRAMO = 240
GENERATION_TIMEOUT_SECONDS_SINTESIS = 300
MAX_OUTPUT_TOKENS_TRAMO = 3000
MAX_OUTPUT_TOKENS_SINTESIS = 8000
MODELO_USADO_LABEL = 'Generado con IA'

# ~8000 palabras por tramo mantiene cada llamada del mapa lejos de cualquier límite de tiempo/
# tokens de salida, sin importar cuántas horas dure la sesión completa — una sesión de 4h da entre
# 4 y 6 tramos en vez de una sola llamada gigante.
PALABRAS_POR_TRAMO = 8000
MAX_TRAMOS_EN_PARALELO = 4

SYSTEM_PROMPT_TRAMO = (
    "Eres un analista leyendo UN TRAMO de la transcripción de una sesión (reunión, entrevista o "
    "taller) universitaria — este tramo es solo una parte de una conversación más larga, así que "
    "NO redactes un resumen ejecutivo ni conclusiones finales todavía, eso lo hace otro paso "
    "después con todos los tramos juntos. Tu trabajo acá es extraer, de ESTE tramo únicamente: "
    "los temas que se discutieron, y los puntos concretos (acuerdos, desacuerdos, decisiones, "
    "preocupaciones, datos mencionados) con una cita textual real que los respalde — nunca "
    "resumas de más ni inventes algo que no esté literalmente dicho en el texto. Si el tramo "
    "incluye la etiqueta de quién habla (entre corchetes al inicio de cada línea), úsala para "
    "identificar a quién citas; si no aparece, cita sin atribuir a nadie en particular.\n\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin fences "
    "de markdown, con esta forma exacta:\n"
    "{\n"
    '  "temas": ["<tema tratado en este tramo>", ...],\n'
    '  "puntos": [\n'
    "    {\n"
    '      "descripcion": "<el punto en sí, 1 a 2 frases>",\n'
    '      "cita": "<fragmento textual real de la transcripción que lo respalda>"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Nunca inventes temas, puntos ni citas que no estén en el texto entregado a continuación."
)

SYSTEM_PROMPT_SINTESIS = (
    "Eres un analista senior redactando el informe final de una sesión (reunión, entrevista o "
    "taller) universitaria, a partir de resúmenes parciales que ya se hicieron por tramos "
    "cronológicos de la transcripción completa (se te entregan en JSON, en orden). Tu trabajo es "
    "leerlos todos de corrido, como si tuvieras la sesión completa sobre la mesa, y sintetizar un "
    "informe único — buscando ACTIVAMENTE dónde un mismo tema o postura reaparece en varios "
    "tramos distintos antes de conformarte con un hallazgo de un solo tramo (eso es más valioso: "
    "revela un patrón sostenido en toda la sesión, no un comentario aislado). Prioriza pocos "
    "hallazgos densos y sustanciales sobre muchos superficiales: entrega entre 5 y 12 hallazgos "
    "según lo que la sesión realmente dé — nunca fuerces un número si el material no lo sostiene, "
    "pero tampoco te quedes corto si hay más patrones reales para reportar.\n\n"
    "Cada hallazgo debe llevar al menos una cita textual real (tomada de las citas ya extraídas "
    "por tramo — nunca la reescribas ni la parafrasees) que lo respalde. Nunca inventes nada que "
    "no esté en los datos entregados.\n\n"
    "Responde ÚNICAMENTE con un objeto JSON válido, sin explicación antes ni después, sin fences "
    "de markdown, con esta forma exacta:\n"
    "{\n"
    '  "resumen_ejecutivo": "<panorama general de toda la sesión, 4 a 7 frases>",\n'
    '  "temas_discutidos": ["<tema>", ...],\n'
    '  "hallazgos": [\n'
    "    {\n"
    '      "titulo": "<título corto y natural del hallazgo, no un identificador técnico>",\n'
    '      "descripcion": "<la deducción en sí, 2 a 5 frases>",\n'
    '      "citas": ["<cita textual real que lo respalda>", ...]\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Prosa natural y profesional en español, nunca con etiquetas como '(1)', 'Hallazgo:' o "
    "'Conclusión:' dentro del texto (el campo `titulo` ya cumple ese rol). Nunca frases genéricas "
    "que servirían para cualquier informe."
)

_ETIQUETA_RE = re.compile(
    r'^\s*(\(\d+\)|\d+[.)]\s|hallazgo\s*\d*\s*:|conclusión\s*:|resumen\s*:)\s*', re.IGNORECASE,
)


def _limpiar_texto(texto):
    if not texto:
        return texto
    limpio = _ETIQUETA_RE.sub('', texto.strip())
    return re.sub(r'\s{2,}', ' ', limpio).strip()


def _llamar_openai_json(system, user, max_output_tokens, timeout_seconds, model=None):
    """Una sola llamada a la API de OpenAI en modo JSON estricto. Devuelve (dict_o_None, error) —
    nunca lanza excepción. Copia deliberada (no importada) de
    analitica.analisis_ia_openai._llamar_openai_json — mismo mecanismo, pero transcripciones no
    depende de internals de analitica para mantener los dos módulos independientes."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None, 'OPENAI_API_KEY no está configurada en el entorno del servidor (.env).'

    resultado = {}

    def _run():
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            kwargs = dict(
                model=model or DEFAULT_MODEL,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
                max_completion_tokens=max_output_tokens,
                response_format={'type': 'json_object'},
            )
            if REASONING_EFFORT:
                kwargs['reasoning_effort'] = REASONING_EFFORT
            else:
                kwargs['temperature'] = 0.4
            respuesta = client.chat.completions.create(**kwargs)
            resultado['texto'] = respuesta.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001 — cualquier falla de la API cae a error legible
            resultado['error'] = str(exc)

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    hilo.join(timeout=timeout_seconds)

    if hilo.is_alive():
        return None, f'Tiempo de espera agotado ({timeout_seconds}s) esperando a OpenAI.'
    if resultado.get('error'):
        return None, resultado['error']
    texto = resultado.get('texto')
    if not texto:
        return None, 'OpenAI no devolvió contenido.'
    try:
        return json.loads(texto), None
    except json.JSONDecodeError as exc:
        return None, f'OpenAI devolvió JSON inválido: {exc}'


def _particionar_en_tramos(fragmentos):
    """fragmentos: iterable de FragmentoTranscripcion ya ordenados por secuencia. Devuelve una
    lista de tramos (cada uno, una lista de fragmentos) cortando por PALABRAS_POR_TRAMO sin partir
    nunca un fragmento a la mitad."""
    tramos = []
    tramo_actual = []
    palabras_tramo = 0
    for fragmento in fragmentos:
        palabras = len(fragmento.texto.split())
        if tramo_actual and palabras_tramo + palabras > PALABRAS_POR_TRAMO:
            tramos.append(tramo_actual)
            tramo_actual = []
            palabras_tramo = 0
        tramo_actual.append(fragmento)
        palabras_tramo += palabras
    if tramo_actual:
        tramos.append(tramo_actual)
    return tramos


def _texto_tramo(fragmentos_tramo):
    lineas = []
    for fragmento in fragmentos_tramo:
        prefijo = f'[{fragmento.hablante}] ' if fragmento.hablante else ''
        lineas.append(f'{prefijo}{fragmento.texto}')
    return '\n'.join(lineas)


def _resumir_tramo(indice, total, texto_tramo):
    user = f'TRAMO {indice + 1} de {total} (orden cronológico) — TRANSCRIPCIÓN:\n\n{texto_tramo}'
    resultado, error = _llamar_openai_json(
        SYSTEM_PROMPT_TRAMO, user,
        max_output_tokens=MAX_OUTPUT_TOKENS_TRAMO, timeout_seconds=GENERATION_TIMEOUT_SECONDS_TRAMO,
    )
    if resultado:
        return {'indice': indice, 'temas': resultado.get('temas') or [], 'puntos': resultado.get('puntos') or []}
    return {'indice': indice, 'temas': [], 'puntos': [], 'error': error or 'Error desconocido.'}


def _validar_y_limpiar(resultado, sesion):
    resultado['sesion_id'] = sesion.id
    resultado['resumen_ejecutivo'] = _limpiar_texto(resultado.get('resumen_ejecutivo'))
    for hallazgo in resultado.get('hallazgos') or []:
        hallazgo['titulo'] = _limpiar_texto(hallazgo.get('titulo'))
        hallazgo['descripcion'] = _limpiar_texto(hallazgo.get('descripcion'))
    return resultado


def generar_informe_transcripcion(informe_id):
    """Genera el informe de un InformeTranscripcion ya creado (estado `pendiente`). Corre en un
    hilo de background — mismo patrón que procesar_reporte/analizar_jornada_ia."""
    from django.db import close_old_connections

    close_old_connections()
    from .models import InformeTranscripcion

    informe = None
    try:
        informe = InformeTranscripcion.objects.select_related('sesion').get(pk=informe_id)
        informe.estado = InformeTranscripcion.ESTADO_PROCESANDO
        informe.save(update_fields=['estado'])

        fragmentos = list(informe.sesion.fragmentos.order_by('secuencia'))
        if not fragmentos:
            informe.estado = InformeTranscripcion.ESTADO_ERROR
            informe.error_mensaje = 'Esta sesión no tiene ningún fragmento de transcripción todavía.'
            informe.save(update_fields=['estado', 'error_mensaje'])
            return

        tramos = _particionar_en_tramos(fragmentos)

        # MAPA — en paralelo, igual que analysis.py con preguntas (cada llamada es independiente
        # de OpenAI, sin modelo local compartido de por medio, así que no hay riesgo de crash).
        resumenes_parciales = [None] * len(tramos)
        with ThreadPoolExecutor(max_workers=min(len(tramos), MAX_TRAMOS_EN_PARALELO)) as pool:
            futuros = {
                pool.submit(_resumir_tramo, i, len(tramos), _texto_tramo(tramo)): i
                for i, tramo in enumerate(tramos)
            }
            for futuro in as_completed(futuros):
                indice = futuros[futuro]
                resumenes_parciales[indice] = futuro.result()

        tramos_con_error = [r['indice'] for r in resumenes_parciales if r.get('error')]
        tramos_utiles = [
            {'temas': r['temas'], 'puntos': r['puntos']} for r in resumenes_parciales if not r.get('error')
        ]
        if not tramos_utiles:
            informe.estado = InformeTranscripcion.ESTADO_ERROR
            informe.error_mensaje = (
                f'Los {len(tramos)} tramo(s) de esta sesión fallaron al resumirse — no quedó '
                'nada con qué sintetizar el informe final.'
            )
            informe.save(update_fields=['estado', 'error_mensaje'])
            return

        # REDUCE — una síntesis final sobre todos los tramos que sí funcionaron.
        payload = {
            'sesion_nombre': informe.sesion.nombre,
            'sesion_descripcion': informe.sesion.descripcion,
            'tramos': tramos_utiles,
        }
        user = 'RESÚMENES POR TRAMO, EN ORDEN CRONOLÓGICO (JSON):\n' + json.dumps(
            payload, ensure_ascii=False, indent=2,
        )
        resultado, error = _llamar_openai_json(
            SYSTEM_PROMPT_SINTESIS, user,
            max_output_tokens=MAX_OUTPUT_TOKENS_SINTESIS, timeout_seconds=GENERATION_TIMEOUT_SECONDS_SINTESIS,
        )

        if resultado:
            resultado = _validar_y_limpiar(resultado, informe.sesion)
            resultado['tramos_analizados'] = len(tramos)
            if tramos_con_error:
                resultado['tramos_con_error'] = tramos_con_error
            informe.resultado = resultado
            informe.estado = InformeTranscripcion.ESTADO_COMPLETO
            informe.error_mensaje = ''
            informe.modelo_usado = MODELO_USADO_LABEL
            informe.completado_en = timezone.now()
        else:
            informe.estado = InformeTranscripcion.ESTADO_ERROR
            informe.error_mensaje = error or 'Error desconocido generando la síntesis final.'
        informe.save(update_fields=[
            'resultado', 'estado', 'error_mensaje', 'modelo_usado', 'completado_en',
        ])
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if informe is not None:
            informe.estado = InformeTranscripcion.ESTADO_ERROR
            informe.error_mensaje = str(exc)
            informe.save(update_fields=['estado', 'error_mensaje'])
    finally:
        close_old_connections()
