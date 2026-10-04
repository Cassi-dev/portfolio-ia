import os
import time

import chromadb
import pandas as pd
import streamlit as st

import registro
from core import llm
from core.config import MODELO_GEMINI
from core.embeddings import EmbeddingFunctionMultilingue
from core.llm import FalhaLLM, criar_cliente, gerar_texto
from indexacao import (
    extrair_paginas, hash_do_arquivo, indexar_arquivo, indice_desatualizado, listar_documentos,
    remover_documento, sincronizar_pasta,
)
from recuperacao import MODOS, Recuperador, decidir, obter_reranker
from resposta import reescrever_pergunta, responder_com_citacoes
from seguranca_rag import sanitizar_trecho
from texto_util import como_citacao, sem_cabecalho

st.set_page_config(page_title="Chatbot RAG - Projeto 01", page_icon="🤖", layout="wide")

BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_DOCUMENTOS = os.path.join(BASE, "documentos")
PASTA_BANCO = os.path.join(BASE, "banco_vetorial")
os.makedirs(PASTA_DOCUMENTOS, exist_ok=True)
os.makedirs(PASTA_BANCO, exist_ok=True)

DESCRICAO_MODOS = {
    "vetorial_rerank": "Vetorial + reranker (recomendado: separa melhor o 'não sei', ~0,7 s a mais)",
    "vetorial": "Só vetorial (rápido, ~30 ms)",
    "hibrido_rerank": "Híbrido (vetor + palavras-chave) + reranker",
    "hibrido": "Híbrido (vetor + palavras-chave)",
    "bm25": "Só palavras-chave (BM25)",
}


@st.cache_resource
def obter_colecao():
    cliente = chromadb.PersistentClient(path=PASTA_BANCO)
    return cliente.get_or_create_collection(
        name="meus_documentos_ptbr", embedding_function=EmbeddingFunctionMultilingue(), metadata={"hnsw:space": "cosine"}
    )


@st.cache_resource
def obter_recuperador(modo: str):
    return Recuperador(obter_colecao(), modo)


colecao = obter_colecao()


def ocr_com_gemini(client, dados_pdf):
    from google.genai import types
    pdf_part = types.Part.from_bytes(data=bytes(dados_pdf), mime_type="application/pdf")
    prompt_ocr = (
        "Você é um especialista em OCR. Extraia e transcreva fielmente todo o conteúdo textual "
        "deste documento, mantendo a estrutura de tópicos, seções e listas. Não invente nada e não faça resumos."
    )
    return gerar_texto(client, [pdf_part, prompt_ocr], usar_cache=False)


def processar_e_indexar_arquivo(uploaded_file, api_key_informada=""):
    nome_arquivo = os.path.basename(uploaded_file.name)
    caminho_salvar = os.path.join(PASTA_DOCUMENTOS, nome_arquivo)
    file_bytes = uploaded_file.getbuffer()
    with open(caminho_salvar, "wb") as f:
        f.write(file_bytes)

    try:
        paginas_texto = extrair_paginas(caminho_salvar)
    except Exception as e:
        st.error(f"Não consegui ler este arquivo ({type(e).__name__}: {e}). Ele está corrompido?")
        return 0, False

    client = None
    if api_key_informada.strip():
        try:
            client = criar_cliente(api_key_informada)
        except FalhaLLM as e:
            st.warning(f"Não foi possível iniciar o cliente do Gemini ({e}). Seguindo em modo local.")

    usou_ocr = False
    if not paginas_texto and nome_arquivo.lower().endswith(".pdf"):
        if client is None:
            st.warning("⚠️ Este PDF é uma imagem escaneada. Cole sua chave Gemini na barra lateral para ativar a leitura visual (OCR) automática!")
            return 0, False
        try:
            texto_extraido = ocr_com_gemini(client, file_bytes)
        except FalhaLLM as e:
            st.error(f"Erro no OCR do Gemini: {e}")
            return 0, False
        if texto_extraido.strip():
            paginas_texto.append((1, texto_extraido.strip()))
            usou_ocr = True

    if not paginas_texto:
        return 0, False

    resumo_contexto = None
    if client is not None:
        texto_completo = " ".join(t for _, t in paginas_texto)
        try:
            resumo_contexto = gerar_texto(client, (
                f"Analise o texto abaixo do arquivo '{nome_arquivo}'. "
                "Gere uma síntese de 2 a 3 frases explicando qual é o contexto geral, tema e objetivo principal deste documento:\n\n"
                f"{texto_completo[:4000]}"
            ), temperatura=0.2)
        except FalhaLLM:
            resumo_contexto = None

    return indexar_arquivo(colecao, nome_arquivo, paginas_texto, resumo_contexto, hash_arquivo=hash_do_arquivo(caminho_salvar)), usou_ocr


