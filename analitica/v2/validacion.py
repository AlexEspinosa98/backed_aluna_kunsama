"""Validación de una salida `kunsamu.analisis/v2` en dos capas (README de la entrega, §"Validación
de negocio obligatoria"):

1. `validar_esquema`: forma y tipos contra `recursos/analisis.schema.json` (jsonschema, Draft
   2020-12). Con `response_format` estricto de OpenAI esto casi nunca falla, pero el modo estricto
   no es una garantía absoluta y el respaldo `json_object` (ver llm.py) no tiene ninguna.
2. `validar_negocio`: lo que el esquema no puede expresar — alcance, cobertura, fuentes copiadas
   tal cual, referencias e IDs, citas literales, porcentajes recalculados y las condiciones por
   tipo de visualización (TIPOS_VISUALES.md §11).

Las dos devuelven una lista de strings (vacía = válido). Nunca lanzan por un JSON raro: cualquier
forma inesperada es un error reportado. Devolver TODOS los errores (y no solo el primero) es lo
que hace útil el reintento de reparación de procesar.py: el modelo recibe la lista completa.

Reglas de ESTILO (largo del resumen, palabras por título) no se validan a propósito — no están en
la tabla obligatoria de la entrega y fallarlas convertiría en error técnico un informe correcto.
"""
import math
import re

from jsonschema import Draft202012Validator

from .contrato import MODO_INTEGRAL, cargar_esquema

# Los ejemplos de la entrega usan "porcentaje"; TIPOS_VISUALES.md usa "%". Se aceptan las dos.
UNIDADES_PORCENTAJE = ('porcentaje', '%')
# 33.33 para 2/6 (=33.333…) y también 33.3 (redondeo a un decimal): el error máximo de redondear a
# un decimal es 0.05.
TOLERANCIA_PORCENTAJE = 0.051
# Suma de una barra 100%: tolera redondeos por categoría documentados.
TOLERANCIA_BARRAS_100 = 0.5

TIPOS_CATEGORICOS = ('barras', 'barras_agrupadas', 'barras_apiladas', 'barras_100', 'dona', 'radar')
TIPOS_COORDENADAS = ('lineas', 'areas', 'dispersion', 'pendientes')
TIPOS_TABLA = ('tabla', 'matriz_cualitativa')

# YYYY-MM-DD o fecha-hora ISO con zona explícita (TIPOS_VISUALES.md §4).
_FECHA_ISO_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2}))?$'
)


class PunteroInvalido(ValueError):
    pass


def resolver_puntero(valor, ruta):
    """JSON Pointer (RFC 6901) relativo a `valor`. `''` es el valor completo. Lanza
    `PunteroInvalido` si no resuelve — el llamador lo convierte en un error de la lista."""
    if ruta == '':
        return valor
    if not isinstance(ruta, str) or not ruta.startswith('/'):
        raise PunteroInvalido(f'JSON Pointer inválido: {ruta!r}')
    for clave in ruta[1:].split('/'):
        clave = clave.replace('~1', '/').replace('~0', '~')
        if isinstance(valor, list):
            if not clave.isdigit() or int(clave) >= len(valor):
                raise PunteroInvalido(f'índice {clave!r} fuera de rango en {ruta!r}')
            valor = valor[int(clave)]
        elif isinstance(valor, dict):
            if clave not in valor:
                raise PunteroInvalido(f'clave {clave!r} inexistente en {ruta!r}')
            valor = valor[clave]
        else:
            raise PunteroInvalido(f'{ruta!r} atraviesa un valor escalar')
    return valor


def validar_esquema(salida):
    validador = Draft202012Validator(cargar_esquema())
    errores = []
    for error in sorted(validador.iter_errors(salida), key=lambda e: [str(p) for p in e.absolute_path]):
        ruta = '/' + '/'.join(str(p) for p in error.absolute_path)
        errores.append(f'[esquema] {ruta}: {error.message}'[:400])
    return errores


def _es_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)


def _es_entero_no_negativo(valor):
    return _es_numero(valor) and valor >= 0 and float(valor).is_integer()


