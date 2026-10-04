"""
Acurácia de execução do Text-to-SQL: o resultado do SQL gerado é igual ao do SQL escrito à mão?

    python projeto_05_gerador_sql/avaliar_acuracia.py --modo gabarito   # sanidade: o próprio gabarito deve dar 100%
    python projeto_05_gerador_sql/avaliar_acuracia.py --modo offline    # baseline do modo sem IA
    GEMINI_API_KEY=... python projeto_05_gerador_sql/avaliar_acuracia.py --modo gemini

Compara conjuntos de linhas (ordem só importa nas perguntas marcadas "ordenado") e arredonda números
em 2 casas. Nomes de coluna não contam. O resultado vai para resultados/avaliacao_<modo>.json.
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(__file__).resolve().parent
GABARITO = BASE / "perguntas_gabarito.json"


def _valor(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)
    return v


def normalizar_linhas(df: pd.DataFrame):
    return [tuple(_valor(v) for v in linha) for linha in df.itertuples(index=False, name=None)]


def comparar_resultados(esperado: pd.DataFrame, obtido: pd.DataFrame, ordenado: bool = False) -> bool:
    if esperado.shape[1] != obtido.shape[1]:
        return False
    a, b = normalizar_linhas(esperado), normalizar_linhas(obtido)
    if ordenado:
        return a == b
    chave = lambda linha: tuple(str(v) for v in linha)
    return sorted(a, key=chave) == sorted(b, key=chave)


def carregar_gabarito():
    dados = json.loads(GABARITO.read_text(encoding="utf-8"))
    return date.fromisoformat(dados["hoje"]), dados["perguntas"]


def avaliar(modo: str, chave_api: str = ""):
    from banco_dados import executar_consulta, inicializar_banco
    from core import llm
    from motor_text_to_sql import processar_pergunta_com_ciclo_correcao, responder_offline

    inicializar_banco()
    hoje, perguntas = carregar_gabarito()
    client = llm.criar_cliente(chave_api) if modo == "gemini" else None
    llm.historico.clear()

    linhas, por_categoria = [], defaultdict(lambda: [0, 0])
    for item in perguntas:
        esperado = executar_consulta(item["sql"])
        if esperado.erro:
            raise RuntimeError(f"SQL do gabarito falhou ({item['pergunta']}): {esperado.erro}")

        if modo == "gabarito":
            obtido, sql_gerado, degradado = executar_consulta(item["sql"]).df, item["sql"], False
        elif modo == "offline":
            r = responder_offline(item["pergunta"], "avaliação")
            obtido, sql_gerado, degradado = r["df"], r["sql"], True
        else:
            r = processar_pergunta_com_ciclo_correcao(item["pergunta"], client=client, hoje=hoje)
            obtido, sql_gerado, degradado = r["df"], r["sql"], r["degradado"]

        acertou = obtido is not None and comparar_resultados(esperado.df, obtido, item.get("ordenado", False))
        por_categoria[item["categoria"]][0] += int(acertou)
        por_categoria[item["categoria"]][1] += 1
        linhas.append({"pergunta": item["pergunta"], "categoria": item["categoria"], "acertou": bool(acertou),
                       "degradado": degradado, "sql_gerado": sql_gerado, "sql_gabarito": item["sql"]})

    total = sum(l["acertou"] for l in linhas)
    resumo = {
        "modo": modo,
        "acuracia": total / len(linhas),
        "acertos": total,
        "perguntas": len(linhas),
        "por_categoria": {c: {"acertos": a, "total": t, "acuracia": a / t} for c, (a, t) in por_categoria.items()},
        "uso_llm": llm.estatisticas(),
        "resultados": linhas,
    }
    destino = BASE / "resultados"
    destino.mkdir(exist_ok=True)
    (destino / f"avaliacao_{modo}.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def imprimir(resumo):
    print(f"\nModo: {resumo['modo']} | acurácia de execução: {resumo['acuracia'] * 100:.0f}% ({resumo['acertos']}/{resumo['perguntas']})")
    print("\n| Categoria | Acertos | Acurácia |\n|---|---|---|")
    for cat, r in resumo["por_categoria"].items():
        print(f"| {cat} | {r['acertos']}/{r['total']} | {r['acuracia'] * 100:.0f}% |")
    uso = resumo["uso_llm"]
    if uso["chamadas_api"]:
        print(f"\nChamadas à API: {uso['chamadas_api']} | latência média: {uso['latencia_media_ms']} ms | tokens: {uso['tokens_entrada']} entrada / {uso['tokens_saida']} saída")
    erradas = [r for r in resumo["resultados"] if not r["acertou"]]
    if erradas and resumo["modo"] == "gemini":
        print("\nErros:")
        for r in erradas:
            print(f"- {r['pergunta']}\n    gerado:   {r['sql_gerado']}\n    gabarito: {r['sql_gabarito']}")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modo", choices=["gabarito", "offline", "gemini"], default="offline")
    args = parser.parse_args()
    chave = os.environ.get("GEMINI_API_KEY", "")
    if args.modo == "gemini" and not chave:
        sys.exit("Defina a variável de ambiente GEMINI_API_KEY para avaliar com o Gemini.")
    imprimir(avaliar(args.modo, chave))
