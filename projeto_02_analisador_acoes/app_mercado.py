import os
import sys
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

diretorio_atual = os.path.dirname(os.path.abspath(__file__))
if diretorio_atual not in sys.path:
    sys.path.append(diretorio_atual)

from analise_estatistica import acuracia_de_sinal, correlacao_com_defasagem, sinal_atual, veredito
from analise_sentimento import aplicar_decaimento_temporal, pontuar_sentimento_llm
from coleta_noticias import coletar_noticias
from cruzamento_precos import cruzar_sentimento_com_precos, mercado_do_ticker, obter_historico_precos

st.set_page_config(
    page_title="Analisador de Sentimento de Ações - Projeto 02",
    page_icon="📈",
    layout="wide"
)

DIAS_POR_PERIODO = {"1mo": 30, "3mo": 90, "6mo": 180}


@st.cache_data(ttl=900, show_spinner=False)
def carregar_noticias(ticker, limite_dias):
    return coletar_noticias(ticker, limite_dias)


@st.cache_data(ttl=900, show_spinner=False)
def carregar_precos(ticker, periodo):
    return obter_historico_precos(ticker, periodo=periodo)


# ==========================================
# BARRA LATERAL (CONFIGURAÇÕES GERAIS)
# ==========================================
with st.sidebar:
    st.header("⚙️ Configurações Avançadas")
    periodo = st.selectbox("Janela do Gráfico:", list(DIAS_POR_PERIODO), index=0)
    meia_vida = st.slider("Meia-vida do Decaimento (Dias):", min_value=1, max_value=15, value=5)

    st.subheader("🔑 Conexão com LLM (Opcional)")
    api_key = st.text_input("Chave Google Gemini API:", type="password", placeholder="Cole sua chave aqui")
    if not api_key.strip():
        st.caption("ℹ️ Modo 100% Local Gratuito (Léxico Financeiro Ativo)")

# ==========================================
# TELA PRINCIPAL
# ==========================================
st.title("📈 Analisador de Sentimento vs. Preço de Ações")

col_ticker, col_btn = st.columns([3, 1])
with col_ticker:
    ticker_opcoes = ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "BBAS3.SA", "MGLU3.SA", "AAPL", "NVDA", "TSLA"]
    ticker = st.selectbox("Selecione a ação para monitorar:", ticker_opcoes, index=0)
with col_btn:
    st.write("")
    st.write("")
    if st.button("🔄 Atualizar Agora", use_container_width=True):
        st.cache_data.clear()

mercado = mercado_do_ticker(ticker)

with st.spinner(f"Buscando notícias e cotações para {ticker}..."):
    noticias = carregar_noticias(ticker, DIAS_POR_PERIODO[periodo])
    df_precos = carregar_precos(ticker, periodo)
    noticias = pontuar_sentimento_llm(noticias, api_key)
    noticias = aplicar_decaimento_temporal(noticias, meia_vida_dias=meia_vida)
    df = cruzar_sentimento_com_precos(noticias, df_precos, mercado=mercado, meia_vida_dias=meia_vida)

if df.empty:
    st.warning("Sem dados suficientes: não encontrei notícias ou cotações para este ativo/janela.")
    st.stop()

st.caption(f"⏱️ Última sincronização: {datetime.now():%H:%M:%S} (cache de até 15 min) | Ticker: {ticker} | Mercado: {mercado}")

noticias_lexico = [n for n in noticias if n.get("motor") == "lexico"]
if noticias_lexico:
    motivos = sorted({n.get("motivo_motor", "") for n in noticias_lexico})
    st.warning(
        f"⚠️ **Modo degradado:** {len(noticias_lexico)} de {len(noticias)} manchetes foram pontuadas por um léxico "
        f"simples de palavras, não por IA (motivo: {'; '.join(motivos)}). O léxico erra ironia e contexto, "
        "então trate esses scores como aproximação."
    )