def preparar_reranker():
    """Carrega o reranker uma vez (~470 MB no primeiro uso). Se não der, a busca cai para só vetorial."""
    try:
        obter_reranker()
        return True
    except Exception as e:
        st.warning(f"Não consegui carregar o reranker ({type(e).__name__}); usando só a busca vetorial.")
        return False


# ==========================================
# BARRA LATERAL
# ==========================================
with st.sidebar:
    st.header("⚙️ Painel do RAG")

    st.subheader("🔑 Conexão com LLM")
    api_key = st.text_input("Chave Google Gemini API:", type="password", placeholder="Cole sua chave aqui")
    if api_key.strip():
        if st.button("🔍 Validar Chave API"):
            with st.spinner("Testando conexão com Gemini..."):
                try:
                    gerar_texto(criar_cliente(api_key), "Responda apenas: OK", usar_cache=False)
                    st.success(f"✅ Chave válida! Conectado com sucesso ao {MODELO_GEMINI}.")
                except FalhaLLM as e:
                    st.error(f"❌ Erro ao validar chave: {e}")
    else:
        st.info("ℹ️ Sem chave: Modo 100% Local (entrega os trechos e fontes diretas).")

    st.divider()
    st.subheader("📂 Adicionar Documento")
    arquivo_enviado = st.file_uploader("Arraste um PDF (nativo ou scan), TXT ou MD:", type=["pdf", "txt", "md"])
    if arquivo_enviado is not None and st.button("📥 Processar e Guardar no Banco Local"):
        with st.spinner("Analisando documento..."):
            qtd, usou_ocr = processar_e_indexar_arquivo(arquivo_enviado, api_key)
            if qtd > 0:
                st.success(f"{'👁️ Scan detectado! OCR extraiu o texto e gerou' if usou_ocr else '⚡ Indexado com sucesso!'} {qtd} blocos. "
                           "Reenviar o mesmo arquivo substitui os blocos, sem duplicar.")
                time.sleep(1.5)
                st.rerun()

    st.divider()
    st.subheader("📚 Documentos indexados")
    documentos = listar_documentos(colecao)
    if documentos:
        st.dataframe(pd.DataFrame(documentos).rename(columns={"arquivo": "Arquivo", "blocos": "Blocos", "paginas": "Págs", "secoes": "Seções"}),
                     hide_index=True, use_container_width=True)
        escolhidos = st.multiselect("Buscar somente em:", [d["arquivo"] for d in documentos], placeholder="Todos os documentos")
        with st.expander("🗑️ Remover um documento"):
            alvo = st.selectbox("Documento:", [d["arquivo"] for d in documentos], key="alvo_remocao")
            apagar_arquivo = st.checkbox("Apagar também o arquivo da pasta documentos/", value=True)
            if st.button("Remover", key="btn_remover"):
                remover_documento(colecao, alvo, PASTA_DOCUMENTOS if apagar_arquivo else None)
                st.success(f"'{alvo}' removido do índice.")
                time.sleep(1)
                st.rerun()
    else:
        escolhidos = []
        st.caption("Nenhum documento indexado ainda.")
    if st.button("🔄 Sincronizar a pasta documentos/"):
        with st.spinner("Sincronizando (só reindexa o que mudou)..."):
            r = sincronizar_pasta(colecao, PASTA_DOCUMENTOS)
        st.success(f"Indexados: {len(r['indexados'])} · sem mudança: {len(r['pulados'])} · removidos: {len(r['removidos'])}")
        time.sleep(1)
        st.rerun()
    if documentos and indice_desatualizado(colecao):
        st.info("ℹ️ Parte do índice está no formato antigo (sem seção). Clique em **Sincronizar** para ganhar a busca por seção.")

    st.divider()
    st.subheader("🎛️ Busca")
    modo = st.selectbox("Modo de busca:", MODOS, index=MODOS.index("vetorial_rerank"), format_func=lambda m: DESCRICAO_MODOS[m])
    usa_rerank = modo.endswith("_rerank")
    if usa_rerank:
        limiar_rerank = st.slider("Nota mínima do reranker:", -8.0, 5.0, -4.0, 0.1,
                                  help="Abaixo disso o bot diz que não sabe. Calibrado com 68 perguntas (veja o README); ajuste ao seu conjunto de documentos.")
        limiar_distancia = 0.16
    else:
        limiar_rerank = None
        limiar_distancia = st.slider("Distância máxima (modo 'não sei'):", 0.05, 0.40, 0.16, 0.01,
                                     help="Distâncias maiores que isso são recusadas para evitar alucinação.")
    top_k = st.number_input("Blocos a recuperar (Top K):", min_value=1, max_value=5, value=3)

    st.divider()
    with st.expander("📊 Métricas de uso"):
        m = registro.resumo_metricas(registro.carregar())
        if m["consultas"]:
            st.write(f"Consultas: **{m['consultas']}** · 'não sei': **{m['pct_nao_sei']}%**")
            st.write(f"Latência da busca: mediana **{m['latencia_mediana_ms']} ms**, p95 **{m['latencia_p95_ms']} ms**")
            if m["pct_positivo"] is not None:
                st.write(f"Feedback positivo: **{m['pct_positivo']}%** de {m['com_feedback']} votos")
        else:
            st.caption("Ainda sem consultas registradas. (Desligue o registro com a variável RAG_LOG=0.)")
        est = llm.estatisticas()
        if est["chamadas_api"]:
            st.caption(f"IA nesta sessão: {est['chamadas_api']} chamadas, latência média {est['latencia_media_ms']} ms, "
                       f"{est['tokens_entrada']} tokens de entrada / {est['tokens_saida']} de saída.")

    if st.button("🗑️ Limpar Conversa"):
        st.session_state.mensagens = []
        st.rerun()

