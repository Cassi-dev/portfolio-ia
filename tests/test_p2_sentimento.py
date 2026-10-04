import json
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from analise_estatistica import (
    acuracia_de_sinal,
    correlacao_com_defasagem,
    p_valor_binomial,
    sinal_atual,
    veredito,
)
from analise_sentimento import aplicar_decaimento_temporal, pontuar_por_lexico, pontuar_sentimento_llm
from coleta_noticias import calcular_similaridade, deduplicar, filtrar_por_data, limpar_titulo, montar_url
from cruzamento_precos import cruzar_sentimento_com_precos, data_de_impacto, mercado_do_ticker


def noticias(*titulos):
    return [{"titulo": t, "data": "2026-09-18"} for t in titulos]


def resposta(*itens):
    return json.dumps([
        {"indice": i, "score": s, "classificacao": c, "motivo": "m"} for i, s, c in itens
    ])


# --- coleta ---------------------------------------------------------------

def test_limpar_titulo_remove_a_fonte_no_final():
    assert limpar_titulo("Petrobras sobe 3% - InfoMoney") == "Petrobras sobe 3%"


def test_similaridade_e_deduplicacao():
    assert calcular_similaridade("Petrobras anuncia dividendos", "Petrobras anuncia dividendos") == 1.0
    assert calcular_similaridade("Petrobras anuncia dividendos", "Vale amplia produção minério") == 0.0
    itens = [
        {"titulo": "Petrobras anuncia dividendos extraordinários bilhões"},
        {"titulo": "Petrobras anuncia dividendos extraordinários bilhões hoje"},
        {"titulo": "Vale amplia produção de minério"},
    ]
    assert len(deduplicar(itens)) == 2


def test_consulta_usa_nome_da_empresa_parenteses_e_janela():
    url = montar_url("PETR4.SA", 30)
    assert "when%3A30d" in url and "%28%22Petrobras%22%20OR%20PETR4%29" in url and "hl=pt-BR" in url
    assert "hl=en-US" in montar_url("AAPL", 30) and "earnings" in montar_url("AAPL", 30)


def test_filtro_de_janela_descarta_o_que_e_antigo():
    hoje = date(2026, 9, 18)
    itens = [{"data": "2026-09-10"}, {"data": "2026-08-01"}]
    assert filtrar_por_data(itens, 30, hoje=hoje) == [{"data": "2026-09-10"}]


# --- decaimento e sinal ----------------------------------------------------

def test_decaimento_dobra_a_cada_meia_vida():
    hoje = date.today()
    itens = [
        {"titulo": "a", "data": hoje.isoformat(), "score": 1.0},
        {"titulo": "b", "data": (hoje - timedelta(days=5)).isoformat(), "score": 1.0},
    ]
    aplicar_decaimento_temporal(itens, meia_vida_dias=5)
    assert itens[0]["peso_temporal"] == 1.0
    assert itens[1]["peso_temporal"] == 0.5 and itens[1]["score_ponderado"] == 0.5


def test_sinal_atual_pesa_mais_o_recente():
    itens = [{"score": 1.0, "peso_temporal": 1.0}, {"score": -1.0, "peso_temporal": 0.25}]
    assert sinal_atual(itens) == pytest.approx(0.6)
    assert sinal_atual([]) is None


# --- pontuação: motor, fallback e léxico ------------------------------------

def test_sem_chave_tudo_cai_no_lexico_com_motivo():
    itens = pontuar_sentimento_llm(noticias("Petrobras paga dividendos recorde", "Petrobras enfrenta multa"))
    assert all(n["motor"] == "lexico" for n in itens)
    assert all("sem chave" in n["motivo_motor"] for n in itens)
    assert itens[0]["score"] > 0 > itens[1]["score"]


def test_ia_valida_pontua_e_marca_o_motor(cliente_falso):
    cliente = cliente_falso(resposta((0, 0.9, "Otimista"), (1, -0.5, "Pessimista")))
    itens = pontuar_sentimento_llm(noticias("A", "B"), client=cliente)
    assert [n["motor"] for n in itens] == ["gemini", "gemini"]
    assert [n["score"] for n in itens] == [0.9, -0.5]


