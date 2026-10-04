"""
PROCESSO 4: calibração de tamanho de chunk e do limiar do "modo não sei".

O e-book pede duas coisas que ninguém faz por preguiça:
1. Testar 256 / 512 / 1024 com as mesmas perguntas e comparar.
2. Medir o limiar do "não sei" em vez de chutar um número.

Este script faz as duas com um gabarito de perguntas: parte tem resposta nos documentos (com o
arquivo esperado), parte é proposital fora do assunto. Para cada tamanho de chunk, reindexa tudo
numa coleção temporária (com o MESMO divisor de blocos do app) e mede: acurácia top-1, recall@3,
distância das perguntas respondíveis e das perguntas fora do domínio. O limiar sugerido é o ponto
médio entre as duas distribuições.
"""
import os
import shutil
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import chromadb

from core.embeddings import EmbeddingFunctionMultilingue
from indexacao import EXTENSOES, extrair_paginas, montar_blocos

BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_DOCUMENTOS = os.path.join(BASE, "documentos")
PASTA_BANCO_TEMP = os.path.join(BASE, "banco_vetorial_calibracao")
TAMANHOS_TESTADOS = [256, 512, 1024]
SOBREPOSICAO_PCT = 0.15
K_RECALL = 3

GABARITO = [
    {"pergunta": "Quantos dias tenho para pedir reembolso integral?", "arquivo_esperado": "politica_reembolso_e_ti.txt"},
    {"pergunta": "Qual o prazo de resposta para um chamado de prioridade alta?", "arquivo_esperado": "politica_reembolso_e_ti.txt"},
    {"pergunta": "Qual o tamanho de bloco recomendado para testar no RAG?", "arquivo_esperado": "exercicio_1_roteiro_rag.md"},
    {"pergunta": "Com que ferramenta devo gerar os embeddings dos documentos?", "arquivo_esperado": "exercicio_1_roteiro_rag.md"},
    # fora do domínio: propositalmente sem relação com nenhum documento indexado
    {"pergunta": "Qual é a melhor receita de pudim de leite condensado?", "arquivo_esperado": None},
    {"pergunta": "Quem foi o primeiro presidente do Brasil?", "arquivo_esperado": None},
    {"pergunta": "Como faço para trocar o pneu de um carro?", "arquivo_esperado": None},
]


def carregar_documentos():
    arquivos = sorted(f for f in os.listdir(PASTA_DOCUMENTOS) if f.lower().endswith(EXTENSOES))
    documentos = [(nome, extrair_paginas(os.path.join(PASTA_DOCUMENTOS, nome))) for nome in arquivos]
    return [(nome, paginas) for nome, paginas in documentos if paginas]


def indexar_com_tamanho(colecao, documentos, tamanho_chunk):
    sobreposicao = int(tamanho_chunk * SOBREPOSICAO_PCT)
    textos, metas, ids = [], [], []
    for nome, paginas in documentos:
        t, m, i = montar_blocos(nome, paginas, tamanho=tamanho_chunk, sobreposicao=sobreposicao)
        textos += t
        metas += m
        ids += i
    colecao.upsert(documents=textos, metadatas=metas, ids=ids)
    return len(ids)


def avaliar(colecao):
    dist_ok, dist_fora, acertos, no_topo_k = [], [], 0, 0
    respondiveis = [g for g in GABARITO if g["arquivo_esperado"]]

    for item in GABARITO:
        resultado = colecao.query(query_texts=[item["pergunta"]], n_results=K_RECALL, include=["metadatas", "distances"])
        distancia = resultado["distances"][0][0]
        arquivos = [m["arquivo"] for m in resultado["metadatas"][0]]

        if item["arquivo_esperado"]:
            dist_ok.append(distancia)
            acertos += arquivos[0] == item["arquivo_esperado"]
            no_topo_k += item["arquivo_esperado"] in arquivos
        else:
            dist_fora.append(distancia)

    return acertos / len(respondiveis), no_topo_k / len(respondiveis), dist_ok, dist_fora


def main():
    documentos = carregar_documentos()
    if not documentos:
        print("Nenhum documento com texto em 'documentos/'.")
        return

    shutil.rmtree(PASTA_BANCO_TEMP, ignore_errors=True)
    cliente = chromadb.PersistentClient(path=PASTA_BANCO_TEMP)
    embedding_fn = EmbeddingFunctionMultilingue()

    print("=" * 78)
    print("  CALIBRAÇÃO: TAMANHO DE CHUNK x LIMIAR DO MODO 'NÃO SEI'")
    print("=" * 78)

    resultados = []
    for tamanho in TAMANHOS_TESTADOS:
        colecao = cliente.get_or_create_collection(
            name=f"calib_{tamanho}", embedding_function=embedding_fn, metadata={"hnsw:space": "cosine"}
        )
        n_blocos = indexar_com_tamanho(colecao, documentos, tamanho)
        acuracia, recall, dist_ok, dist_fora = avaliar(colecao)

        pior_ok, pior_fora = max(dist_ok), min(dist_fora)
        margem = pior_fora - pior_ok
        limiar = (pior_ok + pior_fora) / 2
        resultados.append({"tamanho": tamanho, "acuracia": acuracia, "recall": recall, "margem": margem, "limiar": limiar})

        print(f"\n--- Chunk = {tamanho} caracteres ({n_blocos} blocos) ---")
        print(f"  Acurácia top-1: {acuracia * 100:.0f}% | recall@{K_RECALL}: {recall * 100:.0f}%")
        print(f"  Distância perguntas respondíveis: média {sum(dist_ok) / len(dist_ok):.4f} (pior {pior_ok:.4f})")
        print(f"  Distância perguntas fora do domínio: média {sum(dist_fora) / len(dist_fora):.4f} (melhor {pior_fora:.4f})")
        if margem > 0:
            print(f"  ✅ Há separação de {margem:.4f}. Limiar sugerido: {limiar:.4f}")
        else:
            print(f"  ⚠️ Sem separação clara (margem {margem:.4f}): este tamanho não discrimina bem.")

    melhor = max(resultados, key=lambda r: (r["acuracia"], r["margem"]))
    print("\n" + "=" * 78)
    print(f"  RECOMENDAÇÃO: TAMANHO_CHUNK = {melhor['tamanho']}, LIMIAR_DISTANCIA = {melhor['limiar']:.2f}")
    print(f"  (acurácia {melhor['acuracia'] * 100:.0f}%, recall@{K_RECALL} {melhor['recall'] * 100:.0f}%, margem {melhor['margem']:.4f})")
    print("=" * 78)

    shutil.rmtree(PASTA_BANCO_TEMP, ignore_errors=True)


if __name__ == "__main__":
    main()