# ==========================================
# CARDS DE MÉTRICAS NO TOPO
# ==========================================
ultimo_preco = df["Preco_Fechamento"].iloc[-1]
var_total = (ultimo_preco / df["Preco_Fechamento"].iloc[0] - 1) * 100
sinal = sinal_atual(noticias)
estat = acuracia_de_sinal(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Cotação ({ticker})", f"{'R$' if mercado == 'BR' else 'US$'} {ultimo_preco:.2f}", f"{var_total:+.2f}%")

rotulo = "Sem dados"
if sinal is not None:
    rotulo = "Otimista 🟢" if sinal > 0.15 else ("Pessimista 🔴" if sinal < -0.15 else "Neutro ⚪")
c2.metric("Sinal atual (ponderado)", f"{sinal:+.2f}" if sinal is not None else "n/d", rotulo)
c3.metric("Manchetes únicas", f"{len(noticias)}", f"janela de {DIAS_POR_PERIODO[periodo]} dias")
c4.metric(
    "Acerto de direção", f"{estat['taxa'] * 100:.0f}%" if estat["n_dias"] else "n/d",
    f"baseline {estat['baseline'] * 100:.0f}% · {estat['acertos']}/{estat['n_dias']} dias", delta_color="off"
)

st.divider()

# ==========================================
# GRÁFICO PLOTLY DE DUPLO EIXO
# ==========================================
st.subheader("📊 Gráfico Interativo de Duplo Eixo")

fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_trace(
    go.Scatter(x=df["Data"], y=df["Preco_Fechamento"], name="Cotação (Fechamento)",
               line=dict(color="#00F0FF", width=3), mode="lines+markers"),
    secondary_y=False,
)
fig.add_trace(
    go.Bar(x=df["Data"], y=df["Sentimento_Medio"], name="Sentimento do dia",
           marker=dict(color=["#10F984" if s >= 0 else "#FF4A68" for s in df["Sentimento_Medio"]], opacity=0.5)),
    secondary_y=True,
)
fig.add_trace(
    go.Scatter(x=df["Data"], y=df["Sentimento_Ponderado"], name=f"Sentimento suavizado (meia-vida {meia_vida}d)",
               line=dict(color="#FFD166", width=2, dash="dot")),
    secondary_y=True,
)
fig.update_layout(
    template="plotly_dark", height=480, hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(l=10, r=10, t=30, b=10)
)
fig.update_yaxes(title_text="Preço da Ação", secondary_y=False)
fig.update_yaxes(title_text="Sentimento (-1 a +1)", range=[-1.1, 1.1], secondary_y=True)
st.plotly_chart(fig, use_container_width=True)

# ==========================================
# RIGOR ESTATÍSTICO
# ==========================================
with st.expander("📐 Rigor estatístico: isso é sinal ou coincidência?", expanded=True):
    st.markdown(f"**{veredito(estat)}**")
    st.caption(
        f"Acerto de direção: {estat['acertos']}/{estat['n_dias']} dias com notícia e sentimento ≠ 0. "
        f"Baseline (melhor palpite constante): {estat['baseline'] * 100:.0f}%. "
        f"P-valor de acertar tanto ou mais só por sorte: {estat['p_valor']:.2f}."
    )
    defasagem = correlacao_com_defasagem(df)
    col_g, col_t = st.columns([2, 1])
    with col_g:
        st.bar_chart(defasagem.set_index("Defasagem_pregoes")["Correlacao"])
    with col_t:
        st.dataframe(defasagem.style.format({"Correlacao": "{:+.2f}"}), hide_index=True, use_container_width=True)
    st.caption(
        "Correlação entre o sentimento de k pregões atrás e o retorno de hoje. Notícia publicada depois do "
        "fechamento conta para o pregão seguinte; fim de semana e feriado caem no próximo pregão. "
        "Correlação não é causalidade, e poucos pontos não sustentam conclusão."
    )

# ==========================================
# FEED AUDITÁVEL DE NOTÍCIAS
# ==========================================
st.subheader("📰 Feed de Notícias em Tempo Real")

filtro = st.radio("Filtrar:", ["Todas", "Otimistas", "Pessimistas"], horizontal=True)

df_tabela = pd.DataFrame(noticias)
if filtro == "Otimistas":
    df_tabela = df_tabela[df_tabela["score"] > 0.20]
elif filtro == "Pessimistas":
    df_tabela = df_tabela[df_tabela["score"] < -0.20]

for _, n in df_tabela.head(15).iterrows():
    cor = "🟢" if n["score"] > 0.2 else ("🔴" if n["score"] < -0.2 else "⚪")
    with st.expander(f"{cor} [{n['data']}] {n['titulo']} ({n['fonte']})"):
        st.write(f"**Score:** {n['score']:+.2f} ({n['classificacao']}) | **Peso:** {n.get('peso_temporal', 1.0):.2f} | **Motor:** {n.get('motor', '-')}")
        st.caption(f"Análise: {n.get('motivo', 'Avaliação financeira')}")
        st.markdown(f"[🔗 Ler notícia no portal original]({n['link']})")

st.caption("⚠️ Estudo acadêmico de NLP, não é recomendação de investimento. Notícias via Google News RSS; cotações via Yahoo Finance.")
