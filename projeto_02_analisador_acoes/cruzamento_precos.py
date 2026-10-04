import sys
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# ==========================================================
# PROCESSO 3: SÉRIE TEMPORAL, CALENDÁRIO DE PREGÃO & ALINHAMENTO
# ==========================================================

MERCADOS = {
    "BR": {"tz": "America/Sao_Paulo", "fechamento": 17},
    "US": {"tz": "America/New_York", "fechamento": 16},
}


def mercado_do_ticker(ticker):
    t = ticker.upper().strip()
    return "BR" if t.endswith(".SA") or t[-1:].isdigit() else "US"


def obter_historico_precos(ticker="PETR4.SA", periodo="1mo"):
    """Baixa os preços de fechamento diários via yfinance (adiciona .SA em tickers da B3)."""
    ticker_busca = ticker.upper().strip()
    if not ticker_busca.endswith(".SA") and len(ticker_busca) in [5, 6] and ticker_busca[-1].isdigit():
        ticker_busca = f"{ticker_busca}.SA"

    print(f"Baixando série histórica de preços para '{ticker_busca}' ({periodo})...")
    df_precos = yf.Ticker(ticker_busca).history(period=periodo)

    if df_precos.empty:
        print(f"[Erro] Nenhum dado de preço encontrado para {ticker_busca}")
        return pd.DataFrame()

    df_precos.reset_index(inplace=True)
    df_precos['Data'] = pd.to_datetime(df_precos['Date']).dt.tz_localize(None).dt.date
    df_precos = df_precos[['Data', 'Close', 'Volume']]
    df_precos.rename(columns={'Close': 'Preco_Fechamento'}, inplace=True)
    return df_precos


def data_de_impacto(publicado_em, dias_pregao, mercado="BR"):
    """
    Primeiro pregão em que a notícia pode ter refletido no preço.
    - notícia publicada depois do fechamento (17h em SP, 16h em NY) vale para o dia seguinte;
    - fim de semana e feriado caem no próximo pregão que existe na série de preços;
    - notícia depois do último pregão da série ainda não tem preço para comparar: devolve None.
    `dias_pregao` é uma lista ordenada de datas com cotação (o próprio calendário do yfinance).
    """
    cfg = MERCADOS[mercado]
    local = publicado_em.astimezone(ZoneInfo(cfg["tz"]))
    dia = local.date()
    if local.hour >= cfg["fechamento"]:
        dia += timedelta(days=1)
    i = bisect_left(dias_pregao, dia)
    return dias_pregao[i] if i < len(dias_pregao) else None


def _publicado_em(noticia, mercado):
    if noticia.get("publicado_em"):
        return datetime.fromisoformat(noticia["publicado_em"])
    # Sem horário (dado antigo): assume meio do pregão, para não empurrar a notícia para o dia seguinte
    d = date.fromisoformat(noticia["data"])
    return datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo(MERCADOS[mercado]["tz"])).astimezone(timezone.utc)


def mapear_datas_de_impacto(noticias, dias_pregao, mercado="BR"):
    for n in noticias:
        n["data_impacto"] = data_de_impacto(_publicado_em(n, mercado), dias_pregao, mercado)
    return noticias


def cruzar_sentimento_com_precos(noticias_pontuadas, df_precos, mercado="BR", meia_vida_dias=5):
    """
    Uma linha por pregão: preço, retorno, sentimento médio das notícias que impactam aquele
    pregão e o sentimento suavizado por média móvel exponencial (o efeito das notícias se dilui
    com a meia-vida, dia a dia, em vez de ser medido contra "hoje").
    """
    if not noticias_pontuadas or df_precos.empty:
        return pd.DataFrame()

    dias_pregao = sorted(df_precos["Data"])
    mapear_datas_de_impacto(noticias_pontuadas, dias_pregao, mercado)
    mapeadas = [n for n in noticias_pontuadas if n["data_impacto"] is not None]

    sentimento_diario = pd.DataFrame(mapeadas, columns=["data_impacto", "score", "titulo"]).groupby("data_impacto").agg(
        Sentimento_Medio=("score", "mean"),
        Qtd_Noticias=("titulo", "count"),
    ).reset_index().rename(columns={"data_impacto": "Data"})

    df = pd.merge(df_precos, sentimento_diario, on="Data", how="left")
    df["Sentimento_Medio"] = df["Sentimento_Medio"].fillna(0.0)
    df["Qtd_Noticias"] = df["Qtd_Noticias"].fillna(0).astype(int)
    df["Sentimento_Ponderado"] = df["Sentimento_Medio"].ewm(halflife=meia_vida_dias, adjust=False).mean()
    df["Retorno_Pct"] = df["Preco_Fechamento"].pct_change() * 100
    return df


if __name__ == "__main__":
    df_p = obter_historico_precos("PETR4.SA", periodo="1mo")
    hoje = datetime.now(timezone.utc)
    noticias_teste = [
        {"titulo": "Petrobras paga dividendos", "data": hoje.date().isoformat(), "publicado_em": hoje.isoformat(), "score": 0.8},
    ]
    df_final = cruzar_sentimento_com_precos(noticias_teste, df_p)
    print(df_final.tail(7)[["Data", "Preco_Fechamento", "Retorno_Pct", "Sentimento_Medio", "Sentimento_Ponderado", "Qtd_Noticias"]])
