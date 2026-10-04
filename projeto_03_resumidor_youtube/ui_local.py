"""
Editor de vídeo que não passa pela análise do YouTube: um arquivo do computador ou um link de outra rede.

Mesmo compositor, mesma direção de arte e mesma busca de marca d'água das outras telas. O que muda é a
legenda: sem a transcrição do YouTube, ela vem de um .srt enviado ou da transcrição do áudio pela IA — ou
não vem, que é o padrão aqui (vídeo de outra rede quase sempre já chega legendado).
"""
import io
import time
from pathlib import Path

import streamlit as st
from PIL import Image

import editor_reels as ed
import fonte_local as fl
import fala_local
import legendas as lg
import publicacao as pub
import renderizador_generico as rg
import transcricao_audio as ta
import ui_ferramentas as uf
from core.llm import FalhaLLM, criar_cliente
from core.midia import localizar_ffmpeg
from cortador_video import ALTURAS, ALTURA_PADRAO, ROTULOS_ALTURA
from temas_video import PRESETS, TEMA_PADRAO

ARQUIVO, LINK = "💻 Arquivo do computador", "🔗 Link de outra rede"
SEM = "Não gerar (o vídeo já tem legenda na imagem, ou fica sem)"
LOCAL = "Reconhecer a fala no computador (grátis)"
SRT, IA = "De um arquivo .srt (custo zero)", "Transcrever o áudio com IA (1 chamada)"
chave = lambda nome: f"loc_{nome}"


def _cliente(api_key: str):
    if not str(api_key).strip():
        return None
    try:
        return criar_cliente(api_key)
    except FalhaLLM as erro:
        st.warning(f"Não foi possível iniciar o Gemini ({erro}). Seguindo sem IA.")
        return None


def _fonte_escolhida(ffmpeg: str) -> dict | None:
    origem = st.radio("De onde vem o vídeo", [ARQUIVO, LINK], horizontal=True, key=chave("origem"))
    if origem == ARQUIVO:
        enviado = st.file_uploader("Vídeo", type=list(fl.EXTENSOES), key=chave("arquivo"),
                                   help="Fica guardado em videos_locais/, fora do git.")
        if enviado is None:
            return None
        # Cada clique na tela roda o script de novo; sem guardar, um vídeo de 1 GB seria copiado e ter o hash
        # recalculado a cada mudança de filtro.
        identidade = (enviado.name, enviado.size)
        guardado = st.session_state.get(chave("salvo"))
        if not guardado or guardado["identidade"] != identidade:
            try:
                caminho = fl.salvar_envio(enviado.name, enviado.getvalue())
                props = ed.sondar_clipe(caminho, ffmpeg)
            except (fl.FalhaNaFonte, ed.FalhaNaEdicao) as erro:
                st.error(f"Não consegui ler o vídeo: {erro}")
                return None
            guardado = {"identidade": identidade, "fonte": {
                "tipo": "arquivo", "caminho": str(caminho), "titulo": Path(enviado.name).stem,
                "duracao": props["duracao"], "tamanho": (props["largura"], props["altura"])}}
            st.session_state[chave("salvo")] = guardado
        return guardado["fonte"]

    c1, c2 = st.columns([3, 1])
    url = c1.text_input("Link do vídeo", placeholder="https://www.dailymotion.com/video/...", key=chave("url"))
    c2.write("")
    if c2.button("🔎 Ler o link", key=chave("btn_link"), use_container_width=True):
        with st.spinner("Lendo o link (não baixa nada ainda)..."):
            try:
                st.session_state[chave("info")] = fl.informacoes_do_link(url)
            except fl.FalhaNaFonte as erro:
                st.session_state.pop(chave("info"), None)
                st.error(f"Não deu: {erro}")
    st.caption("Testado em 21/09: Dailymotion, Reddit, clipes da Twitch e vídeo público do Facebook abriram. Vimeo e "
               "Instagram pediram login, e o TikTok bloqueou os posts testados — para esses, baixe pelo app da rede "
               "e envie como arquivo.")
    info = st.session_state.get(chave("info"))
    if not info or info["url"] != url.strip():
        return None
    return {"tipo": "link", **info}