def test_ia_que_omite_um_indice_nao_quebra_o_decaimento(cliente_falso):
    itens = pontuar_sentimento_llm(noticias("Manchete A", "Manchete B"), client=cliente_falso(resposta((0, 0.9, "Otimista"))))
    assert [n["motor"] for n in itens] == ["gemini", "lexico"]
    assert "não devolveu" in itens[1]["motivo_motor"]
    aplicar_decaimento_temporal(itens)
    assert all("score_ponderado" in n for n in itens)


def test_score_fora_da_faixa_e_rejeitado_e_vira_aviso(cliente_falso):
    itens = pontuar_sentimento_llm(noticias("Manchete A"), client=cliente_falso(resposta((0, 7, "Otimista"))))
    assert itens[0]["motor"] == "lexico" and "formato" in itens[0]["motivo_motor"]


def test_falha_da_api_cai_no_lexico_e_informa_o_erro(cliente_falso):
    itens = pontuar_sentimento_llm(noticias("Manchete A"), client=cliente_falso(RuntimeError("cota esgotada")))
    assert itens[0]["motor"] == "lexico"
    assert "falha na chamada da IA" in itens[0]["motivo_motor"] and "cota esgotada" in itens[0]["motivo_motor"]


def test_resposta_com_cerca_markdown_e_aceita(cliente_falso):
    cliente = cliente_falso("```json\n" + resposta((0, -0.6, "Pessimista")) + "\n```")
    itens = pontuar_sentimento_llm(noticias("Manchete A"), client=cliente)
    assert itens[0]["motor"] == "gemini" and itens[0]["score"] == -0.6


@pytest.mark.parametrize("titulo,esperado", [
    ("Malta abre escritório em Lisboa", 0),
    ("Caixa anuncia programa de crédito", 0),
    ("Petrobras paga dividendo e dividendos recorde", 0.8),
    ("Lucro cai menos que o esperado", 0.8),
    ("Queda menor que a esperada surpreende mercado", 0.4),
    ("Vale fica abaixo do consenso no trimestre", -0.4),
    ("Petrobras enfrenta multa e investigação", -0.8),
])
def test_lexico(titulo, esperado):
    assert pontuar_por_lexico(titulo) == pytest.approx(esperado)


# --- calendário de pregão e cruzamento ---------------------------------------

def utc(ano, mes, dia, hora=15):
    return datetime(ano, mes, dia, hora, tzinfo=timezone.utc)


PREGOES = [date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 14), date(2026, 9, 15)]  # 12 e 13 = fim de semana


def test_noticia_de_sabado_e_domingo_vai_para_segunda():
    assert data_de_impacto(utc(2026, 9, 12), PREGOES) == date(2026, 9, 14)
    assert data_de_impacto(utc(2026, 9, 13), PREGOES) == date(2026, 9, 14)


def test_noticia_depois_do_fechamento_vale_para_o_pregao_seguinte():
    # 17h30 em São Paulo = 20h30 UTC; 13h em São Paulo = 16h UTC
    assert data_de_impacto(utc(2026, 9, 10, 20), PREGOES) == date(2026, 9, 11)
    assert data_de_impacto(utc(2026, 9, 10, 16), PREGOES) == date(2026, 9, 10)


def test_feriado_cai_no_proximo_pregao_que_existe():
    sem_dia_10 = [d for d in PREGOES if d != date(2026, 9, 10)]
    assert data_de_impacto(utc(2026, 9, 10, 16), sem_dia_10) == date(2026, 9, 11)


def test_noticia_depois_do_ultimo_pregao_nao_tem_preco_para_comparar():
    assert data_de_impacto(utc(2026, 9, 16), PREGOES) is None
    assert data_de_impacto(utc(2026, 9, 15, 20), PREGOES) is None


def test_mercado_do_ticker():
    assert [mercado_do_ticker(t) for t in ["PETR4.SA", "VALE3", "AAPL"]] == ["BR", "BR", "US"]


def df_precos():
    return pd.DataFrame({"Data": PREGOES, "Preco_Fechamento": [10.0, 10.5, 10.0, 10.2, 10.6], "Volume": 1})


