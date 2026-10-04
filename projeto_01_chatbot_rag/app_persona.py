"""
Interface Streamlit para a Persona Digital Adaptativa com RAG e Feedback Loop Contínuo.
Aprende a escrever e pensar como o usuário através de conversas reais do WhatsApp.
"""
import os
import sys
from pathlib import Path

# Garante que o diretório raiz e o projeto estejam no sys.path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from core.llm import criar_cliente
from ingestao_whatsapp import (
    parsear_exportacao_whatsapp, identificar_autores,
    extrair_pares_conversa, analisar_estilo_escrita,
    CAMINHO_PADRAO_WPP_SQLITE
)
from motor_persona import MotorPersona, carregar_perfil_estilo, salvar_perfil_estilo
from loop_aprendizado import (
    avaliar_fidelidade_estilo, aprender_com_correcao, loop_geracao_com_guardrail,
    sincronizar_banco_wpp_summarizer
)
from persona_config import config_privada_existe

st.set_page_config(
    page_title="Persona Digital Adaptativa - Projeto 01",
    page_icon="🧬",
    layout="wide"
)

# Inicialização de estado e serviços
@st.cache_resource
def obter_motor():
    return MotorPersona()

motor = obter_motor()
perfil = motor.perfil

# Barra Lateral
with st.sidebar:
    st.title("🧬 Persona Digital")
    st.caption("Aprende seu tom de voz e raciocínio com base no histórico do WhatsApp e feedback contínuo.")
    
    api_key = st.text_input("Chave Gemini API", type="password", placeholder="AIzaSy...", key="persona_api_key")
    st.divider()
    
    st.markdown("### 📊 Status da Memória")
    total_memoria = motor.colecao.count()
    st.metric("Diálogos Indexados", f"{total_memoria} pares")
    st.metric("Tamanho Médio", f"{perfil.get('media_palavras', 14)} palavras")
    
    st.markdown("**Termos Mais Usados:**")
    st.write(", ".join(f"`{t}`" for t in perfil.get("termos_frequentes", [])[:6]))
    
    if st.button("🧹 Limpar Histórico do Chat Atual", use_container_width=True):
        st.session_state.chat_persona_historico = []
        st.rerun()

st.header(f"💬 Clone de Voz & Raciocínio ({perfil.get('nome', 'Usuário')})")
st.caption("Interaja com a persona, teste como ela responde a outras pessoas e ensine novas respostas em tempo real.")

if not config_privada_existe():
    st.warning("Filtro de privacidade sem lista pessoal — crie persona_privado.json a partir do exemplo")

tab_chat, tab_alimentar, tab_perfil = st.tabs([
    "💬 Conversar & Treinar (Modo Teste)",
    "📥 Ingestão de WhatsApp (Upload/Colar)",
    "🧬 DNA de Estilo & Memória"
])