def _chequear_porcentaje(errores, donde, valor, numerador, denominador):
    if numerador is None or denominador is None:
        errores.append(f'{donde}: porcentaje sin numerador/denominador')
        return
    if (
        not _es_numero(numerador) or not _es_numero(denominador)
        or denominador <= 0 or numerador < 0 or numerador > denominador
    ):
        errores.append(f'{donde}: numerador/denominador inválidos ({numerador}/{denominador})')
        return
    if valor is None or not _es_numero(valor) or abs(valor - 100 * numerador / denominador) > TOLERANCIA_PORCENTAJE:
        errores.append(f'{donde}: el porcentaje {valor} no corresponde a 100×{numerador}/{denominador}')


def _clave_orden_x(x):
    # Números antes que strings; entre strings, orden lexicográfico (las fechas ISO lo respetan).
    return (0, x) if _es_numero(x) else (1, str(x))


def validar_negocio(salida, entrada, pipeline_esperado=None):
    """Reglas que dependen de la ENTRADA (alcance, inventario, fuentes, corpus) y las condiciones
    semánticas por tipo de visualización. Asume que `validar_esquema` ya pasó (accede a las claves
    sin defensas de forma). Devuelve la lista de errores."""
    errores = []
    solicitud = entrada['solicitud']
    modo = solicitud['modo']

    if salida['alcance'] != solicitud:
        errores.append('alcance: debe ser idéntico a solicitud de la entrada')
    if pipeline_esperado and salida['pipeline'] != pipeline_esperado:
        errores.append(f"pipeline: se esperaba {pipeline_esperado!r}, llegó {salida['pipeline']!r}")

    # --- IDs locales únicos (informes, hallazgos, recomendaciones y visualizaciones, todos juntos) ---
    ids = [v['id'] for v in salida['visualizaciones']] + [i['id'] for i in salida['informes']]
    ids += [x['id'] for i in salida['informes'] for k in ('hallazgos', 'recomendaciones') for x in i[k]]
    duplicados = sorted({i for i in ids if ids.count(i) > 1})
    if duplicados:
        errores.append(f'IDs locales duplicados: {duplicados}')

    # --- fuentes: copiadas tal cual (sin `datos`), sin repetidas, existentes en la entrada ---
    fuentes_entrada = {f['id']: f for f in entrada['fuentes']}
    declaradas = {}
    for fuente in salida['fuentes']:
        if fuente['id'] in declaradas:
            errores.append(f"fuentes: '{fuente['id']}' repetida")
            continue
        declaradas[fuente['id']] = fuente
        original = fuentes_entrada.get(fuente['id'])
        if original is None:
            errores.append(f"fuentes: '{fuente['id']}' no existe en la entrada")
            continue
        esperada = {k: v for k, v in original.items() if k != 'datos'}
        if fuente != esperada:
            errores.append(f"fuentes: metadatos de '{fuente['id']}' alterados (copiar tal cual, sin 'datos')")

    # --- cobertura: exactamente una fila por pregunta inventariada ---
    esperada_cobertura = {(m['id'], p['id']) for m in entrada['momentos'] for p in m['preguntas']}
    obtenida = [(c['momento_id'], c['pregunta_id']) for c in salida['cobertura']]
    faltan = esperada_cobertura - set(obtenida)
    sobran = set(obtenida) - esperada_cobertura
    if faltan:
        errores.append(f'cobertura: faltan filas para (momento, pregunta) = {sorted(faltan)}')
    if sobran:
        errores.append(f'cobertura: filas para preguntas fuera del inventario = {sorted(sobran)}')
    if len(obtenida) != len(set(obtenida)):
        errores.append('cobertura: filas duplicadas')

    # --- informes: uno (integral) o uno por momento en orden (por_momento) ---
    preguntas_por_momento = {m['id']: {p['id'] for p in m['preguntas']} for m in entrada['momentos']}
    informes = salida['informes']
    if modo == MODO_INTEGRAL:
        if len(informes) != 1:
            errores.append(f'informes: modo integral exige exactamente 1 informe, hay {len(informes)}')
        elif informes[0]['momento_ids'] != solicitud['momento_ids']:
            errores.append('informes[0].momento_ids debe ser igual a solicitud.momento_ids')
    elif [i['momento_ids'] for i in informes] != [[m] for m in solicitud['momento_ids']]:
        errores.append(
            'informes: modo por_momento exige un informe por momento, en el orden de '
            'solicitud.momento_ids, cada uno con exactamente ese momento_id'
        )

    visuales = {v['id']: v for v in salida['visualizaciones']}
    usadas = set()
    for informe in informes:
        pref = f"informes[{informe['id']}]"
        preguntas_informe = set()
        for momento_id in informe['momento_ids']:
            preguntas_informe |= preguntas_por_momento.get(momento_id, set())
        hallazgo_ids = {h['id'] for h in informe['hallazgos']}
        for rec in informe['recomendaciones']:
            if not rec['hallazgo_ids'] or not set(rec['hallazgo_ids']) <= hallazgo_ids:
                errores.append(
                    f"{pref}.recomendaciones[{rec['id']}]: hallazgo_ids vacío o con ids ajenos al informe"
                )
        for hallazgo in informe['hallazgos']:
            hp = f"{pref}.hallazgos[{hallazgo['id']}]"
            fuentes_h = set(hallazgo['fuente_ids'])
            if not fuentes_h <= set(declaradas):
                errores.append(f'{hp}: fuente_ids con fuentes no declaradas en `fuentes`')
            if modo != MODO_INTEGRAL:
                for fuente_id in fuentes_h & set(declaradas):
                    if not set(declaradas[fuente_id]['momento_ids']) <= set(informe['momento_ids']):
                        errores.append(f'{hp}: usa la fuente {fuente_id!r} de otro momento (cruce no permitido)')
            if not set(hallazgo['pregunta_ids']) <= preguntas_informe:
                errores.append(f'{hp}: pregunta_ids con preguntas fuera de los momentos del informe')
            for vid in hallazgo['visualizacion_ids']:
                if vid not in visuales:
                    errores.append(f'{hp}: visualizacion_ids referencia {vid!r}, inexistente')
                usadas.add(vid)
            for i, cita in enumerate(hallazgo['citas']):
                cp = f'{hp}.citas[{i}]'
                if cita['fuente_id'] not in fuentes_h:
                    errores.append(f'{cp}: fuente_id no está en fuente_ids del hallazgo')
                    continue
                original = fuentes_entrada.get(cita['fuente_id'])
                if original is None:
                    continue
                try:
                    texto_origen = resolver_puntero(original['datos'], cita['localizador'])
                except PunteroInvalido as exc:
                    errores.append(f'{cp}: localizador no resoluble ({exc})')
                    continue
                if not isinstance(texto_origen, str) or not cita['texto'] or cita['texto'] not in texto_origen:
                    errores.append(f'{cp}: la cita no es una subcadena literal del texto localizado')
            for i, metrica in enumerate(hallazgo['metricas']):
                mp = f'{hp}.metricas[{i}]'
                if not _es_numero(metrica['valor']):
                    errores.append(f'{mp}: valor no es un número finito')
                for referencia in metrica['referencias']:
                    if referencia['fuente_id'] not in fuentes_h:
                        errores.append(f'{mp}: referencia a una fuente no declarada en el hallazgo')
                        continue
                    original = fuentes_entrada.get(referencia['fuente_id'])
                    if original is None:
                        continue
                    try:
                        resolver_puntero(original['datos'], referencia['ruta'])
                    except PunteroInvalido as exc:
                        errores.append(f'{mp}: ruta no resoluble ({exc})')
                if metrica['unidad'] in UNIDADES_PORCENTAJE:
                    _chequear_porcentaje(errores, mp, metrica['valor'], metrica['numerador'], metrica['denominador'])

    huerfanas = set(visuales) - usadas
    if huerfanas:
        errores.append(f'visualizaciones huérfanas (ningún hallazgo las referencia): {sorted(huerfanas)}')
    for visual in salida['visualizaciones']:
        vp = f"visualizaciones[{visual['id']}]"
        if not set(visual['fuente_ids']) <= set(declaradas):
            errores.append(f'{vp}: fuente_ids con fuentes no declaradas')
        _validar_datos_visual(errores, vp, visual, set(declaradas))
    return errores


