"""
Quanto do que o monitor mostraria é ruído?

Num serviço pago essa é a pergunta que decide se o cliente continua lendo o Radar. Até aqui o projeto só tinha
limiares chutados; aqui eles ganham um número.

O que dá para medir e o que NÃO dá:

  - **Precisão** (dá): dos itens que eu mostraria, quantos uma pessoa jogaria fora. É o que incomoda o cliente.
  - **Cobertura / recall** (não dá): quantas notícias relevantes deixaram de ser coletadas. Para saber isso seria
    preciso uma lista do que existe no mundo, que ninguém tem. Qualquer número de recall aqui seria invenção.

Os rótulos vêm da revisão (descartar = ruído, sobreviver a um Radar aprovado = útil) ou da rotulagem à mão.
Um rótulo é opinião de quem revisou, não verdade absoluta: com um revisor só, mede o caso óbvio.
"""
from collections import defaultdict

PISO_PARA_OPINAR = 10          # abaixo disso a taxa é ruído estatístico, e o relatório diz isso em vez de um número


def _taxa(parte: int, total: int):
    return round(parte / total, 3) if total else None


def _agrupar(rotulos: list, chave: str) -> list:
    grupos = defaultdict(lambda: {"rotulados": 0, "ruido": 0})
    for rotulo in rotulos:
        alvo = grupos[rotulo.get(chave) or "(sem informação)"]
        alvo["rotulados"] += 1
        alvo["ruido"] += 0 if rotulo["relevante"] else 1
    saida = [{chave: nome, **dados, "taxa_de_ruido": _taxa(dados["ruido"], dados["rotulados"])}
             for nome, dados in grupos.items()]
    return sorted(saida, key=lambda d: (-d["ruido"], -d["rotulados"]))


def medir(base, cliente_id=None) -> dict:
    """Devolve as métricas a partir dos rótulos existentes. Sem rótulo nenhum, devolve o estado vazio."""
    rotulos = base.rotulos(cliente_id)
    total = len(rotulos)
    ruido = sum(1 for r in rotulos if not r["relevante"])
    por_origem = defaultdict(int)
    for rotulo in rotulos:
        por_origem[rotulo["origem"]] += 1

    guardados = base.contagem(cliente_id)["total"]
    return {
        "cliente": cliente_id,
        "eventos_na_base": guardados,
        "rotulados": total,
        "cobertura_da_rotulagem": _taxa(total, guardados),
        "uteis": total - ruido,
        "ruido": ruido,
        "taxa_de_ruido": _taxa(ruido, total),
        "confiavel": total >= PISO_PARA_OPINAR,
        "piso_para_opinar": PISO_PARA_OPINAR,
        "por_origem": dict(por_origem),
        "por_alvo": _agrupar(rotulos, "alvo_id"),
        "por_fonte": _agrupar(rotulos, "fonte"),
        "por_motivo": _motivos(rotulos),
    }


def _motivos(rotulos: list) -> list:
    """Por que o ruído é ruído. Uma taxa sozinha não diz o que consertar; o motivo diz."""
    contagem = defaultdict(int)
    for rotulo in rotulos:
        if not rotulo["relevante"]:
            contagem[rotulo["motivo"] or "(sem motivo)"] += 1
    total = sum(contagem.values())
    return sorted(({"motivo": m, "quantos": q, "fatia_do_ruido": _taxa(q, total)} for m, q in contagem.items()),
                  key=lambda d: -d["quantos"])


def leitura(metricas: dict) -> list:
    """Frases prontas sobre o que os números dizem — e sobre o que eles não autorizam a dizer."""
    if not metricas["rotulados"]:
        return ["Nenhum item rotulado ainda. Revise um Radar (o que você descartar e o que aprovar viram rótulos) "
                "ou rotule uma amostra à mão."]
    linhas = []
    if not metricas["confiavel"]:
        linhas.append(f"Só {metricas['rotulados']} item(ns) rotulado(s): pouco para uma taxa. "
                      f"A partir de {metricas['piso_para_opinar']} o número começa a valer.")
    else:
        taxa = metricas["taxa_de_ruido"]
        linhas.append(f"De cada 10 itens que o monitor mostraria, cerca de {taxa * 10:.0f} seriam descartados "
                      f"na revisão ({metricas['ruido']} de {metricas['rotulados']}).")
    principal = metricas["por_motivo"][0] if metricas["por_motivo"] else None
    if principal and principal["fatia_do_ruido"] and principal["fatia_do_ruido"] >= 0.25:
        linhas.append(f"O motivo mais comum do ruído é '{principal['motivo']}' "
                      f"({principal['quantos']} itens, {principal['fatia_do_ruido']:.0%} do descarte). "
                      "É por aí que se ganha mais mexendo.")
    piores = [a for a in metricas["por_alvo"] if a["rotulados"] >= 5 and (a["taxa_de_ruido"] or 0) >= 0.4]
    for alvo in piores[:3]:
        linhas.append(f"O alvo '{alvo['alvo_id']}' traz muito ruído ({alvo['taxa_de_ruido']:.0%}): provavelmente "
                      "os termos de busca dele estão amplos demais ou precisam de um tema para desambiguar.")
    fontes_ruins = [f for f in metricas["por_fonte"] if f["rotulados"] >= 3 and (f["taxa_de_ruido"] or 0) == 1.0]
    if fontes_ruins:
        nomes = ", ".join(f["fonte"] for f in fontes_ruins[:4])
        linhas.append(f"Fonte(s) que só trouxeram ruído até agora: {nomes}.")
    linhas.append("Isto mede precisão (o que aparece e não deveria), não cobertura: o que o monitor deixou de "
                  "encontrar no mundo não está aqui e não dá para estimar com estes dados.")
    return linhas