def test_cruzamento_agrupa_por_pregao_e_suaviza_com_media_exponencial():
    itens = [
        {"titulo": "a", "score": 0.8, "publicado_em": utc(2026, 9, 12).isoformat(), "data": "2026-09-12"},   # sábado -> 14
        {"titulo": "b", "score": 0.4, "publicado_em": utc(2026, 9, 13).isoformat(), "data": "2026-09-13"},   # domingo -> 14
        {"titulo": "c", "score": 0.5, "publicado_em": utc(2026, 9, 20).isoformat(), "data": "2026-09-20"},   # depois do fim da série
    ]
    df = cruzar_sentimento_com_precos(itens, df_precos(), meia_vida_dias=1)
    dia14 = df[df["Data"] == date(2026, 9, 14)].iloc[0]
    assert dia14["Qtd_Noticias"] == 2 and dia14["Sentimento_Medio"] == pytest.approx(0.6)
    assert df["Qtd_Noticias"].sum() == 2
    # meia-vida de 1 dia: a média móvel absorve metade do 0,6 no próprio dia e a metade disso no dia seguinte
    assert dia14["Sentimento_Ponderado"] == pytest.approx(0.3)
    dia15 = df[df["Data"] == date(2026, 9, 15)].iloc[0]
    assert dia15["Sentimento_Ponderado"] == pytest.approx(0.15)
    assert df["Retorno_Pct"].iloc[1] == pytest.approx(5.0)


def test_cruzamento_sem_nenhuma_noticia_no_periodo_nao_quebra():
    itens = [{"titulo": "a", "score": 0.5, "publicado_em": utc(2026, 9, 20).isoformat(), "data": "2026-09-20"}]
    df = cruzar_sentimento_com_precos(itens, df_precos())
    assert df["Qtd_Noticias"].sum() == 0 and (df["Sentimento_Medio"] == 0).all()


# --- estatística -------------------------------------------------------------

def test_p_valor_binomial_conhecido():
    assert p_valor_binomial(0, 10) == pytest.approx(1.0)
    assert p_valor_binomial(10, 10) == pytest.approx(0.5**10)
    assert p_valor_binomial(6, 10) == pytest.approx(0.377, abs=0.001)


def serie(sentimentos, retornos):
    return pd.DataFrame({
        "Sentimento_Medio": sentimentos, "Retorno_Pct": retornos, "Qtd_Noticias": [1] * len(sentimentos),
    })


def test_acuracia_de_sinal_conta_so_dias_validos_e_compara_com_baseline():
    df = serie([0.5, -0.5, 0.5, 0.0, 0.5], [1.0, -1.0, -1.0, 2.0, float("nan")])
    est = acuracia_de_sinal(df)
    assert (est["n_dias"], est["acertos"]) == (3, 2)
    assert est["taxa"] == pytest.approx(2 / 3) and est["baseline"] == pytest.approx(2 / 3)
    assert est["vantagem"] == pytest.approx(0.0)


def test_acuracia_sem_dias_validos():
    assert acuracia_de_sinal(serie([0.0], [1.0]))["n_dias"] == 0


def test_correlacao_com_defasagem_acha_o_atraso_certo():
    sentimento = [0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0]
    retorno = [0.0] + sentimento[:-1]                 # o retorno repete o sentimento do pregão anterior
    tabela = correlacao_com_defasagem(serie(sentimento, retorno), max_defasagem=3)
    assert tabela.loc[tabela["Correlacao"].idxmax(), "Defasagem_pregoes"] == 1
    assert tabela["Correlacao"].max() == pytest.approx(1.0)


def test_veredito_exige_amostra_minima():
    pequena = {"n_dias": 10, "p_valor": 0.001, "vantagem": 0.3}
    assert "não conclusivo" in veredito(pequena)
    grande = {"n_dias": 60, "p_valor": 0.01, "vantagem": 0.2}
    assert "significância" in veredito(grande)
    assert "Sem vantagem" in veredito({"n_dias": 60, "p_valor": 0.4, "vantagem": 0.05})
