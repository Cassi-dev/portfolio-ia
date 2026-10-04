"""
Dashboard Visual do Clone — Monitoramento em Tempo Real

Painel interativo com:
- Status do bot e servidor bridge
- Métricas de aprendizado live
- Gráficos de aprovação por contato
- Timeline de reações e eventos
- Recomendações personalizadas
"""
import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests
from ingestao_whatsapp import CAMINHO_PADRAO_WPP_SQLITE
from persona_config import config_privada_existe

# Config página
st.set_page_config(
    page_title="🤖 Clone Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS custom
st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem; }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# HEADER
# ============================================================================

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    st.markdown("# 🤖 Clone Digital — Dashboard")
with col2:
    st.write("")
with col3:
    st.write(f"🕐 {datetime.now().strftime('%H:%M:%S')}")

if not config_privada_existe():
    st.warning("Filtro de privacidade sem lista pessoal — crie persona_privado.json a partir do exemplo")

# ============================================================================
# STATUS DO SISTEMA
# ============================================================================

st.markdown("---")

status_cols = st.columns(4)

# Bot
try:
    with status_cols[0]:
        st.metric("🔌 Bot WhatsApp", "●", "Online")
except:
    with status_cols[0]:
        st.metric("🔌 Bot WhatsApp", "●", "Offline")

# Servidor Bridge
try:
    resp = requests.get("http://127.0.0.1:8506/status", timeout=2)
    if resp.status_code == 200:
        with status_cols[1]:
            st.metric("🌉 Bridge Server", "●", "Online")
    else:
        with status_cols[1]:
            st.metric("🌉 Bridge Server", "●", "Offline")
except:
    with status_cols[1]:
        st.metric("🌉 Bridge Server", "●", "Offline")

# Banco de dados
DB_BOT_PATH = CAMINHO_PADRAO_WPP_SQLITE
if DB_BOT_PATH and DB_BOT_PATH.exists():
    try:
        conn = sqlite3.connect(str(DB_BOT_PATH))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM clone_responses_feedback WHERE rating IS NOT NULL")
        feedback_count = cur.fetchone()[0]
        conn.close()
        with status_cols[2]:
            st.metric("💾 Banco de Dados", "●", "Online")
    except:
        with status_cols[2]:
            st.metric("💾 Banco de Dados", "●", "Erro")
else:
    with status_cols[2]:
        st.metric("💾 Banco de Dados", "●", "Não configurado" if not DB_BOT_PATH else "Não encontrado")

# Sessão Foco
if DB_BOT_PATH and DB_BOT_PATH.exists():
    try:
        conn = sqlite3.connect(str(DB_BOT_PATH))
        cur = conn.cursor()
        cur.execute("SELECT active FROM focus_sessions WHERE active=1 LIMIT 1")
        foco_ativo = cur.fetchone() is not None
        conn.close()
        with status_cols[3]:
            status_text = "Ativo ⏱️" if foco_ativo else "Parado"
            st.metric("📍 Modo Foco", "●" if foco_ativo else "○", status_text)
    except:
        with status_cols[3]:
            st.metric("📍 Modo Foco", "○", "Erro")
else:
    with status_cols[3]:
        st.metric("📍 Modo Foco", "○", "Desconectado")

# ============================================================================
# MÉTRICAS PRINCIPAIS
# ============================================================================

st.markdown("---")
st.markdown("## 📊 Aprendizado em Tempo Real")

