# Carga de documentos base (HU-101)

Cómo subir los documentos de apoyo de una jornada (acuerdos, planes, informes previos) para que
después se puedan adjuntar a un análisis. Solo lo nuevo.

Todas las rutas van bajo `/api/admin/` y requieren usuario admin.

---

## 1. Subir

`POST /api/admin/jornada-assets/` — `multipart/form-data`

| Campo | Obligatorio | Valor |
|---|---|---|
| `jornada` | sí | id de la jornada |
| `tipo` | sí | **`documento`** |
| `archivos` | sí | uno o varios archivos `.pdf`, `.docx`, `.txt` o `.md`; el campo se repite una vez por archivo |
| `titulo` | no | nombre legible; solo si se sube **un** archivo |
| `descripcion` | no | qué es y para qué sirve. La IA lo lee junto al documento, así que conviene llenarlo |

```bash
curl -X POST https://back.alunaia.co/api/aluna-kunsama/api/admin/jornada-assets/ \
  -H "Authorization: Token <token>" \
  -F jornada=7 -F tipo=documento \
  -F titulo="Acuerdo 012 de 2025" \
  -F descripcion="Acuerdo del Consejo Académico que fija las franjas horarias" \
  -F archivos=@acuerdo_012.pdf
```

Respuesta `201`: **una lista**, un item por archivo.

```json
[
  {
    "id": 41,
    "jornada": 7,
    "tipo": "documento",
    "nombre": "Acuerdo 012 de 2025",
    "titulo": "Acuerdo 012 de 2025",
    "descripcion": "Acuerdo del Consejo Académico que fija las franjas horarias",
    "archivo": "…/acuerdo_012.pdf",
    "nombre_archivo_original": "acuerdo_012.pdf",
    "contenido_estado": "sin_leer",
    "contenido_metodo": "",
    "contenido_error": "",
    "contenido_caracteres": 0,
    "creado_en": "2026-10-06T01:10:00Z"
  }
]
```

`nombre` es lo que conviene mostrar en pantalla: es el `titulo`, o el nombre del archivo si no hay título.

**Errores `400`:** formato no admitido (por ejemplo, una imagen con `tipo=documento`), ningún archivo, o
`titulo` con varios archivos. La tanda es **todo o nada**: si un archivo falla, no se crea ninguno.

## 2. Esperar a que se lea

Al subirlo, el backend lee el documento en segundo plano y lo convierte en el texto que va a usar la IA.

| `contenido_estado` | Significado |
|---|---|
| `sin_leer` | recién subido |
| `leyendo` | en proceso |
| `listo` | se puede adjuntar a un análisis |
| `error` | no se pudo leer; el motivo viene en `contenido_error` |

Para seguirlo hay que consultar `GET /api/admin/jornada-assets/{id}/` hasta que el estado sea `listo` o
`error`. Un PDF con texto o un Word tardan segundos. Un PDF escaneado se transcribe con IA y puede tardar
un par de minutos.

`contenido_metodo` indica cómo se leyó:
- `texto_extraido`: se tomó el texto del archivo.
- `vision`: era un PDF escaneado y se transcribió con IA. Puede tener errores de lectura.
- `texto_escrito`: alguien corrigió el texto a mano.

## 3. Ver y corregir lo que se leyó

- `GET /api/admin/jornada-assets/{id}/` trae además **`contenido_texto`**, el texto completo que va a
  leer la IA. Conviene mostrarlo, sobre todo cuando `contenido_metodo` es `vision`.
- `PATCH /api/admin/jornada-assets/{id}/` (JSON) acepta `titulo`, `descripcion` y `contenido_texto`. Si
  se corrige `contenido_texto`, queda `listo` con método `texto_escrito`.
- `POST /api/admin/jornada-assets/{id}/leer/` vuelve a leer el archivo, por ejemplo después de un
  `error`. Responde `202` y se sigue igual que en el paso 2.

El archivo no se reemplaza: si hay que cambiarlo, se sube uno nuevo y se borra el viejo con
`DELETE /api/admin/jornada-assets/{id}/`.

## 4. Listar

`GET /api/admin/jornada-assets/?jornada=7&tipo=documento`

En el listado no viene el texto completo (puede pesar mucho). Si se necesita, hay que agregar `&con_contenido=1`.

---

Para adjuntar estos documentos a un análisis, como fuente o como contexto, ver
`docs/INTEGRACION_FRONTEND_ADJUNTOS.md` §3.