def _validar_datos_visual(errores, vp, visual, declaradas):
    tipo = visual['tipo']
    datos = visual['datos']

    if tipo in TIPOS_CATEGORICOS:
        orden = datos['orden_categorias']
        if len(orden) != len(set(orden)):
            errores.append(f'{vp}: orden_categorias con duplicados')
        claves, series = set(), set()
        sumas_por_categoria = {}
        for i, fila in enumerate(datos['filas']):
            fp = f'{vp}.filas[{i}]'
            if fila['categoria'] not in orden:
                errores.append(f'{fp}: categoría fuera de orden_categorias')
            clave = (fila['categoria'], fila['serie'])
            if clave in claves:
                errores.append(f'{fp}: categoría+serie repetida')
            claves.add(clave)
            series.add(fila['serie'])
            if fila['valor'] is not None:
                if not _es_numero(fila['valor']):
                    errores.append(f'{fp}: valor no es un número finito')
                    continue
                if datos['unidad'] in UNIDADES_PORCENTAJE:
                    _chequear_porcentaje(errores, fp, fila['valor'], fila['numerador'], fila['denominador'])
                rango = datos['rango']
                if rango is not None and not (rango['min'] <= fila['valor'] <= rango['max']):
                    errores.append(f'{fp}: valor fuera del rango declarado')
                sumas_por_categoria[fila['categoria']] = sumas_por_categoria.get(fila['categoria'], 0) + fila['valor']
        if tipo == 'dona' and len(series) != 1:
            errores.append(f'{vp}: dona exige exactamente una serie')
        if tipo == 'radar' and datos['rango'] is None:
            errores.append(f'{vp}: radar exige rango explícito común a todos los ejes')
        if tipo == 'barras_100':
            for categoria, suma in sumas_por_categoria.items():
                if abs(suma - 100) > TOLERANCIA_BARRAS_100:
                    errores.append(f'{vp}: barras_100 — la categoría {categoria!r} suma {suma}, no 100')

    elif tipo in TIPOS_COORDENADAS:
        por_serie = {}
        for i, punto in enumerate(datos['filas']):
            fp = f'{vp}.filas[{i}]'
            x = punto['x']
            if datos['tipo_x'] == 'numero' and not _es_numero(x):
                errores.append(f'{fp}: tipo_x=numero pero x no es número')
            if datos['tipo_x'] == 'fecha' and not (isinstance(x, str) and _FECHA_ISO_RE.match(x)):
                errores.append(f'{fp}: tipo_x=fecha pero x no es una fecha ISO válida')
            if punto['y'] is not None and not _es_numero(punto['y']):
                errores.append(f'{fp}: y no es un número finito')
            por_serie.setdefault(punto['serie'], []).append(x)
        for serie, xs in por_serie.items():
            if tipo in ('lineas', 'areas'):
                if len(xs) != len(set(map(str, xs))):
                    errores.append(f'{vp}: serie {serie!r} con x repetido')
                if xs != sorted(xs, key=_clave_orden_x):
                    errores.append(f'{vp}: serie {serie!r} no está ordenada por x')
            if tipo == 'pendientes' and len(xs) != 2:
                errores.append(f'{vp}: pendientes exige exactamente 2 puntos por serie ({serie!r} tiene {len(xs)})')

    elif tipo == 'histograma':
        fin_anterior = None
        for i, intervalo in enumerate(datos['intervalos']):
            ip = f'{vp}.intervalos[{i}]'
            if not (_es_numero(intervalo['desde']) and _es_numero(intervalo['hasta']) and intervalo['desde'] < intervalo['hasta']):
                errores.append(f'{ip}: se exige desde < hasta')
            if fin_anterior is not None and _es_numero(intervalo['desde']) and intervalo['desde'] < fin_anterior:
                errores.append(f'{ip}: se solapa con el intervalo anterior')
            if not _es_entero_no_negativo(intervalo['conteo']):
                errores.append(f'{ip}: conteo debe ser entero no negativo')
            fin_anterior = intervalo['hasta'] if _es_numero(intervalo['hasta']) else fin_anterior

    elif tipo == 'caja_bigotes':
        for i, grupo in enumerate(datos['grupos']):
            gp = f'{vp}.grupos[{i}]'
            if not (grupo['min'] <= grupo['q1'] <= grupo['mediana'] <= grupo['q3'] <= grupo['max']):
                errores.append(f'{gp}: se exige min ≤ q1 ≤ mediana ≤ q3 ≤ max')
            if not _es_entero_no_negativo(grupo['n']):
                errores.append(f'{gp}: n debe ser entero no negativo')

    elif tipo == 'mapa_calor':
        claves = set()
        for i, celda in enumerate(datos['filas']):
            cp = f'{vp}.filas[{i}]'
            clave = (celda['x'], celda['y'])
            if clave in claves:
                errores.append(f'{cp}: celda x+y repetida')
            claves.add(clave)
            if celda['valor'] is not None:
                if not _es_numero(celda['valor']):
                    errores.append(f'{cp}: valor no es un número finito')
                elif datos['unidad'] in UNIDADES_PORCENTAJE:
                    _chequear_porcentaje(errores, cp, celda['valor'], celda['numerador'], celda['denominador'])

    elif tipo == 'nube_palabras':
        textos = [t['texto'] for t in datos['terminos']]
        if len(textos) != len(set(textos)):
            errores.append(f'{vp}: términos repetidos')
        for i, termino in enumerate(datos['terminos']):
            if not _es_numero(termino['peso']) or termino['peso'] < 0:
                errores.append(f'{vp}.terminos[{i}]: peso debe ser número no negativo')

    elif tipo == 'red_semantica':
        nodos = [n['id'] for n in datos['nodos']]
        if len(nodos) != len(set(nodos)):
            errores.append(f'{vp}: ids de nodo repetidos')
        conjunto_nodos = set(nodos)
        vistas = set()
        for i, arista in enumerate(datos['aristas']):
            ap = f'{vp}.aristas[{i}]'
            if arista['origen'] not in conjunto_nodos or arista['destino'] not in conjunto_nodos:
                errores.append(f'{ap}: origen/destino no son nodos existentes')
            if arista['origen'] == arista['destino']:
                errores.append(f'{ap}: autoenlace no permitido')
            clave = (arista['origen'], arista['destino']) if datos['dirigida'] else frozenset((arista['origen'], arista['destino']))
            if clave in vistas:
                errores.append(f'{ap}: arista duplicada')
            vistas.add(clave)
            if datos['tipo_relacion'] == 'interpretativa' and arista['peso'] is not None:
                errores.append(f'{ap}: en una red interpretativa el peso debe ser null')
            if not set(arista['fuente_ids']) <= declaradas:
                errores.append(f'{ap}: fuente_ids con fuentes no declaradas')

    elif tipo in TIPOS_TABLA:
        columnas = datos['columnas']
        ids_columnas = [c['id'] for c in columnas]
        if len(ids_columnas) != len(set(ids_columnas)):
            errores.append(f'{vp}: ids de columna repetidos')
        ids_filas = [f['id'] for f in datos['filas']]
        if len(ids_filas) != len(set(ids_filas)):
            errores.append(f'{vp}: ids de fila repetidos')
        for i, fila in enumerate(datos['filas']):
            fp = f'{vp}.filas[{i}]'
            if len(fila['celdas']) != len(columnas):
                errores.append(f'{fp}: {len(fila["celdas"])} celdas para {len(columnas)} columnas')
                continue
            for j, (celda, columna) in enumerate(zip(fila['celdas'], columnas)):
                if celda is None:
                    continue
                if columna['tipo'] == 'texto' and not isinstance(celda, str):
                    errores.append(f'{fp}.celdas[{j}]: la columna es de texto')
                elif columna['tipo'] == 'numero' and not _es_numero(celda):
                    errores.append(f'{fp}.celdas[{j}]: la columna es numérica')
                elif columna['tipo'] == 'fecha' and not (isinstance(celda, str) and _FECHA_ISO_RE.match(celda)):
                    errores.append(f'{fp}.celdas[{j}]: la columna es de fecha ISO')


