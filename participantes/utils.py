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
