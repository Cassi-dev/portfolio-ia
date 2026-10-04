"""
Transforma o feedback 👍/👎 do app em candidatos a pergunta de teste, para VOCÊ revisar.

    python projeto_01_chatbot_rag/4_exportar_feedback.py

Nada entra no gabarito sozinho: o arquivo gerado (resultados/candidatos_gabarito.json) lista as consultas votadas,
com o arquivo do melhor trecho recuperado. Um 👎 costuma ser um erro real do sistema; se a resposta certa existe nos
documentos, copie a pergunta para gabarito_recuperacao.json com a frase de evidência e ela passa a ser medida.
"""
import json
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import registro

registros = registro.carregar()
metricas = registro.resumo_metricas(registros)
if not metricas["consultas"]:
    sys.exit("Ainda não há consultas registradas (o app grava em registros/consultas.jsonl; RAG_LOG=0 desliga).")

print(f"Consultas: {metricas['consultas']} | 'não sei': {metricas['pct_nao_sei']}% | "
      f"latência mediana: {metricas['latencia_mediana_ms']} ms (p95 {metricas['latencia_p95_ms']} ms)")
candidatos = registro.candidatos_a_gabarito(registros)
print(f"Votos: {metricas['com_feedback']} ({metricas['pct_positivo']}% positivos). Candidatos para revisar: {len(candidatos)}")

destino = BASE / "resultados"
destino.mkdir(exist_ok=True)
(destino / "candidatos_gabarito.json").write_text(json.dumps(candidatos, ensure_ascii=False, indent=2), encoding="utf-8")
for c in candidatos:
    print(f"  [{c['voto']}] {c['pergunta']}  (decisão: {c['decisao']}, melhor trecho: {c['arquivo_do_melhor_trecho']})")
print(f"\nSalvo em {destino / 'candidatos_gabarito.json'}")
