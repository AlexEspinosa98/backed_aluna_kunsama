def condicion_cumplida(pregunta, participante, opciones_en_este_envio=None):
    """True si `pregunta` no está condicionada (depende_de_opcion es None), o si el dueño
    correspondiente (el participante, o su mesa si la pregunta de la que depende vive en un
    momento tipo mesa) ya tiene una Respuesta marcando esa opción específica. A diferencia de
    mesas_permitidas/roles_permitidos (estáticos), esto consulta Respuesta porque depende de algo
    que el participante ya hizo, no de quién es.

    `opciones_en_este_envio` (opcional, un set/iterable de ids de OpcionPregunta): un momento se
    responde completo en un solo POST (ver HU-21) — si la pregunta disparadora y la condicionada
    van en el MISMO envío, la disparadora todavía no está guardada cuando se valida la
    condicionada, así que RespuestasMomentoView.post pasa acá las opciones que vienen en el
    mismo lote para que también cuenten, no solo lo que ya hay en la base."""
    from jornadas.models import Momento

    from .models import Respuesta

    if pregunta.depende_de_opcion_id is None:
        return True
    if opciones_en_este_envio and pregunta.depende_de_opcion_id in opciones_en_este_envio:
        return True

    pregunta_dueña = pregunta.depende_de_opcion.pregunta
    filtro = {'pregunta': pregunta_dueña, 'opciones': pregunta.depende_de_opcion}
    if pregunta_dueña.momento.tipo == Momento.TIPO_MESA:
        if participante.mesa is None:
            return False
        filtro['mesa'] = participante.mesa
    else:
        filtro['participante'] = participante
    return Respuesta.objects.filter(**filtro).exists()


def agrupar_por_mesa(participantes):
    """Agrupa un iterable de `Participante` por su campo `mesa`. Devuelve
    (mesas: dict[int, list[Participante]], sin_mesa: list[Participante]) — compartido entre
    `MesasView` y el reporte Excel (`analitica/reporte_excel.py`) para que ambos calculen la
    misma distribución exactamente de la misma forma."""
    mesas = {}
    sin_mesa = []
    for p in participantes:
        if p.mesa is None:
            sin_mesa.append(p)
        else:
            mesas.setdefault(p.mesa, []).append(p)
    return mesas, sin_mesa
