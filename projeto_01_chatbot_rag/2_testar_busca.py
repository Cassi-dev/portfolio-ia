"""
Testa a busca e o "modo não sei" no terminal.

    python projeto_01_chatbot_rag/2_testar_busca.py [modo]       # vetorial_rerank (padrão), vetorial, hibrido, ...
"""
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import chromadb

from core.embeddings import EmbeddingFunctionMultilingue
from recuperacao import MODOS, Recuperador, decidir

PASTA_BANCO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banco_vetorial")
LIMIAR_DISTANCIA = 0.16   # modos sem reranker (ver README: calibração)
LIMIAR_RERANK = -4.0      # modos com reranker

modo = sys.argv[1] if len(sys.argv) > 1 else "vetorial_rerank"
if modo not in MODOS:
    sys.exit(f"Modo inválido. Use um destes: {', '.join(MODOS)}")

colecao = chromadb.PersistentClient(path=PASTA_BANCO).get_collection(
    name="meus_documentos_ptbr", embedding_function=EmbeddingFunctionMultilingue()
)
recuperador = Recuperador(colecao, modo)

print("=" * 70)
print(f"  BUSCA NO MODO '{modo}' E O MODO 'NÃO SEI'")
print("=" * 70)

perguntas_teste = [
    "Qual o tamanho de bloco recomendado para testar?",
    "Quantos dias tenho para pedir reembolso integral?",
    "Qual é a melhor receita de pudim de leite condensado?",
]

for pergunta in perguntas_teste:
    res = recuperador.buscar(pergunta, k=2)
    decisao = decidir(res, LIMIAR_DISTANCIA, LIMIAR_RERANK if modo.endswith("_rerank") else None)
    print(f"\n❓ {pergunta}")
    if res.trechos:
        t = res.trechos[0]
        local = f"pág. {t.pagina}" + (f", seção “{t.secao}”" if t.secao else "")
        print(f"   melhor trecho: {t.arquivo} ({local})")
    print(f"   {'✅ RESPONDE' if decisao.responder else '🚫 NÃO SEI'}: {decisao.motivo}  [{res.latencias_ms['total']:.0f} ms]")
    if decisao.responder and res.trechos:
        print(f"   >>> \"{res.trechos[0].texto[:200]}...\"")
