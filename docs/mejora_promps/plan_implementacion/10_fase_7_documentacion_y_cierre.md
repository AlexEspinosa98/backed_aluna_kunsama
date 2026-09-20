# 10 — Fase 7: documentación, HU y cierre

**Objetivo**: dejar el feature documentado como el resto del proyecto: guía de integración para
el frontend, historias de usuario en el archivo maestro, referencia de prompts actualizada,
variables de entorno documentadas.

**Prerrequisitos**: fases 0–5 (y 6 si se hizo). Antes de escribir, **verificar contra el código
real** cada campo, ruta y mensaje que se cite: la documentación describe lo implementado, no el
plan. Si algo del plan se hizo distinto, la doc gana la versión real.

## Paso 7.1 — `docs/INTEGRACION_FRONTEND_ANALISIS_V2.md` (nuevo)

Escribirlo con esta estructura y contenido (ajustar ejemplos a ids reales del servidor de pruebas
si se tienen a mano; si no, usar los de aquí):

```markdown
# Integración frontend — Análisis v2 (contrato `kunsamu.analisis/v2`)

Implementa la entrega `docs/mejora_promps/` (20-sep-2026). Lo que el frontend recibe es
EXACTAMENTE el JSON de `analisis.schema.json`, ya validado (esquema + reglas de negocio) — nunca
llega un resultado inválido. Los tres análisis legacy (`reportes/`, `analisis-momento-ia/`,
`analisis-jornada-ia/`) siguen funcionando igual para el histórico; el renderer se elige por
`version`.

## 0. URL base
(Copiar la sección 0 de docs/INTEGRACION_FRONTEND_ANALISIS_GUIADO.md: develop en
https://kunsamu.josec.ddns.net sin prefijo; producción bajo /api/aluna-kunsama/.)

## 1. Pedir un análisis — `POST /api/admin/analisis-v2/`
Cuerpo, campos, defaults, semántica de `modo` (integral = TODOS los momentos de la jornada,
activos o no; por_momento = uno o varios, un informe por cada uno en orden de `orden`),
`pipeline` (`llm` | `bertopic_llm`), `contexto`/`instrucciones` (≤4000), `personalizacion_momentos`.
Sin `enfoque`: el modelo decide el método por pregunta (`naturaleza`/`metodos` de cada hallazgo).
Respuesta 201 (estado `pendiente`). Errores: 400 (con la clave del campo: `momentos`,
`personalizacion_momentos`, `pipeline`, `jornada`), 403 (jornada ajena), 409 (mismo alcance en curso).
No hay 400 por "sin respuestas": el resultado llega con `estado_analitico = "sin_datos"`.

## 2. Consultar — `GET /api/admin/analisis-v2/?jornada=<id>` | `?momento=<id>` y `GET /{id}/`
La lista NO trae `resultado`, `entrada`, `diagnostico` ni `prompt_usado` (pesan); el detalle sí.
Campos: id, version, jornada (slug), jornada_id, momentos[{id,titulo,slug,orden}], modo, pipeline,
metodo ("bertopic"|"openai", derivado), contexto, instrucciones, personalizacion_momentos, estado
(pendiente|procesando|completo|error — estado del TRABAJO), estado_analitico (completo|parcial|
sin_datos|datos_insuficientes|null — el `estado` del JSON, solo cuando hay resultado),
error_mensaje, version_prompt, version_esquema, modelo_usado ("Generado con IA" | "Sin datos —
generado por el backend sin IA"), solicitado_por, creado_en, actualizado_en, completado_en; en el
detalle además resultado (el JSON v2), entrada (el sobre que se mandó al modelo — sirve para
resolver localizadores de citas en el cliente si se quiere), diagnostico, prompt_usado.
Polling: igual que los legacy (cada pocos segundos mientras `estado` sea pendiente/procesando).
`DELETE /{id}/` borra.

## 3. Lista unificada — `GET /api/admin/analisis/`
Los items v2 llegan con `tipo: "analisis_v2"` y, además de las claves de siempre, `version`,
`modo`, `pipeline`, `estado_analitico`. `enfoque` viene `null`. `?momento=` incluye solo los
por_momento que contienen ese momento (un integral no es "de" un momento).

## 4. Leer `resultado`
Remitir a docs/mejora_promps/ (esquema, TIPOS_VISUALES.md, MIGRACION_FRONTEND.md §4–§6). Notas
propias del backend: unidades de porcentaje pueden venir como "porcentaje" o "%"; `alcance` es
idéntico a `entrada.solicitud`; los IDs de momentos/preguntas del JSON son los ids numéricos del
sistema como strings; `fuentes[].id` sigue el patrón f-m<momento>, f-agg-m<momento>, fbt-p<pregunta>;
los localizadores de citas apuntan a `entrada.fuentes[].datos` (JSON Pointer).

## 5. Infografía (si se hizo la fase 6)
`POST /api/admin/infografias/ {"analisis_v2": <id>}` — mismo contrato "exactamente uno" que
reporte/analisis_momento/analisis_jornada; `GET /api/admin/infografias/?analisis_v2=<id>`.

## 6. Qué NO cambió
Los tres endpoints legacy, sus formatos y `analisis-sugerencias/` (que sigue aceptando `enfoque`
opcional). Presentación HTML/PDF no existen para v2.

## 7. Checklist de mapeo para el frontend
- [ ] El wizard manda `modo` + `momentos` + `pipeline` + contexto/instrucciones (+ por momento) a `analisis-v2/`; ya no manda `enfoque`.
- [ ] Renderer por `version` (`kunsamu.analisis/v2` → renderer común; sin `version` → visores históricos).
- [ ] Estado del trabajo (`estado`) y estado analítico (`estado_analitico` / `resultado.estado`) se muestran por separado.
- [ ] La lista usa el endpoint de lista (sin `resultado`); el detalle pide `/{id}/`.
```