# ==============================================================================
# ABA 1: CHAT & FEEDBACK LOOP
# ==============================================================================
with tab_chat:
    if "chat_persona_historico" not in st.session_state:
        st.session_state.chat_persona_historico = []
        
    chat_container = st.container()
    with chat_container:
        for i, msg in enumerate(st.session_state.chat_persona_historico):
            if msg["autor"] == "interlocutor":
                with st.chat_message("user", avatar="👤"):
                    st.write(msg["texto"])
            else:
                with st.chat_message("assistant", avatar="⚡"):
                    st.write(msg["texto"])
                    if msg.get("score"):
                        st.caption(f"🎯 **Fidelidade de Estilo:** {msg['score']}/100")
                    if msg.get("exemplos"):
                        with st.expander("🔍 Referências Reais do WhatsApp Usadas pelo RAG", expanded=False):
                            for idx, ex in enumerate(msg["exemplos"], 1):
                                st.markdown(f"**Referência {idx}**")
                                st.write(f"- *Quando perguntaram:* \"{ex['pergunta']}\"")
                                st.write(f"- *Você respondeu:* \"{ex['resposta']}\"")

    # Entrada do chat
    if prompt_usuario := st.chat_input("Envie uma mensagem como se fosse outra pessoa conversando com você..."):
        st.session_state.chat_persona_historico.append({
            "autor": "interlocutor",
            "texto": prompt_usuario
        })
        
        with st.spinner("Pensando e formulando resposta no seu estilo..."):
            client = None
            if api_key.strip():
                try:
                    client = criar_cliente(api_key.strip())
                except Exception:
                    pass
                    
            resultado = loop_geracao_com_guardrail(
                motor=motor,
                pergunta=prompt_usuario,
                historico=st.session_state.chat_persona_historico,
                client=client,
                api_key=api_key
            )
            
            st.session_state.chat_persona_historico.append({
                "autor": "persona",
                "texto": resultado["resposta"],
                "score": resultado["avaliacao"]["score_estilo"],
                "exemplos": resultado.get("exemplos_usados", [])
            })
            st.session_state.ultima_pergunta = prompt_usuario
            st.session_state.ultima_resposta = resultado["resposta"]
            st.rerun()

    # Bloco do Loop de Feedback (Aprender com correção)
    if st.session_state.get("ultima_resposta"):
        st.divider()
        with st.expander("✏️ Feedback Loop: Eu não responderia bem assim! Ensinar a resposta ideal", expanded=False):
            st.caption("Ao corrigir a IA aqui, a sua resposta é gravada no banco vetorial e ela aprende imediatamente.")
            col_p, col_r = st.columns(2)
            with col_p:
                st.markdown("**Mensagem Recebida:**")
                st.info(st.session_state.get("ultima_pergunta", ""))
            with col_r:
                correcao = st.text_area("Como você responderia exatamente?", value=st.session_state.get("ultima_resposta", ""), height=100)
                if st.button("💾 Salvar na Memória (Atualizar Persona)", type="primary"):
                    res_aprendizado = aprender_com_correcao(
                        motor=motor,
                        pergunta=st.session_state.ultima_pergunta,
                        resposta_corrigida=correcao,
                        autor=perfil.get("nome", "Usuário")
                    )
                    if res_aprendizado["sucesso"]:
                        st.success(res_aprendizado["mensagem"])
                        # Atualiza no chat atual também
                        if st.session_state.chat_persona_historico:
                            st.session_state.chat_persona_historico[-1]["texto"] = correcao
                        st.rerun()
                    else:
                        st.error(res_aprendizado.get("motivo", "Erro ao salvar"))

