"""Adaptador BERTopic → contrato v2. STUB hasta la fase 5 del plan: declara cero ejecuciones, que
es una entrada válida ("una lista de ejecuciones vacía indica ausencia de resultados y debe
declararse como tal", ENTRADA_Y_BERTOPIC.md §6). Así `pipeline=bertopic_llm` funciona desde la
fase 4 sin inventar resultados."""


def anexar_bertopic(entrada, analisis_id=None):
    """(entrada_con_bertopic, notas_para_diagnostico). No lanza."""
    entrada['bertopic'] = {'version_adaptador': '1.0', 'ejecuciones': []}
    return entrada, [{'motivo': 'adaptador_no_implementado'}]
