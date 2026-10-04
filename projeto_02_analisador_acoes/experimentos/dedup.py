"""
Qual regra de deduplicação colapsa cada história repetida em UM item, sem juntar notícias diferentes?

A primeira versão deste experimento estava errada: eu contava acerto só quando a regra mantinha exatamente a
variante que eu havia marcado como "a boa". Para o cliente tanto faz qual das cinco sobra — o que importa é
sobrar uma. Aqui cada história repetida tem um grupo, e a medida é:

  - repetições removidas: quantos itens a menos, dentro dos grupos (o ideal é 21, deixando 1 por grupo)
  - fusões erradas: itens barrados por uma notícia de OUTRA história (o erro caro: some notícia de verdade)

Resultado que decidiu o código: jaccard >= 0,60 (o que estava no ar) pegava 0 de 21; embedding com cosseno
>= 0,93 pega 11 de 21, com 1 fusão errada. Ver ../deduplicacao.py.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "projeto_02_analisador_acoes"))
sys.path.insert(0, str(RAIZ))
ROTULOS = RAIZ / "projeto_02_analisador_acoes/dados_medicao/rotulos_80_manchetes.json"

from coleta_noticias import tokenizar  # noqa: E402

# As 11 histórias que saíram repetidas em 2 a 5 portais, identificadas à mão nas 80 manchetes.
GRUPOS = {
    "madero_pinhais": ["faec1dd6f4f27d91", "e132030e3c6dbe45", "4e4fb6085766cee1", "01620159afd0431b"],
    "outback_dentario": ["87ae4e681ad02c50", "d41fa97cbdb503b0", "999beea805b3f5ab", "a31fe33e1dd03959",
                         "b4fa50ba89dfbd6a"],
    "outback_uberaba": ["7c31b681dd488c04", "09558f4cefcc16a6", "5e1204c8b788bb96"],
    "outback_clube": ["6649fe3158c4ffd8", "007b5c780f542dab"],
    "outback_semana_cliente": ["9230125d5828f057", "4d65e0a8ba105729"],
    "setor_crescimento_agosto": ["2ac926d1e8b2a19d", "6a8b61c8a543ed6c", "fcb71de0ec4b41a0"],
    "setor_vendas_julho": ["6031d4dd00d4d5f2", "5091e08bd1f29024", "eaa043136e18646c"],
    "setor_tendencias_ia": ["89970dce02011ef1", "b204761c9edc3e4b", "561095a0245ce18b", "d565163b3d934c2a"],
    "setor_reforma": ["5854250f039838c5", "0dfd8ca3e6bb685b"],
    "setor_feriado": ["8826242f5894ec07", "c11b33879f9f61bd"],
    "setor_connecta": ["4e182d542e3489ff", "468680f7e1f44813"],
}
DE_QUAL_GRUPO = {i: g for g, ids in GRUPOS.items() for i in ids}
IDEAL = sum(len(v) - 1 for v in GRUPOS.values())

# a base compara cada manchete com as que já entraram, então a ordem é da mais antiga para a mais nova
ITENS = list(reversed(json.loads(ROTULOS.read_text(encoding="utf-8"))["manchetes"]))


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def contencao(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def avaliar(semelhanca, limiar, vetor=tokenizar):
    removidas, fusoes_erradas, por_alvo = 0, [], {}
    for item in ITENS:
        representacao = vetor(item["titulo"])
        anteriores = por_alvo.setdefault(item["alvo"], [])
        culpado = next((o for o in anteriores if semelhanca(representacao, o[0]) >= limiar), None)
        if culpado is None:
            anteriores.append((representacao, item))
            continue
        meu, dele = DE_QUAL_GRUPO.get(item["id"]), DE_QUAL_GRUPO.get(culpado[1]["id"])
        if meu is not None and meu == dele:
            removidas += 1
        else:
            fusoes_erradas.append(f"{item['titulo'][:48]}  <=  {culpado[1]['titulo'][:48]}")
    return removidas, fusoes_erradas


def relatar(nome, semelhanca, limiar, vetor=tokenizar):
    removidas, erros = avaliar(semelhanca, limiar, vetor)
    print(f"{nome:<36}{removidas:>3} de {IDEAL:<6}{len(erros):>6} fusão(ões) errada(s)")
    for erro in erros[:2]:
        print(f"{'':<38}{erro}")


def main():
    print(f"{len(ITENS)} manchetes | {len(GRUPOS)} histórias repetidas | ideal: remover {IDEAL}\n")
    print(f"{'regra':<36}{'repetições removidas':>13}")
    print("-" * 78)
    for limiar in (0.60, 0.50, 0.40, 0.35, 0.30):
        relatar(f"jaccard >= {limiar:.2f}" + (" (o de antes)" if limiar == 0.60 else ""), jaccard, limiar)
    for limiar in (0.70, 0.60, 0.50, 0.45):
        relatar(f"contenção >= {limiar:.2f}", contencao, limiar)

    try:
        from core.embeddings import embed_textos
    except ImportError as erro:
        print(f"\n(embeddings indisponíveis: {erro})")
        return
    print("\nCarregando o modelo de embeddings (multilingual-e5-small)...")
    titulos = [i["titulo"] for i in ITENS]
    vetores = dict(zip(titulos, embed_textos(titulos)))

    def cosseno(a, b):
        return sum(x * y for x, y in zip(a, b))          # e5 já devolve vetores normalizados

    print()
    for limiar in (0.95, 0.93, 0.91, 0.90, 0.88):
        relatar(f"embedding, cosseno >= {limiar:.2f}", cosseno, limiar, vetor=lambda t: vetores[t])


if __name__ == "__main__":
    main()
