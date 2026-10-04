"""
Mede a recuperação de trechos e o "modo não sei" em 68 perguntas sobre 8 documentos fictícios.

    python projeto_01_chatbot_rag/5_avaliar_recuperacao.py

Cruza 2 formas de indexar (plano = antigo; contextual = "Documento > Seção" em cada bloco) com 5 modos de busca
(vetorial, bm25, hibrido, vetorial_rerank, hibrido_rerank). Um trecho "acerta" quando é do arquivo esperado e
contém a frase de evidência (ou, nas perguntas abrangentes, quando é do arquivo esperado).
"""
import json
import os
import shutil
import statistics
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
CORPUS = BASE / "corpus_ficticio"
GABARITO = BASE / "gabarito_recuperacao.json"
PASTA_TEMP = BASE / "banco_vetorial_avaliacao"
K = 5


def carregar_gabarito() -> list:
    return json.loads(GABARITO.read_text(encoding="utf-8"))["perguntas"]


def acertou(trecho, item) -> bool:
    from texto_util import chave
    if trecho.arquivo != item["arquivo"]:
        return False
    return True if item["evidencia"] is None else chave(item["evidencia"]) in chave(trecho.texto)


def posicao_do_acerto(trechos, item):
    for i, t in enumerate(trechos, start=1):
        if acertou(t, item):
            return i
    return None


def auroc(positivos: list, negativos: list) -> float:
    """Chance de uma pergunta respondível ter nota maior que uma não respondível (0,5 = acaso, 1,0 = separa tudo)."""
    if not positivos or not negativos:
        return float("nan")
    maiores = sum((p > n) + 0.5 * (p == n) for p in positivos for n in negativos)
    return maiores / (len(positivos) * len(negativos))


def melhor_corte(respondiveis: list, nao_respondiveis: list) -> float:
    """Corte que maximiza a acurácia balanceada (só chute em cima das notas que existem)."""
    todas = sorted(set(respondiveis + nao_respondiveis))
    candidatos = [(a + b) / 2 for a, b in zip(todas, todas[1:])] or todas
    def balanceada(c):
        acerto_resp = sum(x >= c for x in respondiveis) / max(1, len(respondiveis))
        acerto_nao = sum(x < c for x in nao_respondiveis) / max(1, len(nao_respondiveis))
        return (acerto_resp + acerto_nao) / 2
    return max(candidatos, key=balanceada)


def recusa_com_calibracao_cruzada(itens: list) -> dict:
    """
    Calibra o corte em metade das perguntas e mede na outra metade (e vice-versa), para a medida não ser otimista.
    `itens` = [(respondivel, nota)].
    """
    dobras = [[x for i, x in enumerate(itens) if i % 2 == f] for f in (0, 1)]
    acertos_resp = acertos_nao = tot_resp = tot_nao = 0
    for teste, treino in ((dobras[0], dobras[1]), (dobras[1], dobras[0])):
        corte = melhor_corte([n for r, n in treino if r], [n for r, n in treino if not r])
        for respondivel, nota in teste:
            if respondivel:
                tot_resp += 1
                acertos_resp += nota >= corte
            else:
                tot_nao += 1
                acertos_nao += nota < corte
    return {"acerta_o_que_tem_resposta": acertos_resp / max(1, tot_resp), "recusa_o_que_nao_tem": acertos_nao / max(1, tot_nao)}


def nota_de_relevancia(modo: str, resultado) -> float:
    """Quanto maior, mais o sistema 'acha' que sabe responder."""
    if resultado.melhor_rerank is not None:
        return resultado.melhor_rerank
    if resultado.melhor_distancia is not None:
        return -resultado.melhor_distancia
    return resultado.trechos[0].nota_bm25 if resultado.trechos else 0.0


