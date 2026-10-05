"""Resumen de un análisis terminado, para presentarlo en diapositivas (HU-99).

Recibe la salida estructurada (`kunsamu.analisis/v2`) de un análisis ya completo y produce otra con
el mismo contrato, más corta, en el modo segundo plano de OpenAI (`v2.background`). Lo que se le
manda al modelo NO es la entrada del análisis (las respuestas de los participantes) sino el
análisis mismo: es mucho más chico — más barato y más rápido — y es lo único que hace falta para
resumir. La validación, en cambio, sí usa la entrada original del análisis (ver
`_AdaptadorResumenPresentacion`): por eso las citas y métricas del resumen siguen siendo
verificables contra los datos.
"""
from django.db import close_old_connections

from auditoria.openai_cliente import auditar_llamadas

from .v2 import background
from .v2.contrato import VERSION_ESQUEMA
from .v2.migracion_contrato import visualizaciones_a_v2_1

# Del análisis original solo se le manda al modelo lo que necesita para resumir. La cobertura
# (una fila por pregunta) no aporta nada a un resumen y en una jornada grande pesa mucho: el
# backend la copia tal cual al armar la salida.
CLAVES_PARA_EL_MODELO = ('alcance', 'estado', 'fuentes', 'limitaciones', 'informes', 'visualizaciones')


def entrada_del_resumen(resumen):
    from .models import resultado_v2_de

    original = resultado_v2_de(resumen.fuente)
    analisis = {clave: original[clave] for clave in CLAVES_PARA_EL_MODELO}
    # El resumen sale en v2.1 (HU-100): si el análisis es v2, sus visualizaciones van ya en la forma
    # v2.1 (campos de color vacíos) para que el modelo las pueda copiar idénticas.
    analisis['visualizaciones'] = visualizaciones_a_v2_1(analisis['visualizaciones'])
    return {
        'jornada': {'nombre': resumen.jornada.nombre, 'descripcion': resumen.jornada.descripcion or ''},
        'instrucciones_usuario': resumen.instrucciones or '',
        'analisis': analisis,
    }


def iniciar_resumen(resumen):
    """Fija la versión del prompt, guarda lo que se le va a mandar al modelo y lanza el primer
    intento. Nunca lanza: cualquier falla deja el resumen en error con el motivo."""
    from .models import SystemPrompt

    resumen.diagnostico = {'intentos': [], 'modo': 'background', 'store': background.GUARDAR_EN_OPENAI}
    try:
        prompt = SystemPrompt.activo_de(SystemPrompt.TIPO_RESUMEN_PRESENTACION)
        resumen.entrada = entrada_del_resumen(resumen)
        resumen.version_prompt = prompt.referencia
        resumen.version_esquema = VERSION_ESQUEMA
        resumen.save(update_fields=['entrada', 'version_prompt', 'version_esquema', 'diagnostico', 'actualizado_en'])
        # Desde lo guardado, igual que el análisis: intento y reparación mandan el mismo texto exacto.
        resumen.refresh_from_db(fields=['entrada'])
        background._lanzar(resumen, resumen.FASE_INTENTO)
    except Exception as exc:  # noqa: BLE001
        background._terminar_con_error(resumen, str(exc))


@auditar_llamadas('analitica.ResumenPresentacion')
def generar_resumen_presentacion(resumen_id):
    """Corre en un hilo de segundo plano: lanza y consulta hasta que termina. Si el hilo muere
    (reinicio), el cron `consultar_analisis_background` sigue desde donde quedó."""
    close_old_connections()
    from .models import ResumenPresentacion

    resumen = None
    try:
        resumen = ResumenPresentacion.objects.select_related('jornada').get(pk=resumen_id)
        resumen.estado = ResumenPresentacion.ESTADO_PROCESANDO
        resumen.save(update_fields=['estado', 'actualizado_en'])
        iniciar_resumen(resumen)
        resumen.refresh_from_db(fields=['estado'])
        if resumen.estado == ResumenPresentacion.ESTADO_PROCESANDO:
            background.seguir_hasta_terminar(resumen.id, ResumenPresentacion)
    except Exception as exc:  # noqa: BLE001 — nunca debe dejar el hilo morir en silencio
        if resumen is not None:
            background._terminar_con_error(resumen, str(exc))
    finally:
        close_old_connections()
