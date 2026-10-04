"""
Aba "Edição": vários trechos do vídeo montados numa peça só.

Separada do fatiador de propósito. Lá é um corte contínuo, e o vídeo pronto sai de um clique. Aqui a IA
propõe uma sequência, o usuário lê a fala de cada trecho, mexe nos tempos e só então manda montar — porque
a decisão de qual pedaço entra é a parte que decide se a peça funciona, e ela é do usuário.
"""
import io
import time

import streamlit as st
from PIL import Image

import edicao
import editor_reels as ed
import efeitos as ef
import legendas as lg
import renderizador_generico as rg
import ui_ferramentas as uf
from core.llm import FalhaLLM, criar_cliente
from core.midia import localizar_ffmpeg
from cortador_video import ALTURAS, ALTURA_PADRAO, ROTULOS_ALTURA, FalhaNoCorte, PASTA_CORTES, baixar_e_cortar_clipe
from temas_video import PRESETS, TEMA_PADRAO
from transcricao_youtube import segundos_para_tempo
from ui_video_pronto import nome_do_arquivo

DURACOES = [30, 45, 60, 90]


def _cliente(api_key: str):
    if not str(api_key).strip():
        return None
    try:
        return criar_cliente(api_key)
    except FalhaLLM as erro:
        st.warning(f"Não foi possível iniciar o Gemini ({erro}). Seguindo sem IA.")
        return None


def _clipe_do_trecho(url_video: str, video_id: str, inicio: int, fim: int, altura: int):
    """Um arquivo por (trecho, qualidade): remontar a edição depois de mexer no tema não baixa nada de novo."""
    PASTA_CORTES.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_CORTES / f"trecho_{video_id}_{inicio}_{fim}_{altura}p.mp4"
    if not caminho.exists():
        baixar_e_cortar_clipe(url_video, inicio, fim, caminho, altura_max=altura)
    return caminho


def _mostrar(dados: dict, titulo: str) -> None:
    with open(dados["caminho"], "rb") as arquivo:
        conteudo = arquivo.read()
    col_v, col_i = st.columns([1, 1.6])
    with col_v:
        st.video(conteudo)
    with col_i:
        st.success(f"Edição pronta: {dados['duracao_segundos']:.0f} s em {len(dados['partes'])} trechos"
                   + (f", com transição \"{ef.TRANSICOES[dados['transicao']]}\"." if dados.get("transicao", "corte")
                      != "corte" else "."))
        st.caption(" · ".join(f"{n} {d:.0f}s" for n, d in zip(dados["nomes_das_partes"], dados["partes"])))
        if dados.get("aviso_marca"):
            st.caption(f"🧽 {dados['aviso_marca']}")
        if dados.get("aviso_legenda"):
            st.warning(f"⚠️ {dados['aviso_legenda']}")
        if dados.get("aviso_sincronia"):
            st.caption(dados["aviso_sincronia"])
        b1, b2 = st.columns(2)
        b1.download_button("📥 Vídeo (.mp4)", conteudo, file_name=dados["nome"], mime="video/mp4",
                           use_container_width=True, key=f"dl_ed_{dados['nome']}")
        if dados.get("srt"):
            with open(dados["srt"], "rb") as arquivo:
                b2.download_button("📄 Legenda (.srt)", arquivo.read(),
                                   file_name=dados["nome"].replace(".mp4", ".srt"), mime="text/plain",
                                   use_container_width=True, key=f"dl_ed_srt_{dados['nome']}")
        st.text_input("Título da peça", titulo, key=f"ed_tit_saida_{dados['nome']}")