# ==============================================================================
# ABA 2: INGESTÃO DE CONVERSAS DO WHATSAPP
# ==============================================================================
with tab_alimentar:
    st.subheader("📥 Ingestão de Histórico do WhatsApp")
    
    # Seção 1: Conexão Direta com o wpp-ai-summarizer
    with st.container(border=True):
        st.markdown("### ⚡ Conexão Nativa com o Bot (`wpp-ai-summarizer`)")
        st.caption("Conectado diretamente ao banco de dados SQLite onde o bot grava as suas conversas reais do WhatsApp.")
        
        caminho_sqlite = CAMINHO_PADRAO_WPP_SQLITE
        if caminho_sqlite is None:
            st.warning("⚠️ Variável WPP_SQLITE_PATH não configurada no .env. Configure o caminho do SQLite do bot para sincronização.")
        elif caminho_sqlite.exists():
            st.success(f"✅ Banco de dados encontrado: `{caminho_sqlite.name}` ({caminho_sqlite.stat().st_size / (1024*1024):.2f} MB)")
            c1, c2 = st.columns([2, 1])
            with c1:
                st.write("Identificamos o banco de dados arquivado pelo bot, pronto para sincronização.")
            with c2:
                if st.button("🚀 Sincronizar Tudo do Bot Agora", type="primary", use_container_width=True):
                    with st.spinner("Lendo histórico do SQLite e indexando diálogos no ChromaDB..."):
                        res_sync = sincronizar_banco_wpp_summarizer(motor, caminho_sqlite, nome_usuario=perfil.get("nome", "Usuário"))
                        if res_sync["sucesso"]:
                            st.success(f"🎉 Sincronizado! **{res_sync['pares_indexados']} diálogos reais** indexados no ChromaDB. Total na memória: {res_sync['total_memoria']}.")
                            st.rerun()
                        else:
                            st.error(res_sync.get("motivo"))
        else:
            st.info(f"Banco do bot não localizado em `{caminho_sqlite}`. Você pode usar a importação manual abaixo.")

    st.divider()
    st.markdown("### 📂 Ingestão Manual (Exportação .txt ou Colar)")
    st.markdown("""
    Você também pode:
    1. **Exportar uma conversa no WhatsApp** (no celular: *Mais opções > Mais > Exportar conversa > Sem mídia*) e enviar o `.txt` abaixo.
    2. **Ou colar trechos de conversa** diretamente no campo de texto.
    """)
    
    col_cfg1, col_cfg2 = st.columns([1, 2])
    with col_cfg1:
        nome_usuario = st.text_input("Seu nome no WhatsApp", value=perfil.get("nome", "Usuário"), help="Usado para saber quais mensagens foram enviadas por você.")
    
    tipo_entrada = st.radio("Forma de entrada manual", ["📂 Enviar arquivo .txt exportado", "✍️ Colar texto da conversa"], horizontal=True)
    conteudo_chat = ""
    
    if tipo_entrada == "📂 Enviar arquivo .txt exportado":
        arquivo = st.file_uploader("Arquivo de conversa do WhatsApp (.txt)", type=["txt"])
        if arquivo is not None:
            conteudo_chat = arquivo.getvalue().decode("utf-8", errors="ignore")
    else:
        conteudo_chat = st.text_area("Cole trechos de conversa aqui", height=200, placeholder="[14/08/2026, 10:15] Amigo: E aí, como tá o projeto?\n[14/08/2026, 10:16] Você: Fala irmão! Tá show, rodando liso aqui.")
        
    if st.button("⚡ Processar e Indexar no Banco de Memória", type="primary", disabled=not bool(conteudo_chat.strip())):
        with st.spinner("Parseando mensagens e extraindo pares de conversas..."):
            mensagens = parsear_exportacao_whatsapp(conteudo_chat)
            if not mensagens:
                st.warning("Nenhuma mensagem reconhecida no formato do WhatsApp. Verifique se o texto tem datas/horas padrão.")
            else:
                autores = identificar_autores(mensagens)
                pares = extrair_pares_conversa(mensagens, nome_usuario)
                
                if not pares:
                    st.warning(f"Reconhecemos {len(mensagens)} mensagens, mas nenhuma do autor '{nome_usuario}'. Autores encontrados no texto: {list(autores.keys())}")
                else:
                    qtd_salva = motor.indexar_pares(pares)
                    st.success(f"🎉 Sucesso! {len(mensagens)} mensagens analisadas. **{qtd_salva} novos pares de diálogo** indexados no ChromaDB!")
                    
                    st.markdown("#### Amostra dos Diálogos Aprendidos:")
                    for p in pares[:3]:
                        st.write(f"- **{p.interlocutor}:** {p.pergunta}")
                        st.write(f"  👉 **{nome_usuario}:** {p.resposta}")
                    st.rerun()

# ==============================================================================
# ABA 3: PERFIL DE ESTILO & DIRETRIZES
# ==============================================================================
with tab_perfil:
    st.subheader("🧬 DNA de Estilo & Diretrizes de Pensamento")
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Média de Palavras", f"{perfil.get('media_palavras', 14)} palavras")
    c2.metric("Média de Caracteres", f"{perfil.get('media_chars', 70)} caracteres")
    c3.metric("Uso de Pontuação Final", f"{perfil.get('usa_pontuacao_final_pct', 30)}%")
    
    st.markdown("#### Diretrizes de Pensamento (Como você raciocina)")
    st.caption("A IA consulta essas diretrizes antes de qualquer resposta:")
    
    diretrizes_atuais = "\n".join(perfil.get("diretrizes_pensamento", []))
    novas_diretrizes = st.text_area("Diretrizes de Raciocínio (uma por linha)", value=diretrizes_atuais, height=140)
    
    col_t, col_e = st.columns(2)
    with col_t:
        termos_str = ", ".join(perfil.get("termos_frequentes", []))
        novos_termos = st.text_input("Expressões e Gírias Típicas (separadas por vírgula)", value=termos_str)
    with col_e:
        emojis_str = " ".join(perfil.get("emojis_frequentes", []))
        novos_emojis = st.text_input("Emojis Frequentes", value=emojis_str)
        
    if st.button("💾 Salvar Alterações de Estilo"):
        perfil["diretrizes_pensamento"] = [d.strip() for d in novas_diretrizes.splitlines() if d.strip()]
        perfil["termos_frequentes"] = [t.strip() for t in novos_termos.split(",") if t.strip()]
        perfil["emojis_frequentes"] = novos_emojis.split()
        salvar_perfil_estilo(perfil)
        st.success("Perfil de estilo atualizado!")
        st.rerun()