def _falas(fonte_legenda: str, arquivo_srt, clipe, props, client, ffmpeg) -> tuple:
    """(falas relativas ao começo do clipe, aviso ou None). A transcrição por IA fica guardada por clipe."""
    if fonte_legenda == LOCAL:
        return fala_local.reconhecer_clipe(clipe, ffmpeg)["falas"], None
    if fonte_legenda == SRT:
        return (lg.falas_do_srt(arquivo_srt.getvalue().decode("utf-8", errors="ignore")) if arquivo_srt else []), None
    if fonte_legenda == IA:
        guardadas = st.session_state.setdefault(chave("transcricoes"), {})
        if str(clipe) not in guardadas:
            guardadas[str(clipe)] = ta.transcrever(clipe, props["duracao"], client, ffmpeg)
        feita = guardadas[str(clipe)]
        if feita["degradado"]:
            guardadas.pop(str(clipe))                       # não guarda falha: a próxima tentativa chama de novo
        return feita["falas"], (f"Sem legenda: {feita['motivo_degradado']}." if feita["degradado"] else None)
    return [], None


def _legendas_do_trecho(falas, fonte_legenda, inicio, fim, ouvidas=None) -> tuple:
    """
    O .srt é do vídeo inteiro (tempo absoluto); a transcrição por IA já é do trecho (começa em zero).
    Nenhum dos dois passa pela revisão da IA: o .srt já é legenda pronta, e a transcrição já vem pontuada —
    revisar seria pagar uma chamada a mais para consertar o que não está quebrado.
    """
    if not falas:
        return [], None
    montadas = (lg.montar_legendas(falas, inicio, fim, ouvidas=ouvidas) if fonte_legenda == SRT
                else lg.montar_legendas(falas, 0.0, fim - inicio, ouvidas=ouvidas))
    return montadas["blocos"], montadas["sincronia"]


def _em_portugues(legendas, client, previa: bool, idioma: str = "") -> tuple:
    """
    A legenda traduzida para português, se ela não estiver em português. Na prévia não se traduz (gastaria uma
    chamada a cada clique): fica só o que a fonte consegue desenhar. `idioma` é o que o reconhecimento local
    detectou; sem ele, vale o palpite pelas palavras.
    """
    texto = " ".join(b["texto"] for b in legendas)
    if idioma == "pt" or (not idioma and pub.parece_portugues(texto)):
        return legendas, None
    if previa:
        return uf.amostra_da_legenda(legendas), None
    traduzidas, aviso = pub.traduzir_legendas(legendas, "pt", client, origem="")
    if aviso and not pub.escrita_desenhavel(" ".join(b["texto"] for b in traduzidas)):
        return [], f"{aviso}. A fala está numa escrita que a fonte do vídeo não desenha, então saiu sem legenda"
    return traduzidas, aviso