def tela_edicao(res: dict, api_key: str = "") -> None:
    transcricao, video_id = res["transcricao"], res["video_id"]
    url_video, falas = res.get("url_video", ""), transcricao.get("falas", [])
    chave = lambda nome: f"ed_{nome}_{video_id}"

    st.subheader("🎞️ Edição: vários trechos numa peça só")
    st.caption("O fatiador pega um pedaço contínuo. Aqui a IA lê o vídeo inteiro e escolhe trechos de lugares "
               "diferentes que, juntos, contam uma ideia fechada — e o caminho entre eles fica de fora.")

    c1, c2 = st.columns([1, 2])
    alvo = c1.select_slider("Duração alvo", DURACOES, value=60, key=chave("alvo"))
    angulo = c2.text_input("Ângulo (opcional)", placeholder="ex.: só a parte prática, sem a introdução teórica",
                           key=chave("angulo"), help="O que a peça deve defender. Em branco, a IA escolhe o "
                                                     "que considera mais forte no vídeo.")

    if st.button("🧠 Planejar a edição", type="primary", key=chave("btn_plano")):
        with st.spinner("Lendo o vídeo inteiro e escolhendo os trechos..."):
            st.session_state[chave("plano")] = edicao.planejar_edicao(
                transcricao, _cliente(api_key), duracao_alvo=alvo, angulo=angulo)
            st.session_state.pop(chave("video"), None)

    guardado = st.session_state.get(chave("plano"))
    if not guardado:
        st.info("Clique em **Planejar a edição**. Você revisa os trechos escolhidos, e só então monta o vídeo.")
        return

    plano = guardado["plano"]
    if guardado["degradado"]:
        st.warning(f"⚠️ **Sem leitura de conteúdo:** {guardado['motivo_degradado']}. Os tempos abaixo são um "
                   "ponto de partida mecânico — vale a pena ajustar cada um antes de montar.")
    else:
        st.markdown(f"**{plano['titulo']}**")
        st.caption(f"Por que funciona: {plano['por_que_funciona']}")

    st.markdown("#### Trechos escolhidos")
    trechos, duracao_video = [], transcricao.get("duracao_segundos", 10 ** 6)
    for i, trecho in enumerate(plano["trechos"], 1):
        with st.container(border=True):
            col_t, col_f = st.columns([1, 2.4])
            manter = col_t.checkbox(f"Trecho {i}", value=True, key=chave(f"manter_{i}"))
            inicio = col_t.number_input("Começa em (s)", 0, int(duracao_video), trecho["inicio_segundos"],
                                        key=chave(f"ini_{i}"))
            fim = col_t.number_input("Termina em (s)", 0, int(duracao_video), trecho["fim_segundos"],
                                     key=chave(f"fim_{i}"))
            with col_f:
                st.caption(f"{trecho.get('papel', '')} · {segundos_para_tempo(inicio)}–{segundos_para_tempo(fim)} "
                           f"({max(0, fim - inicio)}s)")
                st.write(lg.fala_do_trecho(falas, inicio, fim) or "_(sem transcrição neste intervalo)_")
            if manter and fim > inicio:
                trechos.append({**trecho, "inicio_segundos": int(inicio), "fim_segundos": int(fim)})

    total = edicao.duracao_total(trechos)
    problemas = []
    if len(trechos) < 1:
        problemas.append("mantenha ao menos um trecho")
    if any(a["fim_segundos"] > b["inicio_segundos"] for a, b in zip(trechos, trechos[1:])):
        problemas.append("há trechos se sobrepondo: ajuste os tempos")
    if problemas:
        st.warning("Antes de montar:\n\n" + "\n".join(f"- {p}" for p in problemas))

    modo_auto = st.toggle("⚡ Modo Automático 1-Clique (Preset Reels/TikTok Profissional)", value=True, key=chave("chk_auto_preset"),
                          help="Aplica automaticamente: Enquadramento Vertical 9:16, Legenda Dinâmica estilizada, Tema Obsidian e Barra de Progresso, sem você precisar configurar nada manualmente.")


    idioma_fala = uf.idioma_da_fala(transcricao)
    legenda = uf.campos_legenda(chave("lg"), disponivel=bool(falas), idioma_fala=idioma_fala,
                                nome_idioma=transcricao.get("idioma", ""),
                                amostra=lg.fala_do_trecho(falas, 0, 10 ** 6, limite=400),
                                tem_chave=bool(str(api_key).strip()))
    sincronizar = uf.campo_sincronia(chave("lg"), legenda, ja_medido=bool(transcricao.get("palavras_ouvidas")))

    with st.expander("🎨 Direção de arte, áudio e marca d'água", expanded=True):
        arte = uf.campos_direcao_de_arte(chave("arte"), com_transicao=True)
        st.divider()
        config_audio = uf.campos_audio_estudio(chave("audio"))
        contexto_ed = f"{res.get('metadados', {}).get('titulo', '')} {plano.get('titulo', '')}"
        produto_ml = uf.campo_produto_ml(chave("ml"), contexto=contexto_ed)
        st.divider()
        escolha_marca = uf.campos_marca_dagua(chave("md"))


    with st.expander("⚙️ Tema e qualidade", expanded=False):
        a1, a2, a3, a4 = st.columns([1.3, 1, 1, 1.2])
        tema = PRESETS[a1.selectbox("Tema visual", list(PRESETS), index=list(PRESETS).index(TEMA_PADRAO),
                                    key=chave("tema"))]
        marca = a2.text_input("Marca (cabeçalho)", placeholder="ex.: @meucanal", max_chars=30, key=chave("marca"))
        arquivo_logo = a3.file_uploader("Logo (opcional)", type=["png", "jpg", "jpeg"], key=chave("logo"))
        altura = a4.selectbox("Qualidade", ALTURAS, index=ALTURAS.index(ALTURA_PADRAO),
                              format_func=lambda a: ROTULOS_ALTURA.get(a, f"Até {a}p"), key=chave("altura"))
        b1, b2 = st.columns(2)
        enquadramento = b1.selectbox("Enquadramento", list(ed.ENQUADRAMENTOS), format_func=ed.ENQUADRAMENTOS.get,
                                     key=chave("enq"))
        b2.write("")
        com_barra = b2.checkbox("Barra de progresso", value=False, key=chave("barra"))

    logo = None
    if arquivo_logo is not None:
        try:
            logo = Image.open(io.BytesIO(arquivo_logo.getvalue()))
        except OSError:
            st.warning("Não consegui abrir o logo enviado; seguindo sem ele.")

    chamadas = (len(trechos) if legenda["revisar"] else 1 if legenda["traduzir"] else 0) if api_key.strip() else 0
    com_transicao = arte.transicao != "corte" and len(trechos) > 1
    st.caption(f"A peça vai ter **{total}s** em {len(trechos)} trecho(s). Montar baixa um pedaço do YouTube por "
               f"trecho e leva algo como {total * 1.4 + 20 + (25 if com_transicao else 0):.0f}s"
               + (f"; a legenda custa {chamadas} chamada(s) à IA." if chamadas else "."))

    arte = uf.proteger_legenda_da_imagem(arte, legenda)
    montagem = dict(tema=tema, marca=marca, logo=logo, enquadramento=enquadramento,
                    com_caixa_legenda=legenda["com_caixa"], com_barra=com_barra, arte=arte,
                    estilo_legenda=uf.estilo_da_legenda(legenda["estilo"], arte),
                    produto_ml=produto_ml)

    contexto_legenda = f"Vídeo: {plano.get('titulo', '')}. Termos/Técnicas: {legenda.get('prompt_guia', '')}".strip()
    blocos_iniciais = []
    if legenda["ligada"] and trechos:
        primeiro = trechos[0]
        blocos_iniciais = lg.montar_legendas(falas, primeiro["inicio_segundos"], primeiro["fim_segundos"],
                                             contexto=contexto_legenda)["blocos"]
    legendas_editadas = uf.editor_de_legendas(chave("editor"), blocos_iniciais) if legenda["ligada"] and trechos else []

    b_previa, b_montar = st.columns([1, 1.4])
    if trechos and b_previa.button("🔍 Prévia do primeiro trecho", key=chave("btn_previa"), use_container_width=True,
                                   help="Baixa o primeiro trecho (a montagem reaproveita) e desenha um quadro com "
                                        "cor, zoom, legenda e marca apagada."):
        with st.spinner("Buscando o trecho e desenhando um quadro..."):
            try:
                primeiro = trechos[0]
                clipe = _clipe_do_trecho(url_video, video_id, primeiro["inicio_segundos"], primeiro["fim_segundos"], altura)
                ffmpeg = localizar_ffmpeg()
                props = ed.sondar_clipe(clipe, ffmpeg)
                amostra = []
                if legenda["ligada"]:
                    blocos_base = legendas_editadas or lg.montar_legendas(falas, primeiro["inicio_segundos"], primeiro["fim_segundos"],
                                                                          contexto=contexto_legenda)["blocos"]
                    amostra = uf.amostra_da_legenda(blocos_base)
                uf.gerar_previa(chave("md"), clipe, ffmpeg, props, escolha_marca,
                                uf.segundo_da_previa(amostra, props["duracao"]), legendas=amostra, **montagem)
            except (FalhaNoCorte, ed.FalhaNaEdicao, RuntimeError) as erro:
                st.error(f"Não consegui gerar a prévia: {erro}")
    uf.mostrar_previa(chave("md"))

    if b_montar.button("🎬 Montar a edição", disabled=bool(problemas), key=chave("btn_montar"),
                       use_container_width=True):
        barra = st.progress(0.0, text="Buscando os trechos no YouTube...")
        client = _cliente(api_key)
        try:
            prontos, sincronias = [], []
            ffmpeg = localizar_ffmpeg()
            for i, trecho in enumerate(trechos, 1):
                barra.progress(0.05 + 0.30 * (i - 1) / len(trechos),
                               text=f"Baixando o trecho {i} de {len(trechos)}...")
                clipe = _clipe_do_trecho(url_video, video_id, trecho["inicio_segundos"], trecho["fim_segundos"], altura)
                blocos = []
                if legenda["ligada"]:
                    if legenda.get("whisper_local"):
                        barra.progress(0.05 + 0.30 * (i - 1) / len(trechos),
                                       text=f"Ouvindo o trecho {i} na CPU com Whisper (R$ 0)...")
                        prompt_w = uf.prompt_inicial_whisper(legenda.get("prompt_guia", ""))
                        reconhecido = uf.falas_do_clipe_whisper(clipe, ffmpeg, idioma_fala, prompt_w)
                        dur_clipe = ed.sondar_clipe(clipe, ffmpeg)["duracao"]
                        montadas = lg.montar_legendas(reconhecido["falas"], 0.0, dur_clipe, ouvidas=reconhecido["palavras"],
                                                      contexto=contexto_legenda)
                        blocos = montadas["blocos"]
                    else:
                        ouvidas = None
                        if sincronizar:
                            barra.progress(0.05 + 0.30 * (i - 1) / len(trechos),
                                           text=f"Ouvindo o trecho {i} para sincronizar a legenda...")
                            ouvidas = uf.ouvidas_do_clipe(transcricao, clipe, ffmpeg, trecho["inicio_segundos"],
                                                          trecho["fim_segundos"], idioma_fala,
                                                          prompt_inicial=legenda.get("prompt_guia", ""))
                        montadas = lg.montar_legendas(falas, trecho["inicio_segundos"], trecho["fim_segundos"],
                                                      client if legenda["revisar"] else None, ouvidas=ouvidas,
                                                      contexto=contexto_legenda)
                        blocos = montadas["blocos"]
                        if montadas["sincronia"] is not None:
                            sincronias.append(montadas["sincronia"])

                    if i == 1 and legendas_editadas:
                        for idx_e, b_edit in enumerate(legendas_editadas):
                            if idx_e < len(blocos):
                                blocos[idx_e]["texto"] = b_edit["texto"]

                prontos.append({"clipe": clipe, "legendas": blocos, "titulo": "", "etiqueta": ""})

            aviso_legenda = None
            if legenda["traduzir"]:
                barra.progress(0.34, text="Traduzindo a legenda para português...")
                blocos, aviso_legenda = uf.traduzir_varios([p["legendas"] for p in prontos], "pt", client, idioma_fala)
                for pronto, traduzidos in zip(prontos, blocos):
                    pronto["legendas"] = traduzidos
            barra.progress(0.36, text="Procurando marca d'água...")
            regiao, aviso_marca = uf.resolver_marca_de_varios(escolha_marca, [p["clipe"] for p in prontos], ffmpeg,
                                                              chave("md"))
            nome = nome_do_arquivo(plano["titulo"], 0, "pt", time.strftime("%Y%m%d_%H%M%S")).replace("_corte0", "_edicao")
            dados = ed.montar_edicao(prontos, **montagem, marca_dagua=regiao, config_audio=config_audio,
                                     nome_arquivo=nome, pasta_saida=ed.PASTA_SAIDA, ffmpeg=ffmpeg,
                                     progresso=lambda p, msg: barra.progress(min(1.0, 0.4 + 0.6 * p), text=msg))

        except (FalhaNoCorte, ed.FalhaNaEdicao, rg.FalhaRenderizacao, RuntimeError) as erro:
            barra.empty()
            st.error(f"Não consegui montar a edição: {erro}")
        else:
            barra.empty()
            st.session_state[chave("video")] = {
                **dados, "nome": nome, "aviso_marca": aviso_marca, "aviso_legenda": aviso_legenda,
                "aviso_sincronia": uf.aviso_de_sincronia(min(sincronias)) if sincronias else None}

    if pronto := st.session_state.get(chave("video")):
        st.divider()
        _mostrar(pronto, plano["titulo"])