if DB_BOT_PATH and DB_BOT_PATH.exists():
    conn = sqlite3.connect(str(DB_BOT_PATH))

    # Stats gerais
    stats = pd.read_sql_query("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as rejeitadas,
            SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) as sem_feedback
        FROM clone_responses_feedback
    """, conn)

    total = stats['total'].iloc[0] if stats['total'].iloc[0] else 0
    aprovadas = stats['aprovadas'].iloc[0] if stats['aprovadas'].iloc[0] else 0
    rejeitadas = stats['rejeitadas'].iloc[0] if stats['rejeitadas'].iloc[0] else 0
    sem_feedback = stats['sem_feedback'].iloc[0] if stats['sem_feedback'].iloc[0] else 0

    taxa = (aprovadas / total * 100) if total > 0 else 0

    # KPIs
    kpi_cols = st.columns(5)
    with kpi_cols[0]:
        st.metric("Total de Respostas", total)
    with kpi_cols[1]:
        st.metric("👍 Aprovadas", aprovadas, f"+{taxa:.0f}%")
    with kpi_cols[2]:
        st.metric("👎 Rejeitadas", rejeitadas)
    with kpi_cols[3]:
        st.metric("⏳ Sem Feedback", sem_feedback)
    with kpi_cols[4]:
        st.metric("📈 Taxa Geral", f"{taxa:.1f}%")

    # ========================================================================
    # GRÁFICOS
    # ========================================================================

    col1, col2 = st.columns(2)

    # Gráfico 1: Aprovação por contato
    with col1:
        st.markdown("### Aprovação por Contato")
        por_contato = pd.read_sql_query("""
            SELECT
                sender_name as "Contato",
                COUNT(*) as "Total",
                SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as "Aprovadas"
            FROM clone_responses_feedback
            WHERE rating IS NOT NULL
            GROUP BY sender_name
            ORDER BY "Aprovadas" DESC
        """, conn)

        if not por_contato.empty:
            por_contato["Taxa %"] = (por_contato["Aprovadas"] / por_contato["Total"] * 100).round(1)

            fig = px.bar(
                por_contato,
                x="Contato",
                y="Taxa %",
                title="Taxa de Aprovação por Contato",
                labels={"Taxa %": "Aprovação (%)"},
                color="Taxa %",
                color_continuous_scale=["#d03b3b", "#fab219", "#0ca30c"]
            )
            fig.update_layout(height=300, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sem dados de contato ainda")

    # Gráfico 2: Distribuição de feedback
    with col2:
        st.markdown("### Distribuição de Feedback")
        feedback_dist = pd.DataFrame({
            "Status": ["Aprovadas 👍", "Rejeitadas 👎", "Sem Reação ⏳"],
            "Quantidade": [aprovadas, rejeitadas, sem_feedback]
        })

        colors = ["#0ca30c", "#d03b3b", "#999999"]
        fig = px.pie(
            feedback_dist,
            values="Quantidade",
            names="Status",
            title="Distribuição do Feedback",
            color_discrete_sequence=colors
        )
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)

    # ========================================================================
    # TONE POR CONTATO (PARTE 3)
    # ========================================================================

    st.markdown("---")
    st.markdown("## 🎯 Tone Adaptado por Contato")

    try:
        tone_resp = requests.get("http://127.0.0.1:8506/relatorio_tone", timeout=3)
        if tone_resp.status_code == 200:
            tone_data = tone_resp.json()
            por_contato_tone = tone_data.get("por_contato", {})

            if por_contato_tone:
                # Melhor contato
                melhor = tone_data.get("melhor_contato", "?").title()
                taxa_melhor = tone_data.get("taxa_melhor", 0) * 100

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("🌟 Melhor Tone", melhor, f"{taxa_melhor:.0f}% de sucesso")
                with col2:
                    st.metric("📚 Contatos com Padrão", len(por_contato_tone))
                with col3:
                    avg_tone = sum(por_contato_tone.values()) / len(por_contato_tone) * 100 if por_contato_tone else 0
                    st.metric("⚡ Média Geral", f"{avg_tone:.0f}%")

                # Barra visual
                st.markdown("#### Taxa de Sucesso por Contato")
                for contato, taxa in sorted(por_contato_tone.items(), key=lambda x: x[1], reverse=True):
                    pct = taxa * 100
                    emoji = "🌟" if pct >= 80 else "✅" if pct >= 60 else "⚠️"
                    col1, col2 = st.columns([2, 3])
                    with col1:
                        st.write(f"{emoji} **{contato.title()}**")
                    with col2:
                        st.progress(min(taxa, 1.0), text=f"{pct:.0f}%")
            else:
                st.info("Sem dados de tone ainda. Após alguns feedbacks, o padrão aparecerá aqui.")
    except:
        st.info("Servidor bridge não respondeu. Verifique se está rodando.")

    # ========================================================================
    # HISTÓRICO RECENTE
    # ========================================================================

    st.markdown("---")
    st.markdown("## 📝 Últimas Reações")

    recent = pd.read_sql_query("""
        SELECT
            sender_name as "Contato",
            response_text as "Resposta",
            rating as "Rating",
            timestamp as "Timestamp"
        FROM clone_responses_feedback
        ORDER BY timestamp DESC
        LIMIT 15
    """, conn)

    if not recent.empty:
        def format_rating(r):
            if r == 1:
                return "👍 Boa"
            elif r == -1:
                return "👎 Ruim"
            else:
                return "⏳ Aguardando"

        recent["Rating"] = recent["Rating"].apply(format_rating)
        recent["Timestamp"] = pd.to_datetime(recent["Timestamp"], unit="ms").dt.strftime("%d/%m %H:%M")
        recent["Resposta"] = recent["Resposta"].str[:60] + "..."

        st.dataframe(recent, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma reação ainda")

    conn.close()
else:
    st.error("❌ Banco de dados não configurado ou não encontrado (defina WPP_SQLITE_PATH no .env)")

# ============================================================================
# RECOMENDAÇÕES
# ============================================================================

st.markdown("---")
st.markdown("## 💡 Recomendações")

if total > 0:
    recomendacoes = []

    if taxa < 50:
        recomendacoes.append("⚠️ Taxa de aprovação baixa (<50%). Clone precisa aprender mais. Mantenha reagindo com 👍/👎")
    elif taxa >= 80:
        recomendacoes.append("🎉 Excelente! Taxa acima de 80%. Clone está acertando o tom.")

    if rejeitadas > aprovadas:
        recomendacoes.append("👎 Mais rejeições que aprovações. Clone não está no seu estilo. Observe os padrões.")

    if sem_feedback > total * 0.3:
        recomendacoes.append("⏳ Muitas respostas sem feedback. Reaja com 👍/👎 pra treinar melhor.")

    if recomendacoes:
        for rec in recomendacoes:
            st.info(rec)
    else:
        st.success("✅ Sistema funcionando bem! Continue reagindo às respostas do clone.")
else:
    st.info("🚀 Comece ativando `!foco 15m` no WhatsApp e reagindo com 👍/👎")

# ============================================================================
# SIDEBAR: CONFIGURAÇÕES
# ============================================================================

st.sidebar.markdown("## ⚙️ Configurações")

refresh_interval = st.sidebar.slider(
    "Auto-refresh (segundos)",
    min_value=5,
    max_value=60,
    value=10,
    step=5
)

st.sidebar.markdown("---")
st.sidebar.markdown("## 📚 Documentação")
st.sidebar.markdown("""
### Partes do Loop

**PARTE 1:** Reação Automática
- Bot lê 👍👎 do WhatsApp
- Atualiza rating no banco

**PARTE 2:** Treino com Feedback
- ChromaDB aprende com reações
- Exemplos 👍 são priorizados

**PARTE 3:** Per-Contact Tone
- Clone responde diferente com cada pessoa
- Dashboard mostra taxa por contato

### Como Usar

1. Ative `!foco 15m` no WhatsApp
2. Clone responde automaticamente
3. Reaja com 👍 ou 👎
4. Dashboard atualiza em tempo real
""")

st.sidebar.markdown("---")
st.sidebar.caption("🔄 Dashboard atualiza a cada 10s | Dados: SQLite do bot")

# Auto-refresh
import time
if refresh_interval:
    time.sleep(refresh_interval)
    st.rerun()