def _indice_ids_fuente(fuente):
    """id → JSON Pointer al texto, para las colecciones donde el modelo tiende a citar por id."""
    datos = fuente.get('datos') or {}
    indice = {}
    for i, r in enumerate(datos.get('respuestas') or []):
        indice[r.get('id')] = f'/respuestas/{i}/valor'
    for i, d in enumerate(datos.get('documentos') or []):
        indice[d.get('id')] = f'/documentos/{i}/texto'
    return indice


def normalizar_salida(salida, entrada):
    """Correcciones de REPRESENTACIÓN que el backend puede hacer sin inventar nada, antes de
    validar — observadas en respuestas reales del modelo (AnalisisJornadaIA #11, 2026-09-20), donde
    el reintento de reparación optó por borrar citas y gráficas en vez de corregirlas:
    1. `localizador`/`ruta` con el ID de una respuesta o documento (`r2442`) en vez del JSON
       Pointer normativo → se resuelve al puntero de ese id dentro de la misma fuente. El id está
       en la entrada, así que la cita sigue siendo auditable.
    2. `orden_categorias` que lista las SERIES (p. ej. los niveles Likert) y ninguna categoría de
       las filas → se reconstruye con las categorías de las filas en orden de aparición.
    Muta `salida` y devuelve la lista de normalizaciones aplicadas (para `diagnostico`). Nunca
    toca cifras ni textos; lo que no encaja se deja tal cual para que la validación lo reporte."""
    notas = []
    indices = {f['id']: _indice_ids_fuente(f) for f in entrada.get('fuentes', [])}

    def _resolver(fuente_id, ruta):
        if isinstance(ruta, str) and not ruta.startswith('/'):
            puntero = indices.get(fuente_id, {}).get(ruta)
            if puntero:
                return puntero
        return ruta

    for informe in salida.get('informes') or []:
        for h in informe.get('hallazgos') or []:
            for cita in h.get('citas') or []:
                nuevo = _resolver(cita.get('fuente_id'), cita.get('localizador'))
                if nuevo != cita.get('localizador'):
                    notas.append(f"cita {cita.get('localizador')!r} → {nuevo}")
                    cita['localizador'] = nuevo
            for m in h.get('metricas') or []:
                for ref in m.get('referencias') or []:
                    nuevo = _resolver(ref.get('fuente_id'), ref.get('ruta'))
                    if nuevo != ref.get('ruta'):
                        notas.append(f"referencia {ref.get('ruta')!r} → {nuevo}")
                        ref['ruta'] = nuevo

    for v in salida.get('visualizaciones') or []:
        if v.get('tipo') not in TIPOS_CATEGORICOS:
            continue
        datos = v.get('datos') or {}
        filas = datos.get('filas') or []
        orden = datos.get('orden_categorias') or []
        categorias = [f.get('categoria') for f in filas]
        series = {f.get('serie') for f in filas}
        if filas and orden and not (set(orden) & set(categorias)) and series <= set(orden):
            datos['orden_categorias'] = list(dict.fromkeys(categorias))
            notas.append(f"visualizaciones[{v.get('id')}]: orden_categorias listaba las series; reconstruido con las categorías de las filas")
    return notas


def validar_salida(salida, entrada, pipeline_esperado=None):
    """Las dos capas en orden: si el esquema falla, no tiene sentido (ni es seguro) correr las
    reglas de negocio sobre una forma desconocida."""
    errores = validar_esquema(salida)
    if errores:
        return errores
    return validar_negocio(salida, entrada, pipeline_esperado=pipeline_esperado)
