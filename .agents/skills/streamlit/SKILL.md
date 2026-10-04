---
name: streamlit
description: Guia de boas práticas, padrões de arquitetura, gerenciamento de estado (session_state), cache e interfaces interativas de IA usando Streamlit.
---

# Skill: Desenvolvimento de Aplicações e Interfaces com Streamlit

Esta skill reúne as melhores práticas e padrões para projetar e manter aplicações web interativas com foco em Inteligência Artificial e RAG.

## 1. Princípios Fundamentais do Streamlit
- **Execução Top-to-Bottom:** O Streamlit reexecuta o script do início ao fim a cada interação do usuário (clique, texto digitado, slider).
- **Gerenciamento de Estado (st.session_state):** Como o script recarrega, variáveis normais são reiniciadas. Para manter o histórico de chat e seleções do usuário, use sempre st.session_state.
- **Cache de Recursos Pesados (@st.cache_resource):** Conexões com bancos de dados (ChromaDB), modelos de embeddings ou clientes de IA devem ser encapsulados em funções com @st.cache_resource para não serem recarregados a cada clique.

## 2. Padrão de Chat com IA e RAG
`python
import streamlit as st

# 1. Manter histórico no session_state
if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

# 2. Renderizar histórico anterior
for msg in st.session_state.mensagens:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 3. Capturar nova entrada
if prompt := st.chat_input("Digite sua dúvida..."):
    st.session_state.mensagens.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    # Executar busca vetorial e responder
    with st.chat_message("assistant"):
        st.markdown("Resposta gerada...")
`

## 3. Boas Práticas de UI e Auditoria
- **Expander de Fontes (st.expander):** Sempre mostre trechos recuperados, arquivos de origem e scores de distância dentro de um expander para não poluir a tela principal.
- **Painel de Controle Lateral (st.sidebar):** Coloque parâmetros como limiar de similaridade (threshold), escolha de modelo e inputs de API na barra lateral.
- **Feedback Visual:** Use st.spinner("Pesquisando documentos...") para indicar processamento em tempo real.