def avaliar_configuracao(recuperador, gabarito: list) -> dict:
    posicoes, por_tipo, notas, latencias = [], {}, [], []
    for item in gabarito:
        r = recuperador.buscar(item["pergunta"], k=K)
        latencias.append(r.latencias_ms["total"])
        respondivel = item["arquivo"] is not None
        notas.append((respondivel, nota_de_relevancia(recuperador.modo, r), item["tipo"]))
        if respondivel:
            p = posicao_do_acerto(r.trechos, item)
            posicoes.append(p)
            por_tipo.setdefault(item["tipo"], []).append(p)

    def recall(k, lista=posicoes):
        return sum(1 for p in lista if p is not None and p <= k) / len(lista)

    resp = [n for r, n, _ in notas if r]
    nao = [n for r, n, _ in notas if not r]
    dificeis = [n for r, n, t in notas if t == "fora_dominio_dificil"]
    corte = melhor_corte(resp, nao)
    return {
        "corte_sugerido": round(corte, 3),
        "distancia_maxima_sugerida": round(-corte, 3) if recuperador.modo in ("vetorial", "hibrido") else None,
        "recall@1": round(recall(1), 3), "recall@3": round(recall(3), 3), "recall@5": round(recall(5), 3),
        "mrr@5": round(sum(1 / p for p in posicoes if p) / len(posicoes), 3),
        "recall@3_por_tipo": {t: round(recall(3, l), 2) for t, l in por_tipo.items()},
        "auroc_nao_sei": round(auroc(resp, nao), 3),
        "auroc_nao_sei_dificeis": round(auroc(resp, dificeis), 3),
        "nao_sei_com_calibracao_cruzada": {k: round(v, 3) for k, v in recusa_com_calibracao_cruzada([(r, n) for r, n, _ in notas]).items()},
        "latencia_media_ms": round(statistics.mean(latencias)),
        "latencia_p95_ms": round(sorted(latencias)[int(0.95 * len(latencias)) - 1]),
    }


def construir_colecao(cliente, nome: str, modo_indexacao: str, embedding_fn):
    from indexacao import EXTENSOES, extrair_paginas, montar_blocos
    colecao = cliente.get_or_create_collection(nome, embedding_function=embedding_fn, metadata={"hnsw:space": "cosine"})
    for arquivo in sorted(f for f in os.listdir(CORPUS) if f.lower().endswith(EXTENSOES)):
        textos, metas, ids = montar_blocos(arquivo, extrair_paginas(str(CORPUS / arquivo)), modo=modo_indexacao)
        colecao.upsert(documents=textos, metadatas=metas, ids=ids)
    return colecao


def avaliar(modos=None, indexacoes=("plano", "contextual")) -> dict:
    import chromadb
    from core.embeddings import EmbeddingFunctionMultilingue
    from recuperacao import MODOS, Recuperador

    gabarito = carregar_gabarito()
    shutil.rmtree(PASTA_TEMP, ignore_errors=True)
    cliente = chromadb.PersistentClient(path=str(PASTA_TEMP))
    ef = EmbeddingFunctionMultilingue()
    resultados = {}
    for indexacao in indexacoes:
        colecao = construir_colecao(cliente, f"aval_{indexacao}", indexacao, ef)
        for modo in modos or MODOS:
            m = avaliar_configuracao(Recuperador(colecao, modo), gabarito)
            m["blocos"] = colecao.count()
            resultados[f"{indexacao}+{modo}"] = m
    destino = BASE / "resultados"
    destino.mkdir(exist_ok=True)
    resumo = {"perguntas": len(gabarito), "resultados": resultados}
    (destino / "avaliacao_recuperacao.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(PASTA_TEMP, ignore_errors=True)
    return resumo


def imprimir(resumo: dict) -> None:
    print(f"\n{resumo['perguntas']} perguntas. Cada linha = forma de indexar + modo de busca.\n")
    print("| Configuração | recall@1 | recall@3 | recall@5 | MRR@5 | AUROC não-sei | AUROC difíceis | latência média (p95) |")
    print("|---|---|---|---|---|---|---|---|")
    for nome, m in resumo["resultados"].items():
        print(f"| {nome} | {m['recall@1']} | {m['recall@3']} | {m['recall@5']} | {m['mrr@5']} | {m['auroc_nao_sei']} | "
              f"{m['auroc_nao_sei_dificeis']} | {m['latencia_media_ms']} ms ({m['latencia_p95_ms']}) |")
    print("\nRecall@3 por tipo de pergunta:")
    for nome, m in resumo["resultados"].items():
        print(f"  {nome:28s} {m['recall@3_por_tipo']}")
    print("\n'Não sei' com calibração cruzada (corte escolhido em metade das perguntas, medido na outra):")
    for nome, m in resumo["resultados"].items():
        c = m["nao_sei_com_calibracao_cruzada"]
        print(f"  {nome:28s} responde o que tem resposta: {c['acerta_o_que_tem_resposta']:.0%} | recusa o que não tem: {c['recusa_o_que_nao_tem']:.0%}")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    imprimir(avaliar())