def tela_video_local(api_key: str = "") -> None:
    st.subheader("📁 Editor de vídeo: do seu computador ou de outra rede")
    st.caption("O vídeo não precisa ser do YouTube nem passar pela análise. Escolha o trecho, a direção de arte e "
               "se a marca d'água sai — o resultado é o mesmo 9:16 das outras telas.")
    try:
        ffmpeg = localizar_ffmpeg()
    except RuntimeError as erro:
        st.error(str(erro))
        return

    fonte = _fonte_escolhida(ffmpeg)
    if fonte is None:
        st.info("Envie um vídeo ou leia um link para começar.")
        return

    duracao = float(fonte["duracao"])
    col_v, col_t = st.columns([1, 1.6])
    with col_v:
        if fonte["tipo"] == "arquivo":
            st.video(fonte["caminho"])
        else:
            st.success(f"**{fonte['titulo']}** · {fonte['site']} · {duracao:.0f}s")
    with col_t:
        titulo = st.text_input("Título (vira o nome do arquivo)", fonte["titulo"][:80], key=chave("titulo"))
        c1, c2 = st.columns(2)
        limite = max(1, int(duracao))
        inicio = c1.number_input("Começa em (s)", 0, limite, 0, key=chave("ini"))
        fim = c2.number_input("Termina em (s)", 0, limite, min(limite, 60), key=chave("fim"))
        st.caption(f"Trecho de **{max(0, fim - inicio)}s** de um vídeo de {duracao:.0f}s.")
    if fim <= inicio:
        st.warning("O fim precisa vir depois do começo.")
        return

    c1, c2, c3 = st.columns([1.6, 1.4, 1])
    fontes = [SEM, LOCAL, SRT, IA] if fala_local.disponivel() else [SEM, SRT, IA]
    fonte_legenda = c1.radio("Legenda", fontes, key=chave("fonte_leg"),
                             help="Transcrever gasta uma chamada à IA por trecho (o áudio de 1 minuto são uns "
                                  "360 KB). O .srt é o do vídeo inteiro: os tempos dele são cortados no trecho.")
    estilo_leg = uf.campos_estilo_legenda(chave("lg"), fonte_legenda != SEM, c2, c3)
    traduzir = st.checkbox("Legenda em português (traduz se a fala for de outro idioma)", value=True,
                           key=chave("traduzir"), disabled=fonte_legenda == SEM,
                           help="Se a fala já for em português, nada é traduzido e nenhuma chamada é gasta. Precisa "
                                "da chave do Gemini.")
    arquivo_srt = None
    if fonte_legenda == SRT:
        arquivo_srt = st.file_uploader("Arquivo .srt", type=["srt"], key=chave("srt"))
    sincronizar = fonte_legenda == LOCAL
    if fonte_legenda in (SRT, IA) and fala_local.disponivel():
        sincronizar = st.checkbox("⏱️ Sincronizar pelo áudio (no computador, grátis)", value=fonte_legenda == IA,
                                  key=chave("sinc"),
                                  help="O texto continua o do .srt ou da IA; o tempo de cada palavra passa a ser o "
                                       "medido no áudio. Um .srt bem feito já vem sincronizado.")
    if fonte_legenda == LOCAL:
        st.caption("O reconhecimento local erra mais nomes próprios que a legenda do YouTube, mas o tempo de cada "
                   "palavra é medido no áudio. Leva cerca de metade da duração do trecho.")
    if fonte_legenda == IA and not str(api_key).strip():
        st.warning("Transcrever precisa da chave do Gemini (barra lateral).")

    with st.expander("🎨 Direção de arte, áudio e marca d'água", expanded=True):
        arte = uf.campos_direcao_de_arte(chave("arte"))
        st.divider()
        config_audio = uf.campos_audio_estudio(chave("audio"))
        produto_ml = uf.campo_produto_ml(chave("ml"), contexto=titulo)
        st.divider()
        escolha_marca = uf.campos_marca_dagua(chave("md"))


    with st.expander("⚙️ Tema, enquadramento e qualidade", expanded=False):
        a1, a2, a3 = st.columns([1.3, 1, 1])
        tema = PRESETS[a1.selectbox("Tema visual", list(PRESETS), index=list(PRESETS).index(TEMA_PADRAO),
                                    key=chave("tema"))]
        marca = a2.text_input("Marca (cabeçalho)", placeholder="ex.: @meucanal", max_chars=30, key=chave("marca"))
        arquivo_logo = a3.file_uploader("Logo (opcional)", type=["png", "jpg", "jpeg"], key=chave("logo"))
        b1, b2, b3 = st.columns(3)
        enquadramento = b1.selectbox("Enquadramento", list(ed.ENQUADRAMENTOS), format_func=ed.ENQUADRAMENTOS.get,
                                     key=chave("enq"))
        altura = ALTURA_PADRAO
        if fonte["tipo"] == "link":
            altura = b2.selectbox("Qualidade", ALTURAS, index=ALTURAS.index(ALTURA_PADRAO),
                                  format_func=lambda a: ROTULOS_ALTURA.get(a, f"Até {a}p"), key=chave("altura"))
        b3.write("")
        com_barra = b3.checkbox("Barra de progresso", value=False, key=chave("barra"))

    logo = None
    if arquivo_logo is not None:
        try:
            logo = Image.open(io.BytesIO(arquivo_logo.getvalue()))
        except OSError:
            st.warning("Não consegui abrir o logo enviado; seguindo sem ele.")

    arte = uf.proteger_legenda_da_imagem(arte, {"da_imagem": fonte_legenda == SEM})
    montagem = dict(tema=tema, titulo="", marca=marca, logo=logo, enquadramento=enquadramento,
                    com_caixa_legenda=estilo_leg["com_caixa"], com_barra=com_barra, arte=arte,
                    estilo_legenda=uf.estilo_da_legenda(estilo_leg["estilo"], arte),
                    produto_ml=produto_ml)
    b_previa, b_montar = st.columns([1, 1.4])
    previa = b_previa.button("🔍 Prévia de um quadro", key=chave("btn_previa"), use_container_width=True)
    montar = b_montar.button("🎬 Montar o vídeo", type="primary", key=chave("btn"), use_container_width=True)
    if not (previa or montar):
        uf.mostrar_previa(chave("md"))
        _resultado()
        return

    # a IA só entra para transcrever ou traduzir; sem nenhum dos dois, nem se cria o cliente
    client = _cliente(api_key) if fonte_legenda == IA or (fonte_legenda in (SRT, LOCAL) and traduzir) else None
    barra = st.progress(0.0, text="Preparando o trecho...")
    legendas, aviso_legenda = [], None
    try:
        clipe = fl.clipe_da_fonte(fonte, float(inicio), float(fim), ffmpeg, altura)
        props = ed.sondar_clipe(clipe, ffmpeg)
        barra.progress(0.15, text="Lendo a legenda..." if fonte_legenda != SEM else "Procurando marca d'água...")
        falas, aviso_legenda = _falas(fonte_legenda, arquivo_srt, clipe, props, client, ffmpeg)
        ouvidas, idioma = None, ""
        if sincronizar and falas and not previa:
            barra.progress(0.18, text="Ouvindo o trecho (~metade da duração)...")
            reconhecido = fala_local.reconhecer_clipe(clipe, ffmpeg)
            ouvidas, idioma = reconhecido["palavras"], reconhecido["idioma"]
        legendas, sincronia = _legendas_do_trecho(falas, fonte_legenda, float(inicio), float(fim), ouvidas)
        aviso_sincronia = uf.aviso_de_sincronia(sincronia) if fonte_legenda != LOCAL else None
        if legendas and traduzir and fonte_legenda != SEM:
            legendas, aviso_traducao = _em_portugues(legendas, client, previa, idioma)
            aviso_legenda = aviso_legenda or aviso_traducao
        if previa:
            barra.progress(0.5, text="Desenhando um quadro...")
            uf.gerar_previa(chave("md"), clipe, ffmpeg, props, escolha_marca,
                            uf.segundo_da_previa(legendas, props["duracao"]), legendas=legendas, **montagem)
        else:
            barra.progress(0.25, text="Procurando marca d'água...")
            regiao, aviso_marca = uf.resolver_marca(escolha_marca, clipe, ffmpeg, props, chave("md"))
            nome = f"{rg.nome_de_arquivo(titulo or 'video')[:-4]}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            dados = ed.montar_reels(clipe, **montagem, legendas=legendas, marca_dagua=regiao,
                                    config_audio=config_audio, nome_arquivo=nome,
                                    pasta_saida=ed.PASTA_SAIDA, ffmpeg=ffmpeg,
                                    progresso=lambda p, msg: barra.progress(min(1.0, 0.3 + 0.7 * p), text=msg))

            st.session_state[chave("video")] = {**dados, "nome": nome, "aviso_marca": aviso_marca,
                                                "aviso_legenda": aviso_legenda, "aviso_sincronia": aviso_sincronia}
    except (fl.FalhaNaFonte, ed.FalhaNaEdicao, rg.FalhaRenderizacao, RuntimeError) as erro:
        st.error(f"Não consegui: {erro}")
    else:
        if aviso_legenda:
            st.warning(aviso_legenda)
        elif fonte_legenda == SRT and arquivo_srt is None:
            st.info("Nenhum .srt enviado: saiu sem legenda.")
        elif fonte_legenda != SEM and not legendas:
            st.info("Nenhuma fala caiu dentro do trecho escolhido: saiu sem legenda.")
    finally:
        barra.empty()
    uf.mostrar_previa(chave("md"))
    _resultado()


def _resultado() -> None:
    dados = st.session_state.get(chave("video"))
    if not dados:
        return
    st.divider()
    with open(dados["caminho"], "rb") as arquivo:
        conteudo = arquivo.read()
    col_v, col_i = st.columns([1, 1.6])
    col_v.video(conteudo)
    with col_i:
        st.success(f"{dados['duracao_segundos']:.0f} s em 1080x1920 (9:16), H.264 + AAC.")
        for aviso in (dados.get("aviso_legenda"), dados.get("aviso_marca"), dados.get("aviso_sincronia")):
            if aviso:
                st.caption(f"ℹ️ {aviso}")
        b1, b2 = st.columns(2)
        b1.download_button("📥 Vídeo (.mp4)", conteudo, file_name=dados["nome"], mime="video/mp4",
                           use_container_width=True, key=f"dl_loc_{dados['nome']}")
        if dados.get("srt"):
            with open(dados["srt"], "rb") as arquivo:
                b2.download_button("📄 Legenda (.srt)", arquivo.read(), file_name=dados["nome"].replace(".mp4", ".srt"),
                                   mime="text/plain", use_container_width=True, key=f"dl_loc_srt_{dados['nome']}")