# ==========================================
# TELA PRINCIPAL DE CHAT
# ==========================================
total_docs = colecao.count()
st.title("🤖 Chatbot RAG sobre Documentos")
st.markdown(f"**Base local ativa:** {total_docs} blocos de conhecimento indexados no seu ChromaDB.")

if "mensagens" not in st.session_state:
    st.session_state.mensagens = [
        {"role": "assistant", "content": "Olá! Posso responder perguntas estritamente baseadas nos seus documentos locais e auditar cada fonte."}
    ]


def formatar_fonte(f) -> str:
    local = f"pág. {f['pagina']}" + (f" · seção “{f['secao']}”" if f.get("secao") else "")
    return f"📄 **{f['arquivo']}** ({local}) · {f.get('tipo', 'detalhe')}"


def mostrar_fontes(fontes):
    with st.expander("🔍 Ver Fontes Auditáveis e Métricas"):
        for f in fontes:
            st.write(formatar_fonte(f))
            partes = [f"Distância: {f['distancia']:.4f}" if f.get("distancia") is not None else None,
                      f"Reranker: {f['nota_rerank']:.2f}" if f.get("nota_rerank") is not None else None]
            st.caption(" · ".join(p for p in partes if p))
            if f.get("suspeito"):
                st.warning("⚠️ Este trecho parece conter instruções dirigidas ao modelo. Foi tratado como dado, não como ordem.")
            st.info(f["texto"])


def botoes_de_feedback(indice, msg):
    identificador = msg.get("id_consulta")
    if not identificador:
        return
    if msg.get("voto"):
        st.caption("Obrigado pelo feedback!")
        return
    c1, c2, _ = st.columns([1, 1, 8])
    if c1.button("👍", key=f"up_{indice}_{identificador}"):
        registro.registrar_feedback(identificador, 1)
        msg["voto"] = 1
        st.rerun()
    if c2.button("👎", key=f"down_{indice}_{identificador}"):
        registro.registrar_feedback(identificador, -1)
        msg["voto"] = -1
        st.rerun()


for i, msg in enumerate(st.session_state.mensagens):
    with st.chat_message(msg["role"]):
        (st.warning if msg.get("estilo") == "aviso" else st.markdown)(msg["content"])
        for aviso in msg.get("avisos", []):
            st.warning(aviso)
        if msg.get("fontes"):
            mostrar_fontes(msg["fontes"])
        if msg["role"] == "assistant":
            botoes_de_feedback(i, msg)


