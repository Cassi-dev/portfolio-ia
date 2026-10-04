import streamlit as st
import os
import sys

diretorio_atual = os.path.dirname(os.path.abspath(__file__))
if diretorio_atual not in sys.path:
    sys.path.append(diretorio_atual)

from core.llm import FalhaLLM, bloqueio_restante, criar_cliente, estatisticas
from transcricao_youtube import (
    SemTranscricao,
    extrair_id_video, obter_metadados_video, obter_transcricao_formatada, segundos_para_tempo, tempo_para_segundos
)
from agente_map_reduce import etapa_map, etapa_reduce, gerar_quiz, avisos_de_degradacao
from cortador_video import ALTURAS, FalhaNoCorte, PASTA_CORTES, sugerir_cortes_virais, baixar_e_cortar_clipe
from gerador_roteiro import gerar_roteiro_viral
from renderizador_video_tacto import (
    renderizar_video_tacto_animado_completo,
    ROTEIRO_PUBLICITARIO_TACTO,
    PASTA_OUTPUT as PASTA_VIDEOS,
    PASTA_STORYBOARD,
    moeda_br,
)
from ui_reels_livre import tela_criar_video
from ui_edicao import tela_edicao
from ui_local import LINK, tela_video_local
import fala_local
from core.midia import localizar_ffmpeg
from ui_video_pronto import tela_video_pronto

st.set_page_config(
    page_title="Estúdio de Vídeos com IA",
    page_icon="🎬",
    layout="wide"
)

os.makedirs(PASTA_CORTES, exist_ok=True)
os.makedirs(PASTA_VIDEOS, exist_ok=True)

# ==========================================
# BARRA LATERAL (CONFIGURAÇÕES)
# ==========================================
with st.sidebar:
    st.header("🎬 Estúdio de Vídeos")
    st.caption("Roteiros, vídeos, cortes e locução com IA")

    api_key = st.text_input("Chave Google Gemini API:", type="password", placeholder="Cole sua chave aqui")
    if api_key.strip():
        st.success("✅ Conexão com Gemini configurada")
    else:
        st.info("ℹ️ Sem chave: o roteiro só divide o seu texto em cenas (modo degradado)")

    if (parado := bloqueio_restante()) > 0:
        st.error(f"⏳ Cota da API esgotada. Novas chamadas só daqui a {parado:.0f}s — até lá, tudo sai degradado.")
    uso = estatisticas()
    if uso["chamadas_api"] or uso["cache_hits"]:
        linhas = [f"Nesta sessão: **{uso['chamadas_api']}** chamada(s) à API e {uso['cache_hits']} aproveitada(s) "
                  "do cache (repetir a mesma análise não gasta de novo)."]
        if uso["custo_usd"] is not None:
            pensou = f" + {uso['tokens_pensamento']:,} de pensamento" if uso["tokens_pensamento"] else ""
            linhas.append(f"{uso['tokens_entrada']:,} tokens de entrada, {uso['tokens_saida']:,} de saída{pensou} "
                          f"— cerca de **US$ {uso['custo_usd']:.4f}**.")
        st.caption(" ".join(linhas).replace(",", "."))

# ==========================================
# TELA PRINCIPAL
# ==========================================
st.title("🎬 Estúdio de Vídeos com IA")
st.caption("Crie vídeos verticais (Reels, TikTok, Shorts) sobre qualquer assunto, analise vídeos do YouTube e gere cortes.")

MODO_LIVRE = "🎞️ Criar vídeo de qualquer assunto"
MODO_TACTO = "⚡ Reels oficial da TACTO Studio"
MODO_YOUTUBE = "🎥 Analisar Vídeo do YouTube (Map-Reduce + Fatiador)"
MODO_LOCAL = "📁 Editar vídeo do computador ou de outra rede"
modo_criacao = st.radio("O que você quer fazer?", [MODO_LIVRE, MODO_TACTO, MODO_YOUTUBE, MODO_LOCAL], horizontal=True,
                        key="modo_app")


def abrir_no_editor(url: str) -> None:
    """Leva um vídeo sem legenda do modo de análise para o editor, com o link já preenchido."""
    st.session_state["modo_app"] = MODO_LOCAL
    st.session_state["loc_origem"] = LINK
    st.session_state["loc_url"] = url
    st.session_state.pop("yt_sem_legenda", None)

# ==========================================================
# MODO 1: VÍDEO DE QUALQUER ASSUNTO (contexto -> roteiro editável -> .mp4)
# ==========================================================
if modo_criacao == MODO_LIVRE:
    tela_criar_video(api_key)

