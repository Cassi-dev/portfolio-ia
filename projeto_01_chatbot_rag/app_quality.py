"""
Dashboard de Qualidade do Clone — Modo Foco

Mostra métricas de aprovação (👍👎) das respostas do clone por contato.
Conecta direto ao SQLite do bot em wpp-ai-summarizer/database.sqlite.
"""
import streamlit as st
import sqlite3
from pathlib import Path
import pandas as pd
from datetime import datetime

# Config
st.set_page_config(page_title="🎯 Qualidade do Clone", layout="wide")
st.markdown("# 🎯 Qualidade do Clone — Modo Foco")

from ingestao_whatsapp import CAMINHO_PADRAO_WPP_SQLITE

# Caminho do banco do bot
DB_BOT_PATH = CAMINHO_PADRAO_WPP_SQLITE

if not DB_BOT_PATH or not DB_BOT_PATH.exists():
    st.error("❌ Banco de dados não encontrado (configure WPP_SQLITE_PATH no .env)")
    st.stop()

# Conecta ao banco
conn = sqlite3.connect(str(DB_BOT_PATH))
conn.row_factory = sqlite3.Row

# Checa se tabela existe
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='clone_responses_feedback'")
if not cursor.fetchone():
    st.warning("⚠️ Nenhum feedback ainda. Ative o Modo Foco e reaja às mensagens do clone com 👍 ou 👎!")
    st.info("Como funciona:\n1. Ative `!foco <minutos>`\n2. O clone responde\n3. React com 👍 (boa) ou 👎 (ruim)\n4. Dashboard atualiza aqui")
    st.stop()

# Lê estatísticas
stats = pd.read_sql_query("""
    SELECT
        remote_jid as "Contato ID",
        sender_name as "Nome",
        COUNT(*) as "Total",
        SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as "👍",
        SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) as "👎",
        SUM(CASE WHEN rating IS NULL THEN 1 ELSE 0 END) as "Sem reação",
        ROUND(
            SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
            1
        ) as "Taxa de Aprovação %"
    FROM clone_responses_feedback
    GROUP BY remote_jid, sender_name
    ORDER BY COUNT(*) DESC
""", conn)

conn.close()

# Mostra tabela geral
st.subheader("📊 Resumo por Contato")
if not stats.empty:
    # Formata a exibição
    display_stats = stats.copy()
    display_stats["Taxa de Aprovação %"] = display_stats["Taxa de Aprovação %"].astype(str) + "%"
    st.dataframe(display_stats, use_container_width=True, hide_index=True)

    # KPIs principais
    col1, col2, col3, col4 = st.columns(4)
    total_respostas = stats["Total"].sum()
    total_aprovadas = stats["👍"].sum()
    total_rejeitadas = stats["👎"].sum()
    taxa_geral = (total_aprovadas / total_respostas * 100) if total_respostas > 0 else 0

    with col1:
        st.metric("Total de Respostas", total_respostas)
    with col2:
        st.metric("👍 Aprovadas", total_aprovadas)
    with col3:
        st.metric("👎 Rejeitadas", total_rejeitadas)
    with col4:
        st.metric("Taxa Geral", f"{taxa_geral:.1f}%")

    # Gráfico de aprovação por contato
    st.subheader("📈 Aprovação por Contato")
    chart_data = stats[["Nome", "Taxa de Aprovação %"]].copy()
    chart_data = chart_data.sort_values("Taxa de Aprovação %", ascending=True)
    st.bar_chart(chart_data.set_index("Nome"), height=400)

    # Detalhe: últimas respostas com feedback
    st.subheader("📝 Últimas Respostas")

    conn = sqlite3.connect(str(DB_BOT_PATH))
    conn.row_factory = sqlite3.Row

    recent = pd.read_sql_query("""
        SELECT
            sender_name as "Contato",
            response_text as "Resposta",
            rating as "Rating",
            timestamp as "Timestamp"
        FROM clone_responses_feedback
        ORDER BY timestamp DESC
        LIMIT 20
    """, conn)

    if not recent.empty:
        # Formata rating
        def format_rating(r):
            if r == 1:
                return "👍 Boa"
            elif r == -1:
                return "👎 Ruim"
            else:
                return "➖ Sem reação"

        recent["Rating"] = recent["Rating"].apply(format_rating)
        recent["Timestamp"] = pd.to_datetime(recent["Timestamp"], unit="ms").dt.strftime("%d/%m %H:%M")

        st.dataframe(recent, use_container_width=True, hide_index=True)

    conn.close()
else:
    st.info("Nenhum feedback gravado ainda.")

# Seção de Per-Contact Tone (requer conexão com servidor bridge)
st.subheader("🎯 Tone por Contato")
try:
    import requests
    tone_response = requests.get("http://127.0.0.1:8506/relatorio_tone", timeout=3)
    if tone_response.status_code == 200:
        tone_data = tone_response.json()
        melhor_contato = tone_data.get("melhor_contato", "?")
        taxa_melhor = tone_data.get("taxa_melhor", 0)
        por_contato = tone_data.get("por_contato", {})

        if por_contato:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Melhor tone", melhor_contato.title(), f"{taxa_melhor*100:.0f}% de aprovação")
            with col2:
                st.metric("Contatos com padrão", len(por_contato))

            st.markdown("#### Taxa de sucesso por contato:")
            for contato, taxa in sorted(por_contato.items(), key=lambda x: x[1], reverse=True):
                pct = taxa * 100
                barra = "█" * int(pct/5) + "░" * (20 - int(pct/5))
                st.write(f"`{contato.title():15}` {barra} {pct:.0f}%")
        else:
            st.info("Sem dados de tone ainda. Após alguns feedbacks, o padrão aparecerá aqui.")
    else:
        st.info("Servidor bridge (8506) não respondeu. Inicie: `python servidor_bridge.py`")
except Exception as e:
    st.info(f"Tone: aguardando servidor bridge... ({type(e).__name__})")

# Instruções
with st.expander("ℹ️ Como avaliar as respostas", expanded=False):
    st.markdown("""
    ### Como o clone aprende com seu feedback:

    1. **Modo Foco ativo** (`!foco 15m`)
    2. **Clone responde** automaticamente as mensagens
    3. **Você reage** com emoji no WhatsApp:
       - 👍 **Polegar para cima** = resposta boa
       - 👎 **Polegar para baixo** = resposta ruim
    4. **Dashboard atualiza** com a estatística
    5. **Persona aprende** qual estilo funciona com qual contato

    ### O que otimizar:
    - **Taxa baixa (<50%)** = clone ainda não entende bem esse tipo de conversa
    - **Taxa alta (>80%)** = clone está acertando o tom
    - **Sem reação** = você não avaliou ainda (no WhatsApp coloque o emoji na resposta)
    """)

st.markdown("---")
st.caption("🔄 Última atualização: agora mesmo | Dados: banco SQLite do bot")