def responder(prompt: str) -> dict:
    """Busca, decide e (com chave) gera a resposta com citações. Devolve a mensagem do assistente pronta para o histórico."""
    historico = [m for m in st.session_state.mensagens[1:-1] if m["role"] in ("user", "assistant")]
    client = None
    if api_key.strip():
        try:
            client = criar_cliente(api_key)
        except FalhaLLM as e:
            st.warning(f"Não foi possível iniciar o cliente do Gemini ({e}). Seguindo em modo local.")

    pergunta_busca, reescreveu, _ = reescrever_pergunta(client, historico, prompt)

    modo_efetivo, limiar_r = modo, limiar_rerank
    if usa_rerank:
        with st.spinner("Carregando o reranker (só na primeira vez, ~470 MB)..."):
            if not preparar_reranker():
                modo_efetivo, limiar_r = ("vetorial" if modo == "vetorial_rerank" else "hibrido"), None
    res = obter_recuperador(modo_efetivo).buscar(pergunta_busca, k=top_k, arquivos=escolhidos or None)
    decisao = decidir(res, limiar_distancia, limiar_r)

    fontes, suspeitos = [], set()
    for n, t in enumerate(res.trechos, start=1):
        _, motivos = sanitizar_trecho(t.texto)
        if motivos:
            suspeitos.add(n)
        fontes.append({"arquivo": t.arquivo, "pagina": t.pagina, "secao": t.secao, "tipo": t.tipo, "distancia": t.distancia,
                       "nota_rerank": t.nota_rerank, "texto": t.texto, "suspeito": bool(motivos)})

    rodape = f"*Busca: {modo_efetivo} · {res.latencias_ms['total']:.0f} ms"
    rodape += f" · pergunta entendida como: “{pergunta_busca}”*" if reescreveu else "*"
    msg = {"role": "assistant", "fontes": fontes, "avisos": []}
    status = "nao_sei"

    if not decisao.responder:
        msg.update(estilo="aviso", content=("🚫 **[Modo Não Sei Ativado]**\n\nNão encontrei essa informação nos seus documentos "
                                            f"com confiança suficiente.\n\n*({decisao.motivo})*\n\n{rodape}"))
    elif client is None:
        t0 = res.trechos[0]
        local = f" (seção “{t0.secao}”)" if t0.secao else ""
        msg["content"] = f"Encontrado em **{t0.arquivo}**{local}:\n\n{como_citacao(sem_cabecalho(t0.texto, t0.secao))}\n\n{rodape}"
        status = "respondeu"
    else:
        r = responder_com_citacoes(client, pergunta_busca, res.trechos)
        suspeitos |= set(r.trechos_suspeitos)
        if r.status == "respondida":
            msg["content"] = f"{r.texto}\n\n✅ *{r.citacoes_verificadas}/{r.citacoes_total} citações conferem nos documentos.* {rodape}"
            status = "respondeu"
        elif r.status == "sem_base":
            msg.update(estilo="aviso", content=f"🤔 Os trechos encontrados não bastam para responder com segurança.\n\n{rodape}")
            status = "nao_sei_ia"
        else:
            t0 = res.trechos[0]
            motivo = r.motivo or "a resposta não pôde ser conferida"
            msg.update(estilo="aviso", content=(f"⚠️ Não consegui confirmar a resposta nos documentos ({motivo}). Em vez de mostrar um texto sem "
                                                f"comprovação, mostro o trecho mais relevante (**{t0.arquivo}**):\n\n"
                                                f"{como_citacao(sem_cabecalho(t0.texto, t0.secao))}\n\n{rodape}"))
            status = "nao_verificada" if r.status == "nao_verificada" else "falhou"

    if suspeitos and decisao.responder:
        msg["avisos"].append(f"🛡️ O(s) trecho(s) {', '.join(map(str, sorted(suspeitos)))} parece(m) conter instruções para o modelo. "
                             "Foram tratados como dado, mas confira a fonte.")

    msg["id_consulta"] = registro.registrar_consulta({
        "pergunta": prompt, "pergunta_busca": pergunta_busca, "modo": modo_efetivo, "decisao": status, "motivo_decisao": decisao.motivo,
        "latencias_ms": {k: round(v, 1) for k, v in res.latencias_ms.items()},
        "trechos": [{k: f[k] for k in ("arquivo", "secao", "distancia", "nota_rerank")} for f in fontes],
        "filtro_arquivos": escolhidos,
    })
    return msg


if prompt := st.chat_input("Faça uma pergunta sobre seus documentos..."):
    st.session_state.mensagens.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if total_docs == 0:
        st.session_state.mensagens.append({"role": "assistant", "estilo": "aviso",
                                           "content": "O banco de dados está vazio. Envie um arquivo pelo menu lateral primeiro!"})
    else:
        with st.chat_message("assistant"):
            with st.spinner("Buscando nos documentos..."):
                st.session_state.mensagens.append(responder(prompt))
    st.rerun()