# ==========================================================
# MODO 4: EDITOR DE VÍDEO LOCAL (arquivo do computador ou link de outra rede)
# ==========================================================
elif modo_criacao == MODO_LOCAL:
    tela_video_local(api_key)

# ==========================================================
# MODO 2: REELS OFICIAL TACTO STUDIO (IDENTIDADE OFICIAL & VÍDEO ANIMADO, 4 CENAS FIXAS)
# ==========================================================
elif modo_criacao == MODO_TACTO:
    # ------------------------------------------------------
    # DESTAQUE MÁXIMO: VÍDEO OFICIAL FINAL RENDERIZADO (ANIMADO)
    # ------------------------------------------------------
    caminho_video_animado = os.path.join(PASTA_VIDEOS, "reels_tacto_animado_oficial.mp4")
    caminho_video_oficial = caminho_video_animado if os.path.exists(caminho_video_animado) else os.path.join(PASTA_VIDEOS, "reels_tacto_oficial.mp4")

    st.markdown("### 🎥 Vídeo Reels Oficial Renderizado (Pronto para Publicar)")
    st.caption("Vídeo vertical em alta definição (1080x1920 - 9:16) com locução neural em português, animações procedurais a 24 FPS (clique de botões, barras de progresso, contador financeiro, mockup PWA e logo oficial).")

    col_v1, col_v2 = st.columns([1.2, 1.8])
    with col_v1:
        if os.path.exists(caminho_video_oficial):
            st.video(caminho_video_oficial)
            with open(caminho_video_oficial, "rb") as f_v:
                st.download_button(
                    "📥 Baixar Vídeo Reels Animado (.mp4)",
                    data=f_v.read(),
                    file_name="reels_tacto_animado_oficial.mp4",
                    mime="video/mp4",
                    use_container_width=True
                )
        else:
            st.warning("Vídeo ainda não renderizado. Clique no botão abaixo para gerar!")

    with col_v2:
        st.markdown("#### ⚡ Central de Renderização de Vídeo Animado")
        st.write("Motor de animação procedural em camadas: Paleta oficial Obsidian Dark (`#0D1117`), Hyper Cyan (`#00F0FF`) e Electric Mint (`#10F984`).")
        
        c_r1, c_r2 = st.columns(2)
        with c_r1:
            voz_render = st.selectbox(
                "Voz da Locução:",
                ["pt-BR-AntonioNeural (Masculina Firme)", "pt-BR-FranciscaNeural (Feminina Expressiva)"],
                key="voz_render_video"
            )
            v_id_render = "pt-BR-AntonioNeural" if "Antonio" in voz_render else "pt-BR-FranciscaNeural"
        with c_r2:
            st.write("")
            st.write("")
            btn_render_completo = st.button("🚀 Renderizar Novo Reels Animado (.mp4)", use_container_width=True)

        if btn_render_completo:
            with st.spinner("Renderizando vídeo animado completo (quadro a quadro com áudio neural e FFmpeg)..."):
                prog_bar = st.progress(0.1, text="Iniciando esteira de produção...")
                def cb_prog(prog, msg):
                    prog_bar.progress(min(1.0, prog), text=msg)
                renderizar_video_tacto_animado_completo(ROTEIRO_PUBLICITARIO_TACTO, "reels_tacto_animado_oficial.mp4", voz=v_id_render, progresso_callback=cb_prog)
                prog_bar.progress(1.0, text="Vídeo animado compilado com sucesso!")
                st.success("Vídeo animado pronto!")
                st.rerun()

        st.info("💡 **Duração:** ~41 segundos (máxima retenção para Instagram Reels e TikTok).")
        st.success("🎯 **Identidade:** Brandboard oficial da TACTO Studio com Monograma N-Link e case Casa Exemplo.")

    st.divider()

    # ------------------------------------------------------
    # SEÇÃO: SIMULADOR INTERATIVO AO VIVO DO SISTEMA TACTO
    # ------------------------------------------------------
    st.markdown("### 📱 Simulador Interativo do Sistema TACTO Studio")
    st.caption("Experimente as interações do sistema em tempo real — as mesmas que aparecem animadas no vídeo:")

    sim_c1, sim_c2, sim_c3 = st.columns(3)

    with sim_c1:
        with st.container(border=True):
            st.markdown("#### ⚡ 1. Velocidade do PWA")
            st.caption("Abertura sem passar pela App Store")
            if st.button("🚀 Testar Benchmark PWA", use_container_width=True, key="btn_sim_pwa"):
                st.success("⚡ **Tempo de Carregamento:** 0.28s")
                st.metric(label="Lighthouse Mobile Score", value="100 / 100", delta="+68 vs Apps Nativos")
                st.write("✓ Service Worker ativo (Instant Cache)")
                st.write("✓ Instalável na tela inicial em 1 toque")
                st.caption("Valores ilustrativos de demonstração, não medidos nesta execução.")

    with sim_c2:
        with st.container(border=True):
            st.markdown("#### 🍔 2. Pedido Direto (Casa Exemplo)")
            st.caption("Cardápio Sensorial + CAC Zero")
            if st.button("🛒 Simular Pedido de Hambúrguer", use_container_width=True, key="btn_sim_pedido"):
                preco = 48.90
                taxa_ifood = preco * 0.27
                st.success(f"**Venda:** R$ {preco:.2f} via Pix Direto")
                col_sub1, col_sub2 = st.columns(2)
                col_sub1.metric("Taxa iFood (27%)", f"- R$ {taxa_ifood:.2f}")
                col_sub2.metric("Margem TACTO (0%)", f"+ R$ {preco:.2f}")
                st.info("📲 Mensagem enviada direto pro WhatsApp da cozinha!")

    with sim_c3:
        with st.container(border=True):
            st.markdown("#### 📊 3. Análise com IA (Text-to-SQL)")
            st.caption("Consulta em linguagem natural no banco real")
            if st.button("🔍 'Quanto faturamos no PWA?'", use_container_width=True, key="btn_sim_sql"):
                import sqlite3
                caminho_db = os.path.join(diretorio_atual, "..", "projeto_05_gerador_sql", "tacto_negocios.db")
                if os.path.exists(caminho_db):
                    conn = sqlite3.connect(f"file:{os.path.abspath(caminho_db)}?mode=ro", uri=True)
                    dados_vendas = conn.execute(
                        "SELECT canal_venda, COUNT(*), SUM(valor_total) FROM pedidos WHERE status = 'Concluído' GROUP BY canal_venda ORDER BY 3 DESC"
                    ).fetchall()
                    conn.close()
                    for canal, qtd, tot in dados_vendas:
                        if canal == "PWA TACTO":
                            st.metric("Total no PWA TACTO", f"R$ {moeda_br(tot)}", f"{qtd} pedidos sem taxa")
                        else:
                            st.write(f"• {canal}: R$ {moeda_br(tot)} ({qtd} pedidos)")
                    st.caption("Pedidos concluídos, executado no SQLite `tacto_negocios.db` (dados de demonstração).")
                else:
                    st.warning("Base de demonstração não encontrada. Rode `python projeto_05_gerador_sql/banco_dados.py` para criá-la.")

    st.divider()

    # ------------------------------------------------------
    # SEÇÃO: PESQUISA DE CONCORRÊNCIA & POSICIONAMENTO B2B
    # ------------------------------------------------------
    st.markdown("### ⚔️ Inteligência Competitiva: Por Que a TACTO Vence a Concorrência?")
    st.caption("Dados reais apurados do mercado de foodservice brasileiro para ancoragem comercial:")

    col_c1, col_c2, col_c3 = st.columns(3)
    with col_c1:
        st.error("""
        **❌ iFood (Marketplace Tradicional)**
        * **23% a 27% de comissão** por cada pedido entregue.
        * **Clientes ocultos:** O restaurante não tem acesso a telefone, e-mail ou histórico.
        * **Repasse em até 30 dias:** Prejudica o fluxo de caixa diário.
        * **Concorrente no seu prato:** Mostra opções mais baratas logo abaixo do seu cardápio.
        """)
    with col_c2:
        st.warning("""
        **⚠️ Anota AI / Goomer (Plataformas Genéricas)**
        * **Mensalidades escaláveis** que aumentam conforme o volume de pedidos.
        * **Interfaces padrão:** Não transmitem o valor gastronômico de alta gastronomia.
        * **Robôs engessados:** Respostas mecânicas sem inteligência de produto ou cardápio.
        * **Falta de IA Integrada:** Sem análise preditiva de clientes ou suporte visual.
        """)
    with col_c3:
        st.success("""
        **⚡ TACTO Studio (Infraestrutura Própria)**
        * **0% de comissão:** Margem 100% no caixa do restaurante via Pix imediato.
        * **CAC Zero & Base Própria:** Todos os clientes são seus no WhatsApp e CRM.
        * **PWA Instantâneo (< 0.5s):** Sem atrito de download de App Store.
        * **Ecossistema de IA Nativo:** Atendente RAG 24/7, Sentimento e Dashboard SQL.
        """)

    st.divider()

    # ------------------------------------------------------
    # SEÇÃO: AS 4 FUNCIONALIDADES DO SISTEMA DA TACTO
    # ------------------------------------------------------
    st.markdown("### 🚀 As 4 Funcionalidades do Sistema Apresentadas no Vídeo:")
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        with st.container(border=True):
            st.markdown("#### ⚡ 1. PWA Ultra-Rápido (< 0.5s)")
            st.write("Sem download em lojas de apps. O cliente abre no 4G em milissegundos pelo QR Code ou Instagram e adiciona na tela inicial com 1 toque.")
        with st.container(border=True):
            st.markdown("#### 🍷 3. Cardápio Sensorial Imersivo")
            st.write("Fotos em alta resolução, histórias dos pratos e bebidas autorais, aumentando o ticket médio em 20% a 35% comparado ao PDF tradicional.")
    with col_f2:
        with st.container(border=True):
            st.markdown("#### 🤖 2. Atendente com IA no WhatsApp (RAG)")
            st.write("Responde instantaneamente sobre cardápio, tira dúvidas sobre alergênicos, faz recomendações e envia pedidos diretos para a cozinha.")
        with st.container(border=True):
            st.markdown("#### 📊 4. Dashboard Executivo Text-to-SQL")
            st.write("O proprietário pergunta em linguagem natural no WhatsApp e recebe métricas de vendas, faturamento e pratos mais vendidos em tempo real.")

    st.divider()

    # ------------------------------------------------------
    # SEÇÃO: STORYBOARD VISUAL DAS CENAS DO VÍDEO
    # ------------------------------------------------------
    st.markdown("### 🎬 Storyboard das Cenas Animadas do Vídeo:")
    tabs_cenas = st.tabs([f"Cena {i+1}: {c['tag']}" for i, c in enumerate(ROTEIRO_PUBLICITARIO_TACTO)])
    
    for i, (tab, c) in enumerate(zip(tabs_cenas, ROTEIRO_PUBLICITARIO_TACTO), 1):
        with tab:
            c_img_path = os.path.join(PASTA_STORYBOARD, f"cena_{i}.png")
            col_im, col_txt = st.columns([1, 2])
            with col_im:
                if os.path.exists(c_img_path):
                    st.image(c_img_path, caption=f"Frame Animado 9:16 da Cena {i}", use_container_width=True)
                else:
                    st.info("Frame será exibido após renderização.")
            with col_txt:
                st.subheader(f"📌 {c['titulo']}")
                st.markdown(f"**Tag:** `{c['tag']}`")
                st.markdown("🗣️ **Texto Narrado pela IA:**")
                st.info(f"\"{c['fala']}\"")
                if i == 1:
                    st.write("• **Animação Visual:** Contador financeiro de taxa de delivery crescendo em tempo real até 27%.")
                elif i == 2:
                    st.write("• **Animação Visual:** Mockup PWA da Casa Exemplo com bloco de demonstração, cursor animado e clique de pedido.")
                elif i == 3:
                    st.write("• **Animação Visual:** Digitação em tempo real de prompt Text-to-SQL e métricas financeiras atualizando.")
                elif i == 4:
                    st.write("• **Animação Visual:** Logo oficial da TACTO Studio com Monograma N-Link e botão de CTA pulsante.")
    st.divider()

    # ------------------------------------------------------
    # SEÇÃO: PACOTE DE POSTAGEM (LEGENDA + HASHTAGS)
    # ------------------------------------------------------
    st.markdown("### 📱 Pacote de Publicação para Redes Sociais:")
    col_p1, col_p2 = st.columns([2, 1])
    with col_p1:
        legenda_padrao = (
            "🚨 Você já calculou quanto dinheiro deixa na mesa todo mês em taxas de delivery?\n\n"
            "Enquanto plataformas tradicionais levam até 27% da sua margem bruta e escondem o contato dos seus próprios clientes fiéis, a TACTO Studio desenha infraestrutura digital de CAC Zero.\n\n"
            "⚡ PWA instantâneo (< 0.5s sem App Store)\n"
            "🤖 Atendente inteligente no WhatsApp 24/7\n"
            "🍷 Cardápio sensorial que eleva seu ticket médio\n"
            "📊 Dashboard de vendas direto no seu celular\n\n"
            "0% de comissão. 100% de controle.\n\n"
            "👉 Toque no link da bio e solicite uma demonstração ao vivo para a sua operação."
        )
        st.text_area("Legenda Otimizada para o Instagram:", value=legenda_padrao, height=180)
    with col_p2:
        hashtags_padrao = "#tactostudio #foodservice #restaurantes #bares #gestaogastronomica #caczero #cardapiodigital #pwa #inteligenciaartificial"
        st.text_area("Hashtags Estratégicas B2B:", value=hashtags_padrao, height=80)
        st.success("✅ Formato do Vídeo: 1080x1920 (Vertical 9:16)\n✅ Áudio: Estéreo AAC 192k\n✅ Codec: H.264 (Compatibilidade total com Instagram & TikTok)")

