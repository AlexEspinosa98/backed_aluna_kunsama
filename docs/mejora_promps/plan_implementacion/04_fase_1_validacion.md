# 04 — Fase 1: validación de esquema y de negocio + comando de verificación

**Objetivo**: `analitica/v2/validacion.py`, que dado un resultado v2 y su entrada devuelve la
lista de errores (vacía = válido), y un comando `python manage.py validar_ejemplos_v2` que lo
ejercita contra los ejemplos congelados (y, más adelante, contra un `AnalisisV2` guardado). Esta
fase no toca modelos ni endpoints.

**Prerrequisitos**: fase 0.

**Referencias de la entrega que implementa**: `README.md` §"Validación de negocio obligatoria",
`TIPOS_VISUALES.md` §11, `verificar_entrega.py::semantic_checks` (se porta ampliado, devolviendo
TODOS los errores en vez de lanzar en el primero).

## Paso 1.1 — `analitica/v2/validacion.py`

Crear con este contenido exacto:

```python
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


def validar_salida(salida, entrada, pipeline_esperado=None):
    """Las dos capas en orden: si el esquema falla, no tiene sentido (ni es seguro) correr las
    reglas de negocio sobre una forma desconocida."""
    errores = validar_esquema(salida)
    if errores:
        return errores
    return validar_negocio(salida, entrada, pipeline_esperado=pipeline_esperado)
```

## Paso 1.2 — Comando `validar_ejemplos_v2`

Crear `analitica/management/commands/validar_ejemplos_v2.py` (la carpeta `management/commands/`
ya existe con `__init__.py`):

```python
"""`python manage.py validar_ejemplos_v2` — corre la validación v2 (analitica/v2/validacion.py)
sobre los ejemplos congelados de la entrega y sobre un puñado de mutaciones que DEBEN rechazarse.
Es la verificación de la fase 1 del plan (docs/mejora_promps/plan_implementacion/) y una forma de
comprobar cambios en validacion.py sin correr la suite completa.

Con `--analisis <id>` valida en su lugar el `resultado` de un AnalisisV2 guardado contra su propia
`entrada` inmutable (útil para QA de una respuesta real del modelo)."""
import copy
import json

from django.core.management.base import BaseCommand, CommandError

from analitica.v2.contrato import RECURSOS
from analitica.v2.validacion import validar_esquema, validar_negocio, validar_salida


class Command(BaseCommand):
    help = 'Valida los ejemplos congelados del contrato v2 (o un AnalisisV2 guardado con --analisis).'

    def add_arguments(self, parser):
        parser.add_argument('--analisis', type=int, default=None, help='id de un AnalisisV2 guardado')

    def handle(self, *args, **options):
        if options['analisis'] is not None:
            return self._validar_analisis_guardado(options['analisis'])
        self._validar_ejemplos()

    def _validar_analisis_guardado(self, analisis_id):
        from analitica.models import AnalisisV2

        try:
            analisis = AnalisisV2.objects.get(pk=analisis_id)
        except AnalisisV2.DoesNotExist as exc:
            raise CommandError(f'No existe AnalisisV2 {analisis_id}') from exc
        if not analisis.resultado:
            raise CommandError(f'AnalisisV2 {analisis_id} no tiene resultado (estado={analisis.estado})')
        errores = validar_salida(analisis.resultado, analisis.entrada, pipeline_esperado=analisis.pipeline)
        if errores:
            for error in errores:
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            raise CommandError(f'{len(errores)} error(es) en AnalisisV2 {analisis_id}')
        self.stdout.write(self.style.SUCCESS(f'OK AnalisisV2 {analisis_id}: esquema y reglas de negocio'))

    def _validar_ejemplos(self):
        carpeta = RECURSOS / 'ejemplos'
        salidas = sorted(carpeta.glob('*.salida.json'))
        if not salidas:
            raise CommandError(f'No hay ejemplos en {carpeta}')
        pares = 0
        for ruta in salidas:
            salida = json.loads(ruta.read_text(encoding='utf-8'))
            errores = validar_esquema(salida)
            ruta_entrada = ruta.with_name(ruta.name.replace('.salida.', '.entrada.'))
            if not errores and ruta_entrada.exists():
                entrada = json.loads(ruta_entrada.read_text(encoding='utf-8'))
                errores = validar_negocio(salida, entrada, pipeline_esperado=salida['pipeline'])
                pares += 1
            if errores:
                for error in errores:
                    self.stdout.write(self.style.ERROR(f'  - {error}'))
                raise CommandError(f'{ruta.name}: {len(errores)} error(es)')
            self.stdout.write(f'OK {ruta.name}')

        # Mutaciones que DEBEN rechazarse (mismas cuatro de verificar_entrega.py + dos propias).
        original = json.loads((carpeta / 'llm_integral.salida.json').read_text(encoding='utf-8'))
        entrada = json.loads((carpeta / 'llm_integral.entrada.json').read_text(encoding='utf-8'))
        mutantes = []
        m = copy.deepcopy(original); m['html'] = '<p>No permitido</p>'; mutantes.append(('clave extra', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['metricas'][0]['valor'] = 90; mutantes.append(('porcentaje falso', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['citas'][0]['texto'] = 'Cita inventada'; mutantes.append(('cita no literal', m))
        m = copy.deepcopy(original); m['informes'][0]['hallazgos'][0]['visualizacion_ids'] = ['no-existe']; mutantes.append(('visualización inexistente', m))
        m = copy.deepcopy(original); m['cobertura'] = m['cobertura'][:-1]; mutantes.append(('cobertura incompleta', m))
        m = copy.deepcopy(original); m['fuentes'][0]['cobertura'] = 'parcial'; mutantes.append(('fuente alterada', m))
        for nombre, mutante in mutantes:
            errores = validar_salida(mutante, entrada, pipeline_esperado='llm')
            if not errores:
                raise CommandError(f'La mutación "{nombre}" fue aceptada y debía rechazarse')
            self.stdout.write(f'OK rechazada: {nombre} ({errores[0][:90]}…)')
        self.stdout.write(self.style.SUCCESS(
            f'Esquema y reglas OK: {len(salidas)} salidas, {pares} pares con entrada, {len(mutantes)} mutaciones rechazadas.'
        ))
```

