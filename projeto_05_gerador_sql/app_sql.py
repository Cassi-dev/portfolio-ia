import streamlit as st
import os
import sys
import pandas as pd

diretorio_atual = os.path.dirname(os.path.abspath(__file__))
if diretorio_atual not in sys.path:
    sys.path.append(diretorio_atual)

from core.config import MODELO_GEMINI
from banco_dados import LIMITE_LINHAS, executar_consulta, inicializar_banco, obter_schema_ddl
from motor_text_to_sql import processar_pergunta_com_ciclo_correcao
from validador_seguranca import validar_seguranca_sql

st.set_page_config(
    page_title="Text-to-SQL Seguro - Projeto 05",
    page_icon="🗄️",
    layout="wide"
)

# Inicializa o banco se necessário
inicializar_banco()
schema_atual = obter_schema_ddl()

# ==========================================
# BARRA LATERAL (SCHEMA E CONFIGURAÇÕES)
# ==========================================
with st.sidebar:
    st.header("⚙️ Configurações & Segurança")
    st.caption("Trava Ativa: Somente SELECT via sqlglot")
    
    api_key = st.text_input("Chave Google Gemini API:", type="password", placeholder="Cole sua chave aqui")
    if api_key.strip():
        st.success(f"✅ {MODELO_GEMINI} ativo para Text-to-SQL")
    else:
        st.info("ℹ️ Sem chave: Motor heurístico offline ativo")

    st.divider()
    st.subheader("📋 Schema das Tabelas (SQLite)")
    with st.expander("Ver Estrutura DDL do Banco"):
        st.code(schema_atual, language="sql")

    st.divider()
    st.subheader("🧪 Teste de Ataque / Segurança")
    st.caption("Teste se a IA ou um usuário tentar rodar comandos destrutivos:")
    if st.button("🚨 Simular 'DROP TABLE clientes'"):
        valido, msg, _ = validar_seguranca_sql("DROP TABLE clientes;")
        st.error(f"1ª trava (validador de AST): {msg}")
    if st.button("🔒 Testar a 2ª trava (SQLite somente leitura)"):
        resultado_direto = executar_consulta("DELETE FROM clientes")
        st.error(f"2ª trava (o próprio banco, sem passar pelo validador): {resultado_direto.erro}")

# ==========================================
# TELA PRINCIPAL
# ==========================================
st.title("🗄️ Fale com o Banco de Dados em Português")
st.caption("Inteligência corporativa Text-to-SQL com execução defensiva de segurança (Zero risco de DROP ou DELETE)")

# Botões de perguntas rápidas (ótimo para testar no celular!)
st.markdown("#### 💡 Perguntas Prontas para Testar:")
col_p1, col_p2, col_p3 = st.columns(3)

pergunta_sugerida = ""
with col_p1:
    if st.button("🏆 Maiores Clientes em Faturamento", use_container_width=True):
        pergunta_sugerida = "Quais são os 5 maiores clientes por faturamento total?"
with col_p2:
    if st.button("📊 Faturamento por Canal de Venda", use_container_width=True):
        pergunta_sugerida = "Qual o faturamento total e quantidade de pedidos por canal de venda?"
with col_p3:
    if st.button("📦 Produtos com Baixo Estoque", use_container_width=True):
        pergunta_sugerida = "Quais produtos têm estoque menor que 50 unidades?"

pergunta_usuario = st.text_input(
    "Digite sua dúvida sobre os negócios em português:",
    value=pergunta_sugerida if pergunta_sugerida else "Quais os 3 clientes que mais compraram?",
    placeholder="Ex: Quais os produtos mais vendidos? Qual o ticket médio por estado?"
)

btn_executar = st.button("⚡ Gerar SQL e Consultar Banco", use_container_width=True)

if btn_executar and pergunta_usuario.strip():
    with st.spinner("Gerando SQL, validando segurança com sqlglot e executando..."):
        resultado = processar_pergunta_com_ciclo_correcao(pergunta_usuario, api_key=api_key)

    st.divider()

    if resultado.get("degradado"):
        st.warning(f"⚠️ **Modo degradado:** {resultado['motivo_degradado']}.")

    # 1. EXIBIÇÃO TRANSPARENTE DO SQL E SEGURANÇA
    col_sql, col_sec = st.columns([3, 1])
    
    with col_sql:
        st.markdown("#### 📝 Consulta SQL Gerada:")
        st.code(resultado["sql"], language="sql")
        st.caption(f"Motor: {resultado['modo']} | Tentativas: {resultado['tentativas']}")
        
    with col_sec:
        st.markdown("#### 🛡️ Auditoria:")
        if resultado["seguro"]:
            st.success("✅ **Segurança: APROVADO**\n\nComando 100% de leitura (SELECT).")
        else:
            st.error(f"🚨 **Bloqueio Ativado!**\n\n{resultado['msg_seguranca']}")

    # 2. RESULTADOS DO BANCO DE DADOS
    if resultado["seguro"] and resultado["df"] is not None:
        df = resultado["df"]
        st.markdown(f"#### 📊 Resultado da Consulta ({len(df)} registros encontrados):")
        if resultado.get("truncado"):
            st.caption(f"⚠️ Resultado limitado às primeiras {LIMITE_LINHAS} linhas.")
        
        if df.empty:
            st.warning("A consulta foi executada com sucesso, mas nenhum dado atendeu aos critérios.")
        else:
            st.dataframe(df, use_container_width=True)
            
            # Gráfico automático se houver pelo menos uma coluna numérica e uma de texto
            colunas_num = df.select_dtypes(include='number').columns.tolist()
            colunas_texto = [c for c in df.columns if c not in colunas_num]
            
            if colunas_texto and colunas_num:
                st.subheader("📈 Visualização Gráfica Automática:")
                col_x = colunas_texto[0]
                col_y = colunas_num[0]
                df_chart = df.set_index(col_x)[[col_y]]
                st.bar_chart(df_chart)

    elif resultado.get("erro_banco"):
        st.error(f"❌ Erro na execução do SQLite: {resultado['erro_banco']}")