Rellenar cada sección con ejemplos JSON reales (request y response) siguiendo el estilo de
`docs/INTEGRACION_FRONTEND_ANALISIS_GUIADO.md`.

## Paso 7.2 — HU en `docs/USER_STORIES_COMPLETO.md`

Agregar **al final del archivo**, numeración correlativa a partir de **HU-73** (la última es
HU-72). Nota: el código y `INTEGRACION_FRONTEND_ANALISIS_GUIADO.md` llaman "HU-73" al aislamiento
de la infografía por versión, que en este archivo es HU-72 — es una discrepancia histórica de
numeración entre el repo del frontend y este; **no** renumerar nada, solo continuar desde HU-73
aquí. Formato del archivo: `### HU-NN — Título`, una línea "Como … quiero …, para …", y bullets
argumentativos (qué se decidió y **por qué**, qué alternativa se descartó). Redactar cinco:

- **HU-73 — Análisis con IA bajo el contrato único `kunsamu.analisis/v2`** (modelo `AnalisisV2`,
  endpoint, modo/pipeline, sin enfoque, lista unificada, D1–D4; por qué un modelo nuevo y no
  tocar los tres legacy; guards; estados del trabajo vs analítico).
- **HU-74 — Entrada normalizada e inmutable, con conteos calculados por el backend** (D7, D11:
  IDs string, inventario completo, fuente respuestas siempre, fuente agregado, categorías
  semilla como contexto, sin_datos sin IA; por qué la entrada se guarda antes de llamar).
- **HU-75 — Salida estructurada estricta y validación en dos capas con un reintento de reparación**
  (D5, D6, D9: prompt = archivo entero, json_schema strict con respaldo, refusal/truncado, esquema +
  negocio, diagnostico para auditoría, nunca publicar inválido; por qué no se "arreglan" cifras).
- **HU-76 — Pipeline `bertopic_llm`: BERTopic exportado como fuente verificable** (D8: una
  ejecución por pregunta ≥8 textos, qué se exporta y qué va vacío y por qué, outliers, stub previo).
- **HU-77 — La infografía se genera también desde un `AnalisisV2`** (solo si se hizo la fase 6; D12).

Cerrar cada HU con la línea de tests ("N tests nuevos en `analitica/tests_v2.py` (clases …); la
suite no se corrió en esta entrega por decisión del dueño del repo" — o el resultado real si él
pidió correrla).

## Paso 7.3 — `docs/SYSTEM_PROMPTS.md`

Agregar una sección `## 7. Análisis v2 (`analitica/v2/`)` antes de la tabla resumen final, que
diga: los prompts v2 son los archivos íntegros `analitica/v2/recursos/SYSTEM_PROMPT_LLM.md` y
`SYSTEM_PROMPT_BERTOPIC.md` (copias congeladas de `docs/mejora_promps/`, versión `VERSION_PROMPT`
en `contrato.py`), se mandan **sin** bloques de enfoque, plantillas ni regla de datos anexada; el
`user` es el JSON de entrada; la salida se fuerza con `response_format` json_schema estricto y se
valida con `validacion.py`. Agregar una fila a la tabla resumen final (`analitica/v2/` → sin
enfoque → salida `kunsamu.analisis/v2`).

También en el encabezado del documento, donde dice que el plan `docs/enfoque_analisis/` nunca se
implementó, agregar una frase: "El contrato que sí se implementó es `kunsamu.analisis/v2`
(`docs/mejora_promps/`, plan en `docs/mejora_promps/plan_implementacion/`)".

## Paso 7.4 — `.env.example`

Debajo de `OPENAI_MODEL=gpt-4o`, agregar:

```
# Análisis v2 (analitica/v2/). Todas opcionales:
# OPENAI_MODEL_V2=            # modelo solo para v2; si no se define usa OPENAI_MODEL
# KUNSAMU_V2_MAX_OUTPUT_TOKENS=24000
# KUNSAMU_V2_TIMEOUT_SECONDS=540
# KUNSAMU_V2_MAX_CARACTERES_ENTRADA=1200000
```

## Paso 7.5 — `docs/mejora_promps/plan_implementacion/README.md`

Agregar al final una sección `## Estado de ejecución` con una tabla fase → commit → fecha →
notas (qué quedó sin probar, desviaciones del plan). Es el registro de lo que realmente se hizo.

## Paso 7.6 — Verificación y commit

Revisar que todos los enlaces relativos de los `.md` nuevos resuelvan (`ls` de cada ruta citada).

```bash
git status --short
git add docs/INTEGRACION_FRONTEND_ANALISIS_V2.md docs/USER_STORIES_COMPLETO.md docs/SYSTEM_PROMPTS.md \
        .env.example docs/mejora_promps/plan_implementacion/README.md
git commit -m "docs(v2): guía de integración del análisis v2, HU-73 a HU-77 y referencia de prompts

Documenta lo implementado en las fases 0–6 del plan de docs/mejora_promps/plan_implementacion/:
endpoint analisis-v2/, lista unificada, lectura del resultado, infografía desde v2, variables de
entorno opcionales, y las decisiones de diseño con su porqué en las HU."
```

## Paso 7.7 — Reporte final al dueño del repo

Un mensaje corto con: commits por fase, qué está desplegado en `develop`, qué se probó a mano
contra el servidor de pruebas (ver `11_verificacion_y_smoke.md`), qué quedó sin probar (la suite
no se corrió, salvo que él lo haya pedido), y los dos avisos operativos: (1) el merge a `main` y
el `migrate` + restart de producción son suyos; (2) los cambios retenidos de `Dockerfile` /
`docker-compose.yml` siguen sin commitear, como pidió.