> Nota: hasta la fase 4 no existe `AnalisisV2`; el import de `--analisis` es perezoso (dentro del
> método) a propósito, así el comando funciona desde ya.

## Paso 1.3 — Verificación

```bash
source .venv/bin/activate
python -m py_compile analitica/v2/validacion.py analitica/management/commands/validar_ejemplos_v2.py
python manage.py validar_ejemplos_v2
```

Salida esperada: `OK` para las 5 salidas (`bertopic_integral`, `catalogo_visual`, `llm_integral`,
`llm_por_momento`, `sin_datos`), `OK rechazada:` ×6 y la línea final en verde con
`5 salidas, 4 pares con entrada, 6 mutaciones rechazadas`.

Si algún ejemplo de la entrega fallara una regla de negocio nueva (las que no estaban en
`verificar_entrega.py`), **la regla está mal, no el ejemplo**: los ejemplos son el contrato.
Revisar la regla, corregirla y anotar en el reporte cuál fue.

## Paso 1.4 — Tests (escribir, no correr)

Crear `analitica/tests_v2.py` con esta primera clase (las fases siguientes agregan más al mismo
archivo):

```python
"""Tests del contrato kunsamu.analisis/v2 (analitica/v2/). Separados de tests.py para no tocar la
suite legacy. Sin OPENAI_API_KEY en el entorno de test: toda llamada al proveedor se mockea o cae
determinísticamente al error 'OPENAI_API_KEY no está configurada'."""
import copy
import json

from django.test import SimpleTestCase

from .v2.contrato import RECURSOS
from .v2.validacion import PunteroInvalido, resolver_puntero, validar_esquema, validar_negocio, validar_salida


def _ejemplo(nombre):
    return json.loads((RECURSOS / 'ejemplos' / nombre).read_text(encoding='utf-8'))


class ValidacionEjemplosTests(SimpleTestCase):
    """Los ejemplos de la entrega son el contrato: los cuatro pares pasan las dos capas y el
    catálogo visual pasa el esquema."""

    def test_pares_de_la_entrega_son_validos(self):
        for base in ('llm_integral', 'llm_por_momento', 'bertopic_integral', 'sin_datos'):
            salida, entrada = _ejemplo(f'{base}.salida.json'), _ejemplo(f'{base}.entrada.json')
            self.assertEqual(validar_salida(salida, entrada, pipeline_esperado=salida['pipeline']), [], base)

    def test_catalogo_visual_pasa_el_esquema(self):
        self.assertEqual(validar_esquema(_ejemplo('catalogo_visual.salida.json')), [])

    def test_rechaza_clave_extra_en_raiz(self):
        salida = _ejemplo('llm_integral.salida.json')
        salida['html'] = '<p>x</p>'
        self.assertTrue(any('[esquema]' in e for e in validar_esquema(salida)))

    def test_rechaza_porcentaje_que_no_cuadra(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['metricas'][0]['valor'] = 90
        self.assertTrue(any('no corresponde a 100×' in e for e in validar_negocio(salida, entrada)))

    def test_rechaza_cita_no_literal(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['citas'][0]['texto'] = 'Cita inventada'
        self.assertTrue(any('subcadena literal' in e for e in validar_negocio(salida, entrada)))

    def test_rechaza_visualizacion_huerfana_y_referencia_rota(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['informes'][0]['hallazgos'][0]['visualizacion_ids'] = ['no-existe']
        errores = validar_negocio(salida, entrada)
        self.assertTrue(any('inexistente' in e for e in errores))
        self.assertTrue(any('huérfanas' in e for e in errores))

    def test_rechaza_cobertura_incompleta_y_pipeline_distinto(self):
        salida, entrada = _ejemplo('llm_integral.salida.json'), _ejemplo('llm_integral.entrada.json')
        salida['cobertura'] = salida['cobertura'][:-1]
        errores = validar_negocio(salida, entrada, pipeline_esperado='bertopic_llm')
        self.assertTrue(any('cobertura: faltan' in e for e in errores))
        self.assertTrue(any(e.startswith('pipeline:') for e in errores))

    def test_por_momento_rechaza_cruce_de_fuentes_entre_momentos(self):
        salida, entrada = _ejemplo('llm_por_momento.salida.json'), _ejemplo('llm_por_momento.entrada.json')
        # El informe i2 (m2) usa la fuente f1, que es de m1.
        salida['informes'][1]['hallazgos'][0]['fuente_ids'] = ['f1', 'f2']
        self.assertTrue(any('cruce no permitido' in e for e in validar_negocio(salida, entrada)))

    def test_puntero_json(self):
        datos = {'respuestas': [{'valor': 'hola'}, {'valor': {'celdas': [{'valor': 'x'}]}}], 'a~b': {'c/d': 1}}
        self.assertEqual(resolver_puntero(datos, '/respuestas/0/valor'), 'hola')
        self.assertEqual(resolver_puntero(datos, '/respuestas/1/valor/celdas/0/valor'), 'x')
        self.assertEqual(resolver_puntero(datos, '/a~0b/c~1d'), 1)
        for ruta in ('respuestas/0', '/respuestas/9/valor', '/respuestas/0/valor/x'):
            with self.assertRaises(PunteroInvalido):
                resolver_puntero(datos, ruta)
```

`python -m py_compile analitica/tests_v2.py` debe pasar. No correr los tests.

## Paso 1.5 — Commit

```bash
git status --short
git add analitica/v2/validacion.py analitica/management/commands/validar_ejemplos_v2.py analitica/tests_v2.py
git commit -m "feat(v2): validación de esquema y de negocio del contrato kunsamu.analisis/v2

Dos capas (jsonschema Draft 2020-12 sobre el esquema congelado + reglas de negocio de la entrega:
alcance, cobertura, fuentes copiadas tal cual, referencias, citas literales, porcentajes
recalculados y condiciones por tipo de visualización), devolviendo TODOS los errores para que el
reintento de reparación del orquestador (fase 3) los reciba completos. Comando
validar_ejemplos_v2 para verificar contra los ejemplos de la entrega sin correr la suite."
```

## Criterios de "hecho"

- [ ] `validacion.py` compila; `python manage.py validar_ejemplos_v2` termina en verde.
- [ ] `tests_v2.py` compila (no se corre).
- [ ] Commit sin `Dockerfile`/`docker-compose.yml`.
