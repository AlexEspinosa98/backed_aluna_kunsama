# Integración frontend — Adjuntos de un análisis (HU-101)

Documentos e imágenes que se suman a un análisis, eligiendo para cada uno si cuentan como
**fuente** (evidencia secundaria, citable) o como **contexto** (marco para interpretar, nunca
evidencia), y que también pueden usarse en la presentación.

Todo vive en los **assets de la jornada**, el mismo recurso que ya se usa para infografías y
presentaciones. No hay un endpoint nuevo de subida.

---

## 1. Subir

`POST /api/admin/jornada-assets/` — multipart, igual que hoy (`archivos` repetido una vez por archivo).

| Campo | Tipo | Notas |
|---|---|---|
| `jornada` | id | obligatorio |
| `tipo` | `asset` \| `system_design` \| `documento` | **`documento`** es nuevo: `.pdf`, `.docx`, `.txt`, `.md`. Las imágenes siguen siendo `asset` (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`). |
| `archivos` | archivos | uno o varios |
| `titulo` | string | opcional; solo con **un** archivo (con varios, cada uno toma el nombre de su archivo) |
| `descripcion` | string | opcional; qué es y para qué sirve. **Le llega al modelo**, así que conviene llenarlo («Acuerdo del Consejo Académico que fija las franjas horarias»). |
| `usar_en_presentacion` | bool | default `true`; con `false` la imagen no entra a la diagramación ni a las infografías (ej. la foto de un papelógrafo que solo sirve para el análisis) |

Responde **una lista** (`201`), como siempre. Cada item trae ahora:

```json
{
  "id": 41, "jornada": 7, "tipo": "documento", "archivo": "…/acuerdo.pdf",
  "nombre_archivo_original": "acuerdo.pdf", "titulo": "Acuerdo 012", "nombre": "Acuerdo 012",
  "descripcion": "Acuerdo que fija las franjas horarias", "usar_en_presentacion": true,
  "contenido_estado": "sin_leer", "contenido_metodo": "", "contenido_error": "",
  "contenido_caracteres": 0, "texto": "", "subido_por": 3, "creado_en": "…"
}
```

`nombre` es lo que conviene mostrar: el `titulo`, o el nombre del archivo si no hay título.

## 2. Lectura del contenido

Lo que el análisis lee de un adjunto es **texto**:

| Adjunto | Cómo se lee | `contenido_metodo` |
|---|---|---|
| .docx, .pdf con texto | se extrae el texto (párrafos y tablas en orden) | `texto_extraido` |
| .txt, .md | tal cual | `texto_extraido` |
| .pdf escaneado | transcripción con IA (visión) | `vision` |
| imagen | transcripción literal del texto visible + descripción, con IA (visión) | `vision` |
| guía de marca escrita | su `texto` | `texto_escrito` |

- Un **documento** se lee apenas se sube, en segundo plano.
- Una **imagen** se lee la primera vez que se adjunta a un análisis (no al subirla, para no gastar una
  llamada por cada foto que solo se sube para la infografía). Si se quiere tener lista antes, `POST {id}/leer/`.
- `contenido_estado`: `sin_leer` → `leyendo` → `listo` | `error` (con el motivo en `contenido_error`).
- `GET /api/admin/jornada-assets/{id}/` trae además `contenido_texto` (el texto completo). En el listado
  no va, salvo con `?con_contenido=1`. `?tipo=documento` filtra.
- `POST /api/admin/jornada-assets/{id}/leer/` → `202`; vuelve a leerlo (tras un error, o si se quiere
  releer una imagen). Se sigue por `GET {id}/`.
- `PATCH /api/admin/jornada-assets/{id}/` acepta `titulo`, `descripcion`, `usar_en_presentacion` y
  `contenido_texto`. Corregir `contenido_texto` a mano sirve cuando la lectura con visión se equivocó en
  una cifra: queda `listo` con método `texto_escrito`. El archivo no se reemplaza: se sube otro y se borra el viejo.

Recomendación de UI: mostrar el texto leído antes de lanzar el análisis («Esto es lo que va a leer la IA»),
con opción de corregirlo, sobre todo cuando `contenido_metodo` es `vision`.

## 3. Adjuntar al pedir un análisis

Campo nuevo **`adjuntos`** (opcional) en:

- `POST /api/admin/analisis-v2/`
- `POST /api/admin/analisis-jornada-ia/`
- `POST /api/admin/analisis-momento-ia/`
- `POST /api/admin/reportes/`

```json
{
  "jornada": 7, "modo": "integral", "pipeline": "llm",
  "adjuntos": [
    {"asset": 41, "uso": "fuente"},
    {"asset": 42, "uso": "contexto"}
  ]
}
```

Un id suelto (`"adjuntos": [42]`) equivale a `"uso": "contexto"` — el que no puede alterar la analítica.
El registro devuelve `adjuntos` normalizado (siempre con `asset` y `uso`).

| `uso` | Qué hace el modelo con él | Qué NO puede hacer |
|---|---|---|
| **`fuente`** | Lo trata como evidencia **secundaria**: puede sostener o matizar un hallazgo, aparecer en `fuente_ids` y citarse literalmente. | Contarlo en cifras, porcentajes o bases (salen solo de las respuestas); atribuir a los participantes lo que dice el documento. |
| **`contexto`** | Lo usa para entender el marco (normativa, antecedentes, objetivos), interpretar y contrastar lo que dicen los participantes y alinear las recomendaciones. Si lo usa, lo nombra en el texto. | Ser fuente de un hallazgo, una cita, una métrica o una visualización. El backend rechaza la salida que lo intente. |

Errores (`400`, en `adjuntos`): asset de otra jornada, repetido, `uso` desconocido, más de 15, o sin
contenido. Si un adjunto no se puede leer cuando corre el análisis, el análisis termina en `error` con el
motivo **antes** de llamar a la IA (no se cobra nada): conviene que el frontend avise si algún adjunto
elegido está en `contenido_estado: "error"`.

## 4. Cómo se ve en el resultado

**El contrato de salida no cambia** (`kunsamu.analisis/v2.1`). Un adjunto como fuente aparece en
`resultado.fuentes` como cualquier otra:

```json
{"id": "f-adj41", "tipo": "resumen_secundario", "etiqueta": "Documento adjunto — Acuerdo 012",
 "momento_ids": [], "pregunta_ids": [], "cobertura": "desconocida"}
```

y sus citas tienen `fuente_id: "f-adj41"` y `localizador: "/texto"`. Para mostrar el fragmento con su
contexto, el texto completo está en `entrada.fuentes[…].datos.texto` del detalle del análisis.

Sugerencia de UI: distinguir visualmente las fuentes `f-adj…` («Documento adjunto», «Imagen adjunta» ya
viene en `etiqueta`) de las respuestas de los participantes.

Los adjuntos de contexto no aparecen en `resultado` (no son fuente de nada). Quedan en
`entrada.referencias` del detalle, por si se quiere mostrar «Contexto usado».

## 5. Presentación

- **Resumen para presentación** — `POST /api/admin/resumenes-presentacion/` acepta `adjuntos` como lista
  de ids, **solo contexto** (`{"asset": 41, "uso": "fuente"}` → `400`): el resumen se valida contra los
  datos del análisis original y no puede sumar evidencia nueva. Sirve para orientarlo al público («perfil
  del Consejo Superior», «lineamientos de la rectoría»).
- **Diagramación** (`presentacion-diseno/`) e **infografía**: usan automáticamente las imágenes y la guía
  de marca con `usar_en_presentacion: true`; los documentos nunca entran. La diagramación recibe además el
  `titulo` y la `descripcion` de cada imagen, que la ayudan a decidir dónde usarla.

## 6. Checklist

- [ ] Selector de tipo `documento` en la subida de assets, con `titulo` y `descripcion`.
- [ ] Estado de lectura (`contenido_estado`) y vista/edición del texto leído.
- [ ] Interruptor `usar_en_presentacion` por imagen.
- [ ] En el formulario de análisis: elegir adjuntos y, para cada uno, «Fuente» o «Contexto» (default «Contexto»).
- [ ] En el visor: distinguir las fuentes `f-adj…`.
- [ ] En el resumen para presentación: elegir adjuntos de contexto.
