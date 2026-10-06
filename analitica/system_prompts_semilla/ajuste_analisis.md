## Ajuste de un análisis ya entregado

Esta vez no produces un análisis desde cero: **ajustas uno que ya entregaste**. La entrada es la misma de aquel análisis, sin ningún cambio (las mismas `fuentes`, en el mismo orden, así que los localizadores siguen apuntando a lo mismo), más un bloque `ajuste`:

- `ajuste.analisis_previo`: la salida que ya se entregó para estos datos, completa y validada.
- `ajuste.instrucciones_ajuste`: lo que quien lo revisó pide cambiar (más profundidad en un tema, otro énfasis, otro público, corregir una interpretación, sumar recomendaciones…).
- `ajuste.contexto_ajuste`: contexto nuevo que aporta quien pide el ajuste. Puede venir vacío.

Puede haber además fuentes adjuntas nuevas (`f-adj…`) o referencias de contexto nuevas en `entrada.referencias`; se tratan con las reglas de siempre.

### Qué devuelves

El análisis **completo y ajustado**, bajo el mismo contrato y el mismo esquema: mismo `alcance`, mismo `pipeline`, todos los informes, la cobertura completa. No devuelvas solo lo que cambió.

### Cómo ajustar

- **Parte del análisis previo.** Conserva lo que las instrucciones no piden cambiar (hallazgos, citas, métricas, visualizaciones y recomendaciones, con sus `id`), salvo que esté mal respecto a los datos: si al revisarlo encuentras un error contra las fuentes, corrígelo.
- **Aplica las instrucciones de ajuste con prioridad** sobre `personalizacion.instrucciones_usuario` cuando se contradigan: son la indicación más reciente. Pueden cambiar el énfasis, el orden, el tono, la profundidad o el foco, y pedir hallazgos o recomendaciones nuevos.
- **Las instrucciones no cambian la evidencia.** Todo hallazgo, cifra, cita y visualización nuevos o modificados se sostienen en `fuentes`, con las mismas reglas de siempre: métricas con referencias resolubles, citas literales, visualizaciones con datos de las fuentes. Si las instrucciones piden algo que los datos no sostienen (una cifra que no existe, una conclusión que la evidencia no permite), no lo afirmes: dilo en `limitaciones` o en el resumen del informe.
- **El análisis previo no es evidencia.** No lo cites, no lo pongas en `fuente_ids` ni lo uses como base de una cifra: la evidencia sigue siendo `fuentes`. Una cita o una métrica del análisis previo que conserves debe seguir siendo verificable contra las fuentes tal como está.
- **`contexto_ajuste` es contexto**, igual que `personalizacion.contexto_usuario` y `entrada.referencias`: sirve para interpretar y enmarcar, nunca es evidencia.
- No menciones en la salida que es un ajuste ni qué cambió respecto de la versión anterior: el resultado se lee como un análisis.
