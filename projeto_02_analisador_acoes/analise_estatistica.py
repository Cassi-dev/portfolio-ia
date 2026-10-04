"""Estatística mínima para não confundir coincidência com sinal (o e-book: "correlação não é sinal")."""
from math import comb

import pandas as pd

AMOSTRA_MINIMA = 30


def p_valor_binomial(acertos, n, p0=0.5):
    """P(X >= acertos) para X ~ Binomial(n, p0): chance de acertar tanto ou mais só por sorte."""
    if n == 0:
        return 1.0
    return min(1.0, sum(comb(n, k) * p0**k * (1 - p0) ** (n - k) for k in range(acertos, n + 1)))


def acuracia_de_sinal(df):
    """
    O sinal de sentimento do dia acerta a direção do retorno do mesmo dia?
    Só conta dias com notícia, sentimento diferente de zero e retorno diferente de zero.
    O baseline é o melhor palpite constante ("sempre sobe" ou "sempre desce") nesses mesmos dias.
    """
    base = df[(df["Qtd_Noticias"] > 0) & (df["Sentimento_Medio"] != 0) & df["Retorno_Pct"].notna() & (df["Retorno_Pct"] != 0)]
    n = len(base)
    if n == 0:
        return {"n_dias": 0, "acertos": 0, "taxa": 0.0, "baseline": 0.0, "vantagem": 0.0, "p_valor": 1.0}

    acertos = int(((base["Sentimento_Medio"] > 0) == (base["Retorno_Pct"] > 0)).sum())
    subiu = float((base["Retorno_Pct"] > 0).mean())
    baseline = max(subiu, 1 - subiu)
    taxa = acertos / n
    return {
        "n_dias": n,
        "acertos": acertos,
        "taxa": taxa,
        "baseline": baseline,
        "vantagem": taxa - baseline,
        "p_valor": p_valor_binomial(acertos, n, baseline),
    }


def correlacao_com_defasagem(df, max_defasagem=5):
    """Correlação entre o sentimento de k pregões atrás e o retorno de hoje, para k = 0..max."""
    linhas = []
    for k in range(max_defasagem + 1):
        par = pd.DataFrame({"x": df["Sentimento_Medio"].shift(k), "y": df["Retorno_Pct"]}).dropna()
        correlacao = par["x"].corr(par["y"]) if len(par) > 2 and par["x"].std() > 0 and par["y"].std() > 0 else float("nan")
        linhas.append({"Defasagem_pregoes": k, "Correlacao": correlacao, "N": len(par)})
    return pd.DataFrame(linhas)


def sinal_atual(noticias):
    """Média dos scores ponderada pelo peso temporal (o que está fresco pesa mais). None sem notícias."""
    pesos = sum(n.get("peso_temporal", 1.0) for n in noticias)
    if not noticias or pesos == 0:
        return None
    return sum(n["score"] * n.get("peso_temporal", 1.0) for n in noticias) / pesos


def veredito(estatisticas):
    if estatisticas["n_dias"] < AMOSTRA_MINIMA:
        return f"Amostra pequena ({estatisticas['n_dias']} dias, o mínimo razoável é {AMOSTRA_MINIMA}): não conclusivo."
    if estatisticas["p_valor"] < 0.05 and estatisticas["vantagem"] > 0:
        return "Acima do baseline com significância estatística (p < 0,05). Ainda não é recomendação de investimento."
    return "Sem vantagem estatística sobre o baseline."
