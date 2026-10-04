"""
Recalcula os vetores da memória da persona com o modelo de embeddings atual,
sem apagar nada (os textos, as correções ensinadas e os IDs ficam iguais).

Por que existe: em 2026-09-30 os 392 exemplos estavam gravados com o fallback
de hash (_ModeloFallbackHash, usado quando o Windows bloqueia as DLLs do torch),
mas a busca rodava com o modelo real. Vetor de um, pergunta do outro: a busca
devolvia exemplos aleatórios e o clone não imitava nada de verdade.

Uso (com o Python do ambiente virtual):
    %USERPROFILE%\\.venvs\\projetos-ia\\Scripts\\python.exe reindexar_memoria.py

Pare o servidor_bridge antes (parar_bot.bat): os dois abrem o mesmo banco.
"""
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR.parent))

from core.embeddings import MODELO_EMBEDDING, _ModeloFallbackHash, _obter_modelo
from motor_persona import obter_colecao_persona

LOTE = 100


def main():
    if isinstance(_obter_modelo(MODELO_EMBEDDING), _ModeloFallbackHash):
        print("ERRO: o modelo real não carregou (caiu no fallback de hash). Reindexar agora "
              "só repetiria o problema. Verifique o sentence-transformers/torch neste Python.")
        sys.exit(1)

    colecao = obter_colecao_persona()
    tudo = colecao.get(include=["documents", "metadatas"])
    ids, docs, metas = tudo["ids"], tudo["documents"], tudo["metadatas"]
    print(f"{len(ids)} exemplos para reindexar com {MODELO_EMBEDDING}...")

    inicio = time.time()
    for i in range(0, len(ids), LOTE):
        # update com documents faz o Chroma recalcular o vetor com a função
        # de embedding da coleção (o modelo real, agora)
        colecao.update(ids=ids[i:i + LOTE], documents=docs[i:i + LOTE], metadatas=metas[i:i + LOTE])
        print(f"  {min(i + LOTE, len(ids))}/{len(ids)}")
    print(f"Pronto em {time.time() - inicio:.1f}s. Total na memória: {colecao.count()}")


if __name__ == "__main__":
    main()