# ==========================================================
# MODO 3: ANALISAR VÍDEO LONGO DO YOUTUBE
# ==========================================================
else:
    url_padrao = "https://www.youtube.com/watch?v=M7lc1UVf-VE"
    url_video = st.text_input("Cole a URL do vídeo do YouTube para analisar e fatiar:", value=url_padrao)
    
    col_v, col_btn_yt = st.columns([3, 1])
    with col_v:
        try:
            st.video(url_video)
        except Exception:
            pass
    with col_btn_yt:
        st.write("")
        btn_processar_yt = st.button("🚀 Analisar Vídeo Completo (IA)", use_container_width=True, type="primary")
        btn_extrair_txt_rapido = st.button("📄 Extrair Apenas Conteúdo em TXT", use_container_width=True)

    def cliente_gemini():
        if not api_key.strip():
            return None
        try:
            return criar_cliente(api_key)
        except FalhaLLM as e:
            st.warning(f"Não foi possível iniciar o cliente do Gemini ({e}). Seguindo sem IA.")
            return None

    def analisar(video_id, url, dados_transcricao, metadados):
        """Resumo, quiz, cortes e roteiro — o mesmo caminho para a legenda do YouTube e a transcrição local."""
        client_gemini = cliente_gemini()
        with st.spinner("Executando Map-Reduce, quiz, cortes e roteiro..."):
            contexto = f"Vídeo: {metadados['titulo']}" + (f" (canal {metadados['canal']})" if metadados["canal"] else "") + ".\n\n"
            resumos_map = etapa_map(dados_transcricao['blocos'], client=client_gemini, contexto=contexto)
            sintese_final = etapa_reduce(resumos_map, titulo_video=metadados["titulo"], client=client_gemini, canal=metadados["canal"])
            st.session_state.resultado_youtube = {
                "metadados": metadados,
                "transcricao": dados_transcricao,
                "resumos_map": resumos_map,
                "sintese": sintese_final,
                "quiz": gerar_quiz(sintese_final, client=client_gemini),
                "cortes": sugerir_cortes_virais(dados_transcricao, client=client_gemini),
                "roteiro": gerar_roteiro_viral(dados_transcricao, client=client_gemini),
                "video_id": video_id,
                "url_video": url
            }
        st.success("Análise de vídeo concluída!")

    if btn_processar_yt:
        video_id = extrair_id_video(url_video)
        if not video_id:
            st.error("URL inválida: não encontrei um ID de vídeo do YouTube nesse endereço.")
        else:
            st.session_state.pop("yt_sem_legenda", None)
            try:
                with st.spinner("Baixando a transcrição do vídeo..."):
                    dados_transcricao = obter_transcricao_formatada(video_id)
                    metadados = obter_metadados_video(video_id)
            except SemTranscricao as e:
                # guardado na sessão: a mensagem e o botão têm que sobreviver ao próximo clique
                st.session_state["yt_sem_legenda"] = {"mensagem": str(e), "sem_legenda": e.sem_legenda,
                                                      "url": url_video, "video_id": video_id}
            except Exception as e:
                st.error(str(e))
            else:
                analisar(video_id, url_video, dados_transcricao, metadados)

    if btn_extrair_txt_rapido:
            video_id = extrair_id_video(url_video)
            if not video_id:
                st.error("URL inválida: não encontrei um ID de vídeo do YouTube nesse endereço.")
            else:
                st.session_state.pop("yt_sem_legenda", None)
                st.session_state.pop("resultado_youtube", None)
                try:
                    with st.spinner("Extraindo transcrição completa do vídeo em TXT..."):
                        dados_transcricao = obter_transcricao_formatada(video_id)
                        metadados = obter_metadados_video(video_id)
                        st.session_state["extracao_txt_direta"] = {
                            "metadados": metadados,
                            "transcricao": dados_transcricao,
                            "video_id": video_id,
                            "url_video": url_video
                        }
                        st.success("Conteúdo extraído com sucesso!")
                except SemTranscricao as e:
                    st.session_state["yt_sem_legenda"] = {"mensagem": str(e), "sem_legenda": e.sem_legenda,
                                                          "url": url_video, "video_id": video_id}
                except Exception as e:
                    st.error(str(e))
        
    if "extracao_txt_direta" in st.session_state and "resultado_youtube" not in st.session_state:
        dados_txt = st.session_state["extracao_txt_direta"]
        meta = dados_txt.get("metadados", {})
        transcricao = dados_txt["transcricao"]
        
        st.divider()
        st.subheader("📄 Conteúdo Integral do Vídeo em TXT")
        if meta.get("titulo"):
            st.markdown(f"#### {meta['titulo']}" + (f"  \n*{meta['canal']}*" if meta.get("canal") else ""))
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Duração", transcricao["duracao_formatada"])
        m2.metric("Idioma", transcricao["idioma"])
        m3.metric("Total de Blocos", transcricao["total_blocos"])
        
        fmt_col1, fmt_col2 = st.columns([1.5, 1])
        with fmt_col1:
            formato_txt = st.radio("Formato do texto:", ["Texto corrido limpo (sem minutagem)", "Texto estruturado com minutagem [00:00]"], horizontal=True, key="fmt_txt_direto")
        
        if "com minutagem" in formato_txt:
            linhas = [f"[{b['timestamp_formatado']}] {b['texto']}" for b in transcricao['blocos']]
        else:
            linhas = [b['texto'] for b in transcricao['blocos']]
            
        conteudo_txt_final = f"TÍTULO: {meta.get('titulo', 'Vídeo do YouTube')}\nCANAL: {meta.get('canal', '')}\nURL: {dados_txt.get('url_video', '')}\nDURAÇÃO: {transcricao['duracao_formatada']}\n" + ("="*50) + "\n\n" + "\n\n".join(linhas)
        
        with fmt_col2:
            st.write("")
            st.download_button(
                "📥 Baixar Arquivo .txt Completo",
                data=conteudo_txt_final,
                file_name=f"conteudo_{dados_txt['video_id']}.txt",
                mime="text/plain",
                use_container_width=True,
                type="primary"
            )
        
        st.text_area("Texto Integral Extraído:", value=conteudo_txt_final, height=350)

    if falha := st.session_state.get("yt_sem_legenda"):
        st.error(falha["mensagem"])
        if falha["sem_legenda"]:
            col_a, col_b = st.columns(2)
            if fala_local.disponivel():
                col_a.caption("**Transcrever no computador** (grátis): o reconhecimento de fala ouve o vídeo inteiro "
                              "e a análise segue normalmente. Leva cerca de metade da duração do vídeo — 10 min de "
                              "vídeo, uns 5 min. O texto erra mais nomes próprios que a legenda do YouTube.")
                transcrever = col_a.button("🎙️ Transcrever no computador e analisar", key="btn_transcrever_local")
            else:
                transcrever = False
                col_a.caption("O reconhecimento de fala local não está instalado (`pip install faster-whisper`).")
            col_b.caption("**Ou editar sem a análise**: você escolhe o trecho, a receita e a marca d'água; a legenda "
                          "sai do reconhecimento local, da IA, de um .srt, ou fica de fora.")
            col_b.button("📁 Editar este vídeo no editor, sem análise", on_click=abrir_no_editor, args=(falha["url"],))
            if transcrever:
                barra = st.progress(0.0, text="Baixando o áudio do vídeo...")
                try:
                    dados_transcricao = fala_local.transcrever_video(
                        falha["video_id"], falha["url"], localizar_ffmpeg(),
                        progresso=lambda f: barra.progress(f, text=f"Ouvindo o vídeo... {f:.0%}"))
                except (SemTranscricao, FalhaNoCorte) as e:
                    barra.empty()
                    st.error(f"Não deu para transcrever: {e}")
                else:
                    barra.empty()
                    st.session_state.pop("yt_sem_legenda", None)
                    analisar(falha["video_id"], falha["url"], dados_transcricao, obter_metadados_video(falha["video_id"]))

    if "resultado_youtube" in st.session_state:
        res = st.session_state.resultado_youtube
        vid_id = res["video_id"]
        url_v = res.get("url_video", "")
        transcricao = res["transcricao"]
        sintese = res["sintese"]
        perguntas = res["quiz"]["perguntas"]
        cortes = res["cortes"]["cortes"]
        roteiro = res["roteiro"]

        st.divider()
        avisos = avisos_de_degradacao(res)
        if avisos:
            st.warning("⚠️ **Modo degradado: parte do resultado abaixo NÃO foi gerada pela IA.**\n\n" + "\n".join(f"- {a}" for a in avisos))

        aba_resumo, aba_topicos, aba_txt, aba_quiz, aba_cortes, aba_roteiro, aba_edicao = st.tabs(
            ["📝 Resumo", "📌 Tópicos", "📄 Conteúdo em TXT", "🧠 Quiz", "✂️ Cortes", "🎬 Roteiro", "✨ Edição"]
        )

        with aba_resumo:
            meta = res.get("metadados", {})
            if meta.get("titulo"):
                st.markdown(f"#### {meta['titulo']}" + (f"  \n*{meta['canal']}*" if meta.get("canal") else ""))
            m1, m2, m3 = st.columns(3)
            m1.metric("Duração", transcricao["duracao_formatada"])
            m2.metric("Idioma da legenda", transcricao["idioma"])
            m3.metric("Blocos de fala", transcricao["total_blocos"])
            st.markdown(sintese.get("resumo_executivo", ""))
            if sintese.get("conclusao"):
                st.success(sintese["conclusao"])

        with aba_topicos:
            topicos = sintese.get("topicos_com_minutagem", [])
            if not topicos:
                st.info("Nenhum tópico disponível.")
            for t in topicos:
                marca = str(t.get("timestamp", ""))
                segundos = tempo_para_segundos(marca)
                rotulo = f"[{marca}](https://youtu.be/{vid_id}?t={segundos})" if segundos is not None else f"`{marca}`"
                st.markdown(f"{rotulo} **{t.get('titulo', '')}**  \n{t.get('descricao', '')}")

        with aba_txt:
            st.subheader("📄 Extração de Conteúdo em TXT")
            st.caption("Exporte todo o conhecimento do vídeo em formato de texto limpo para ler, guardar ou enviar para outras IAs.")
            
            meta = res.get("metadados", {})
            linhas_com_tempo = [f"[{b['timestamp_formatado']}] {b['texto']}" for b in transcricao['blocos']]
            linhas_sem_tempo = [b['texto'] for b in transcricao['blocos']]
            
            c_txt1, c_txt2 = st.columns(2)
            with c_txt1:
                txt_transcricao = f"TÍTULO: {meta.get('titulo', '')}\nCANAL: {meta.get('canal', '')}\nURL: {url_v}\nDURAÇÃO: {transcricao['duracao_formatada']}\n" + ("="*50) + "\n\n" + "\n\n".join(linhas_sem_tempo)
                st.download_button(
                    "📥 Baixar Transcrição Completa (.txt)",
                    data=txt_transcricao,
                    file_name=f"transcricao_{vid_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    key=f"dl_txt_transcricao_{vid_id}"
                )
            with c_txt2:
                # Monta relatório executivo completo em TXT
                resumo_txt = sintese.get("resumo_executivo", "")
                topicos_txt = "\n".join(f"- [{t.get('timestamp', '')}] {t.get('titulo', '')}: {t.get('descricao', '')}" for t in sintese.get("topicos_com_minutagem", []))
                conclusao_txt = sintese.get("conclusao", "")
                
                txt_relatorio = f"RELATÓRIO EXECUTIVO - CONTEÚDO DO VÍDEO\nTÍTULO: {meta.get('titulo', '')}\nCANAL: {meta.get('canal', '')}\nURL: {url_v}\n" + ("="*50) + f"\n\nRESUMO EXECUTIVO:\n{resumo_txt}\n\nTÓPICOS PRINCIPAIS:\n{topicos_txt}\n\nCONCLUSÃO & INSIGHTS:\n{conclusao_txt}\n\n" + ("="*50) + f"\n\nTRANSCRIÇÃO COM MINUTAGEM:\n" + "\n".join(linhas_com_tempo)
                
                st.download_button(
                    "📊 Baixar Relatório Completo + TXT (.txt)",
                    data=txt_relatorio,
                    file_name=f"relatorio_completo_{vid_id}.txt",
                    mime="text/plain",
                    use_container_width=True,
                    type="primary",
                    key=f"dl_txt_relatorio_{vid_id}"
                )
                
            st.text_area("Transcrição Completa (pronta para copiar):", value=txt_transcricao, height=300, key=f"area_txt_{vid_id}")

        with aba_quiz:
            if not perguntas:
                st.info("Quiz indisponível: ele só é gerado com IA (veja o aviso acima).")
            acertos, respondidas = 0, 0
            for n, q in enumerate(perguntas, 1):
                escolha = st.radio(f"{n}. {q['pergunta']}", q["opcoes"], index=None, key=f"quiz_{vid_id}_{n}")
                if escolha is None:
                    continue
                respondidas += 1
                if q["opcoes"].index(escolha) == q["resposta_correta"]:
                    acertos += 1
                    st.success(f"Correto! {q['explicacao']}")
                else:
                    st.error(f"Resposta certa: {q['opcoes'][q['resposta_correta']]}. {q['explicacao']}")
            if respondidas:
                st.metric("Acertos", f"{acertos}/{len(perguntas)}")

        with aba_cortes:
            st.subheader("✂️ Fatiador de Cortes para Reels (.mp4)")
            col_q, col_dica = st.columns([1, 3])
            altura = col_q.selectbox("Qualidade", ALTURAS, format_func=lambda a: f"{a}p", key=f"alt_{vid_id}")
            col_dica.caption("O trecho é baixado na maior qualidade que o YouTube oferecer até esse limite. "
                             "Acima de 360p, vídeo e áudio vêm separados e o ffmpeg junta os dois.")
            for idx, corte in enumerate(cortes, 1):
                ini = corte["inicio_segundos"]
                fim = corte["fim_segundos"]
                dur = fim - ini
                with st.container(border=True):
                    score_txt = f" — `{corte.get('selo_viral', '⚡ Forte retenção')} · {corte['score_viral']}/100`" if corte.get("score_viral") else ""
                    st.markdown(f"#### 🎬 Corte #{idx}: {corte['titulo']}{score_txt}")
                    st.write(f"Intervalo: {segundos_para_tempo(ini)} a {segundos_para_tempo(fim)} ({dur}s)")
                    if corte.get("fatores_virais"):
                        st.caption(" · ".join(f"✅ {f}" for f in corte["fatores_virais"]))
                    if corte.get("motivo_viral"):
                        st.caption(corte["motivo_viral"])
                    nome_corte = f"corte_{vid_id}_{idx}_{altura}p.mp4"
                    caminho_corte = os.path.join(PASTA_CORTES, nome_corte)
                    if st.button(f"✂️ Fatiar {dur}s em .mp4 ({altura}p)", key=f"corte_{idx}"):
                        with st.spinner("Buscando o trecho e cortando (não baixa o vídeo inteiro)..."):
                            try:
                                baixar_e_cortar_clipe(url_v, ini, fim, caminho_corte, altura_max=altura)
                            except FalhaNoCorte as erro:
                                st.error(f"Não consegui gerar este corte: {erro}")
                            else:
                                st.success("Corte pronto!")
                    if os.path.exists(caminho_corte):
                        st.video(caminho_corte)
                        with open(caminho_corte, "rb") as fc:
                            st.download_button(f"📥 Baixar Clipe #{idx} (.mp4)", data=fc.read(), file_name=nome_corte, mime="video/mp4", key=f"dl_c_{idx}")

        with aba_roteiro:
            if roteiro.get("degradado"):
                # O motivo já diz que é o modelo da TACTO e que não vem do vídeo: aqui só o que ele não diz.
                st.warning(f"⚠️ **{roteiro.get('motivo_degradado', 'o roteiro não veio da IA')}.** "
                           "Ele serve como exemplo de estrutura (gancho, dor, valor, chamada) — não copie o texto "
                           "como se fosse do vídeo.")
            titulos = roteiro.get("titulos_capa", [])
            if titulos:
                st.markdown("**Títulos de capa**\n\n" + "\n".join(f"- {t}" for t in titulos))
            for cena in roteiro.get("cenas", []):
                if not isinstance(cena, dict):
                    continue
                with st.container(border=True):
                    st.markdown(f"**{cena.get('tempo', '')} · {cena.get('bloco', '')}**")
                    st.write(f"🗣️ {cena.get('fala', '')}")
                    st.caption(f"🎥 {cena.get('direcao_visual', '')}")
            hashtags = roteiro.get("hashtags", "")
            if isinstance(hashtags, list):
                hashtags = " ".join(str(h) for h in hashtags)
            st.text_area("Legenda para o Instagram", value=str(roteiro.get("legenda_instagram", "")), height=140, key=f"legenda_{vid_id}")
            st.text_area("Hashtags", value=str(hashtags), height=60, key=f"hashtags_{vid_id}")
            st.divider()
            tela_video_pronto(res, api_key)

        with aba_edicao:
            tela_edicao(res, api_key)
