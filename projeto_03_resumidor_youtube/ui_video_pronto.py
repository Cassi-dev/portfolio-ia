"""
Bloco "Vídeo pronto para postar" da aba Roteiro: o corte sugerido vira um .mp4 de tela cheia, com legenda
queimada, cartão final convidando a seguir a conta, e o texto da publicação (título, descrição, hashtags).

Pode sair em mais de um idioma: cada idioma escolhido gera um vídeo próprio, com os textos traduzidos, mais
um .srt. Por que um vídeo por idioma, e não uma faixa de legenda que o espectador troca: Instagram e TikTok
descartam faixas de legenda embutidas — lá, legenda tem que estar queimada na imagem. YouTube e Facebook
aceitam o .srt e escolhem sozinhos pelo idioma de quem assiste.
"""
import io
import time

import streamlit as st
from PIL import Image

import editor_reels as ed
import legendas as lg
import renderizador_generico as rg
import ui_ferramentas as uf
from core.llm import FalhaLLM, criar_cliente
from core.midia import localizar_ffmpeg
from cortador_video import ALTURAS, ALTURA_PADRAO, ROTULOS_ALTURA, FalhaNoCorte, PASTA_CORTES, baixar_e_cortar_clipe
from esquemas_reels import MAX_BOTAO, MAX_TAG, MAX_TITULO, corrigir_cena, problemas_da_cena
from publicacao import (IDIOMA_ORIGINAL, IDIOMAS, escrita_desenhavel, gerar_pacote, idioma_base, traduzir,
                        voz_do_idioma)
from temas_video import PRESETS, TEMA_PADRAO
from transcricao_youtube import segundos_para_tempo

CAMPOS_DO_PACOTE = (("tit_post", "titulo"), ("chamada", "chamada_final"), ("desc", "descricao"),
                    ("tags", "hashtags"), ("botao", "botao"))
SEM_VOZ = "Sem voz (cartões mudos)"
VOZES = [f"{nome} ({id_})" for id_, nome in rg.VOZES.items()] + [SEM_VOZ]
PASTA_REELS = ed.PASTA_SAIDA


def _cliente(api_key: str):
    if not str(api_key).strip():
        return None
    try:
        return criar_cliente(api_key)
    except FalhaLLM as erro:
        st.warning(f"Não foi possível iniciar o Gemini ({erro}). Seguindo sem IA.")
        return None


def _logo_enviado(arquivo):
    if arquivo is None:
        return None
    try:
        return Image.open(io.BytesIO(arquivo.getvalue()))
    except OSError:
        st.warning("Não consegui abrir o logo enviado; seguindo sem ele.")
        return None


def _contexto_do_video(res: dict, corte: dict) -> str:
    """O que a IA lê para escrever a publicação: o resumo do vídeo e a fala do trecho escolhido."""
    meta, sintese = res.get("metadados", {}), res.get("sintese", {})
    falas = res["transcricao"].get("falas", [])
    trecho = " ".join(f["texto"] for f in falas
                      if corte["inicio_segundos"] <= f.get("start", 0) < corte["fim_segundos"])
    partes = [meta.get("titulo", ""), sintese.get("resumo_executivo", ""), sintese.get("conclusao", ""),
              f"Trecho escolhido para o vídeo curto: {trecho}" if trecho else ""]
    return "\n\n".join(p for p in partes if p)


def arquivo_do_corte(video_id: str, indice: int, inicio: int, fim: int, altura: int):
    """
    O nome leva os tempos: com o ajuste fino, o mesmo corte pode ter vários intervalos. Antes o nome era só
    o número do corte, e mexer no fim de 40 para 45 s reaproveitava o arquivo de 40 — com a legenda já
    montada para 45.
    """
    return PASTA_CORTES / f"corte_{video_id}_{indice}_{int(inicio)}_{int(fim)}_{altura}p.mp4"


def _clipe_do_corte(url_video: str, video_id: str, indice: int, corte: dict, altura: int):
    """Corta só quando ainda não existe um arquivo daquele trecho naquela qualidade."""
    PASTA_CORTES.mkdir(parents=True, exist_ok=True)
    caminho = arquivo_do_corte(video_id, indice, corte["inicio_segundos"], corte["fim_segundos"], altura)
    if not caminho.exists():
        baixar_e_cortar_clipe(url_video, corte["inicio_segundos"], corte["fim_segundos"], caminho, altura_max=altura)
    return caminho


def _com_correcao(cena: dict) -> dict:
    """Aplica as correções do renderizador numa cópia, para validar sem mexer no que está na tela."""
    copia = dict(cena)
    corrigir_cena(copia)
    return copia


def _cartao_final(chamada: str, botao: str) -> dict:
    """Sem texto de botão vira cartão de título: um botão repetindo a mesma frase não acrescenta nada."""
    return _com_correcao({"layout": "cta" if botao.strip() else "titulo", "tag": "", "titulo": chamada,
                          "fala": chamada, "itens": [], "rotulos": [], "destaque_valor": "",
                          "destaque_rotulo": "", "botao": botao})


def nome_do_arquivo(titulo: str, indice: int, codigo: str, carimbo: str, com_idioma: bool = False) -> str:
    """
    O nome que vai para a pasta de downloads. Antes saía "reels_aircAruvnKk_1_pt_20260920_143022.mp4" — o
    identificador do YouTube não diz nada a quem vai arquivar o arquivo depois. Agora sai do título da
    postagem, que sem chave de API é o próprio título do vídeo analisado.

    O número do corte separa os três cortes do mesmo vídeo, e o carimbo de tempo evita sobrescrever uma
    montagem anterior quando só os textos mudaram.
    """
    base = rg.nome_de_arquivo(titulo)[:-4]                       # nome_de_arquivo já devolve com ".mp4"
    idioma = f"_{codigo}" if com_idioma else ""
    return f"{base}_corte{indice}{idioma}_{carimbo}.mp4"


def _traduzir_tudo(textos: dict, legendas: list, codigo: str, client, idioma_fala: str = IDIOMA_ORIGINAL,
                   legenda_acompanha: bool = True) -> tuple:
    """
    Traduz textos de tela e legendas numa chamada só, e devolve (textos, legendas, aviso ou None).

    Os dois têm origens diferentes: os textos de tela são escritos em português; a legenda está no idioma da
    fala. Por isso cada um só entra no lote se estiver num idioma diferente do vídeo sendo feito — num vídeo
    falado em japonês, a versão em português traduz só a legenda. `legenda_acompanha=False` é a opção "no
    idioma da fala": a legenda nunca é traduzida.
    """
    chaves = list(textos) if codigo != IDIOMA_ORIGINAL else []
    traduz_legenda = legenda_acompanha and idioma_base(idioma_fala) != codigo
    lote = [textos[c] for c in chaves] + ([l["texto"] for l in legendas] if traduz_legenda else [])
    if not lote:
        return dict(textos), list(legendas), None
    resultado = traduzir(lote, codigo, client, origem=None)
    traduzidos = resultado["textos"]
    novos_textos = {**textos, **dict(zip(chaves, traduzidos[:len(chaves)]))}
    novas = legendas
    if traduz_legenda:
        novas = [{**l, "texto": t} for l, t in zip(legendas, traduzidos[len(chaves):])]
        if resultado["degradado"] and not escrita_desenhavel(" ".join(l["texto"] for l in novas)):
            # Sem tradução, a legenda em japonês sairia como uma fileira de quadradinhos.
            return novos_textos, [], (f"{resultado['motivo_degradado']}. A fala está numa escrita que a fonte do "
                                      "vídeo não desenha, então o vídeo saiu sem legenda")
    return novos_textos, novas, resultado["motivo_degradado"]


def _mostrar(dados: dict, codigo: str) -> None:
    with open(dados["caminho"], "rb") as arquivo:
        conteudo = arquivo.read()
    if dados.get("aviso"):
        st.warning(f"⚠️ {dados['aviso']}")
    col_v, col_i = st.columns([1, 1.6])
    with col_v:
        st.video(conteudo)
    with col_i:
        st.success(f"{dados['duracao_segundos']:.0f} s em 1080x1920 (9:16), tela cheia, H.264 + AAC.")
        st.caption(" · ".join(f"{n} {d:.0f}s" for n, d in zip(dados["nomes_das_partes"], dados["partes"])))
        if dados.get("aviso_marca"):
            st.caption(f"🧽 {dados['aviso_marca']}")
        if dados.get("aviso_sincronia"):
            st.caption(dados["aviso_sincronia"])
        b1, b2 = st.columns(2)
        b1.download_button("📥 Vídeo (.mp4)", conteudo, file_name=dados["nome"], mime="video/mp4",
                           use_container_width=True, key=f"dl_mp4_{codigo}_{dados['nome']}")
        if dados.get("srt"):
            with open(dados["srt"], "rb") as arquivo:
                b2.download_button("📄 Legenda (.srt)", arquivo.read(), file_name=dados["nome"].replace(".mp4", ".srt"),
                                   mime="text/plain", use_container_width=True, key=f"dl_srt_{codigo}_{dados['nome']}")
        st.text_input("Título da postagem", dados["titulo_post"], key=f"post_tit_{codigo}_{dados['nome']}")
        st.text_area("Descrição", dados["descricao"], height=140, key=f"post_desc_{codigo}_{dados['nome']}")
        st.text_area("Hashtags", dados["hashtags"], height=68, key=f"post_tags_{codigo}_{dados['nome']}")


def tela_video_pronto(res: dict, api_key: str = "") -> None:
    cortes, roteiro = res["cortes"]["cortes"], res["roteiro"]
    video_id, url_video = res["video_id"], res.get("url_video", "")
    falas = res["transcricao"].get("falas", [])
    chave = lambda nome: f"vp_{nome}_{video_id}"

    st.markdown("### 🎁 Vídeo pronto para postar")
    st.caption("O corte vira uma peça fechada, em tela cheia (1080x1920): legenda queimada, marca e um cartão "
               "final convidando a seguir a conta. Sai com o título e a descrição da publicação — e, se você "
               "escolher mais de um idioma, um vídeo para cada.")
    if not cortes:
        st.info("Nenhum corte sugerido para montar. Gere a análise novamente.")
        return

    col_a, col_b = st.columns([2, 1])
    indice = col_a.selectbox(
        "Qual corte vira o vídeo?", range(len(cortes)),
        format_func=lambda i: (
            f"#{i + 1} [🔥 {cortes[i].get('score_viral', 82)}/100] · {cortes[i]['titulo'][:54]} "
            f"({segundos_para_tempo(cortes[i]['inicio_segundos'])}–{segundos_para_tempo(cortes[i]['fim_segundos'])})"
        ),
        key=chave("corte"))
    enquadramento = col_b.selectbox("Enquadramento", list(ed.ENQUADRAMENTOS), format_func=ed.ENQUADRAMENTOS.get,
                                    key=chave("enq"),
                                    help="Tela cheia é o padrão do celular: o vídeo ocupa tudo, sem faixa nenhuma. "
                                         "Aula, slide ou tela compartilhada pede o vídeo inteiro, senão o corte "
                                         "das laterais come o conteúdo.")
    # Os tempos vêm da IA encaixados em fronteiras de frase, mas quem assiste é que sabe se faltaram dois
    # segundos no fim. Mesmo ajuste fino que existe na aba de Edição.
    limite = int(res["transcricao"].get("duracao_segundos", 10 ** 6))
    col_i, col_f, col_d = st.columns([1, 1, 2])
    inicio = col_i.number_input("Começa em (s)", 0, limite, int(cortes[indice]["inicio_segundos"]),
                                key=chave(f"ini_{indice}"))
    fim = col_f.number_input("Termina em (s)", 0, limite, int(cortes[indice]["fim_segundos"]),
                             key=chave(f"fim_{indice}"))
    corte = {**cortes[indice], "inicio_segundos": int(inicio), "fim_segundos": int(fim)}
    col_d.write("")
    selo_viral = f" · {corte['selo_viral']} ({corte['score_viral']}/100)" if corte.get("score_viral") else ""
    col_d.caption(f"{segundos_para_tempo(inicio)}–{segundos_para_tempo(fim)} · **{max(0, fim - inicio)}s**{selo_viral}  \n"
                  + (lg.fala_do_trecho(falas, inicio, fim) if falas else corte.get("motivo_viral", "")))
    if fim <= inicio:
        st.warning("O fim precisa vir depois do começo.")
        return

    idioma_fala = uf.idioma_da_fala(res["transcricao"])
    legenda = uf.campos_legenda(chave("lg"), disponivel=bool(falas), idioma_fala=idioma_fala,
                                nome_idioma=res["transcricao"].get("idioma", ""),
                                amostra=lg.fala_do_trecho(falas, 0, 10 ** 6, limite=400),
                                tem_chave=bool(str(api_key).strip()))

    sincronizar = uf.campo_sincronia(chave("lg"), legenda, ja_medido=bool(res["transcricao"].get("palavras_ouvidas")))

    with st.expander("🎨 Direção de arte, áudio e marca d'água", expanded=True):
        arte = uf.campos_direcao_de_arte(chave("arte"))
        st.divider()
        config_audio = uf.campos_audio_estudio(chave("audio"))
        produto_ml = uf.campo_produto_ml(chave("ml"), contexto=f"{corte.get('titulo', '')} {_contexto_do_video(res, corte)}")
        st.divider()
        escolha_marca = uf.campos_marca_dagua(chave("md"))


    with st.expander("⚙️ Tema, voz e qualidade", expanded=False):
        c1, c2, c3, c4 = st.columns([1.3, 1, 1, 1.2])
        tema = PRESETS[c1.selectbox("Tema visual", list(PRESETS), index=list(PRESETS).index(TEMA_PADRAO), key=chave("tema"))]
        marca = c2.text_input("Marca (cabeçalho)", placeholder="ex.: @meucanal", max_chars=30, key=chave("marca"))
        logo = _logo_enviado(c3.file_uploader("Logo (opcional)", type=["png", "jpg", "jpeg"], key=chave("logo")))
        voz_escolhida = c4.selectbox("Voz dos cartões", VOZES, key=chave("voz"))
        d1, d2 = st.columns([1.4, 2])
        altura = d1.selectbox("Qualidade do corte", ALTURAS, index=ALTURAS.index(ALTURA_PADRAO),
                              format_func=lambda a: ROTULOS_ALTURA.get(a, f"Até {a}p"), key=chave("altura"),
                              help="Na tela cheia, um vídeo 16:9 perde 68% da largura e o miolo é ampliado 1,78x. "
                                   "Quanto maior a resolução de origem, menos ampliação — por isso vale pedir alto.")
        d2.write("")
        com_barra = d2.checkbox("Barra de progresso no rodapé", value=False, key=chave("barra"))

    # ---- publicação: título, descrição e o convite para seguir a conta ----
    st.markdown("#### 📣 Publicação e chamada final")
    guardado = st.session_state.get(chave("pacote"))
    col_conta, col_btn = st.columns([2, 1])
    conta = col_conta.text_input("Conta a mencionar no fim do vídeo", placeholder="ex.: @meucanal", max_chars=40,
                                 key=chave("conta"))
    col_btn.write("")
    if col_btn.button("✨ Escrever com IA", use_container_width=True, key=chave("btn_pacote"),
                      help="Usa o resumo do vídeo e a fala do trecho escolhido."):
        with st.spinner("Escrevendo título, descrição e chamada final..."):
            guardado = gerar_pacote(_contexto_do_video(res, corte), titulo_video=res.get("metadados", {}).get("titulo", ""),
                                    conta=conta, client=_cliente(api_key))
            st.session_state[chave("pacote")] = guardado
            # Os campos abaixo já existem na sessão e, por padrão, ignorariam o texto novo: são reescritos aqui,
            # antes de serem desenhados, senão clicar no botão pareceria não ter feito nada.
            for campo, origem in CAMPOS_DO_PACOTE:
                st.session_state[chave(campo)] = guardado["pacote"][origem]
    if guardado is None:
        guardado = gerar_pacote(_contexto_do_video(res, corte),
                                titulo_video=res.get("metadados", {}).get("titulo", ""), conta=conta)
    if guardado["degradado"]:
        st.info(f"Texto sem IA: {guardado['motivo_degradado']}. Edite à vontade abaixo.")
    for campo, origem in CAMPOS_DO_PACOTE:                    # valor inicial pela sessão: o widget não leva `value`,
        st.session_state.setdefault(chave(campo), guardado["pacote"][origem])   # senão o Streamlit reclama dos dois

    p1, p2 = st.columns(2)
    titulo_post = p1.text_input("Título da postagem", max_chars=120, key=chave("tit_post"))
    descricao = p1.text_area("Descrição do vídeo", height=120, key=chave("desc"))
    hashtags = p2.text_area("Hashtags", height=68, key=chave("tags"))
    com_fecho = p2.checkbox("Acrescentar um cartão final no vídeo", value=False, key=chave("tem_fecho"),
                            help="Um cartão desenhado depois do clipe, com locução. Custa uma renderização a "
                                 "mais; desligado, o vídeo termina no próprio corte.")
    chamada, botao_final = "", ""
    if com_fecho:
        chamada = p2.text_input("Frase do cartão final", max_chars=90, key=chave("chamada"))
        botao_final = p2.text_input("Texto do botão", max_chars=MAX_BOTAO, key=chave("botao"),
                                    help="Em branco, o cartão final fica só com a frase, sem botão.")

    # ---- textos dentro do vídeo ----
    with st.expander("✍️ Textos na tela do clipe", expanded=False):
        t1, t2 = st.columns(2)
        st.caption("Em branco, nada aparece sobre a imagem além da legenda — que é o padrão.")
        etiqueta = t1.text_input("Etiqueta", "", max_chars=MAX_TAG, key=chave("tag"), placeholder=f"ex.: Corte {indice + 1}")
        titulo_clipe = t2.text_input("Título sobre o clipe", "", max_chars=MAX_TITULO, key=chave("tit"),
                                     placeholder=corte["titulo"][:50])
        com_capa = st.checkbox("Incluir um cartão de abertura antes do clipe", value=False, key=chave("tem_capa"))
        capa = None
        if com_capa:
            if roteiro.get("degradado"):
                st.warning(f"⚠️ O roteiro desta análise não veio da IA ({roteiro.get('motivo_degradado', '')}), e o "
                           "roteiro-modelo da TACTO Studio não é usado aqui: escreva a abertura você mesmo.")
            base, _ = ed.cenas_do_roteiro(roteiro, corte["titulo"])
            a1, a2 = st.columns(2)
            capa = dict(base)
            capa["titulo"] = a1.text_input("Título da abertura", base["titulo"], max_chars=MAX_TITULO, key=chave("capa_tit"))
            capa["fala"] = a2.text_area("Fala da abertura", base["fala"], height=90, key=chave("capa_fala"))

    idiomas = st.multiselect("Idiomas do vídeo", list(IDIOMAS), default=[IDIOMA_ORIGINAL], format_func=IDIOMAS.get,
                             key=chave("idiomas"),
                             help="Um vídeo por idioma, com os textos traduzidos e um .srt. Instagram e TikTok não "
                                  "trocam de legenda sozinhos: por lá, é um vídeo para cada idioma.")

    problemas = [f"cartão final: {p}" for p in problemas_da_cena(_cartao_final(chamada, botao_final))] if com_fecho else []
    if capa is not None:
        problemas += [f"abertura: {p}" for p in problemas_da_cena(_com_correcao(capa))]
    if not idiomas:
        problemas.append("escolha ao menos um idioma")
    if problemas:
        st.warning("Antes de montar:\n\n" + "\n".join(f"- {p}" for p in problemas))

    duracao_corte = corte["fim_segundos"] - corte["inicio_segundos"]
    cartoes = 4.5 * (bool(com_fecho) + bool(capa))
    st.caption(f"Cada vídeo vai ter cerca de {duracao_corte + cartoes:.0f} s, e montar leva por volta de "
               f"{(duracao_corte * 0.5 + 8 + cartoes * 2):.0f} s"
               + (f" — vezes {len(idiomas)} idiomas." if len(idiomas) > 1 else "."))

    arte = uf.proteger_legenda_da_imagem(arte, legenda)
    montagem = dict(tema=tema, titulo=titulo_clipe, etiqueta=etiqueta, marca=marca, logo=logo,
                    enquadramento=enquadramento, com_caixa_legenda=legenda["com_caixa"], com_barra=com_barra,
                    arte=arte, estilo_legenda=uf.estilo_da_legenda(legenda["estilo"], arte),
                    produto_ml=produto_ml)

    contexto_legenda = f"Vídeo: {titulo_clipe or corte.get('titulo', '')}. Termos/Técnicas: {legenda.get('prompt_guia', '')}".strip()
    blocos_iniciais = []
    if legenda["ligada"]:
        blocos_iniciais = lg.montar_legendas(falas, corte["inicio_segundos"], corte["fim_segundos"],
                                             contexto=contexto_legenda)["blocos"]
    legendas_editadas = uf.editor_de_legendas(chave("editor"), blocos_iniciais) if legenda["ligada"] else []

    b_previa, b_montar = st.columns([1, 1.4])
    if b_previa.button("🔍 Prévia de um quadro", key=chave("btn_previa"), use_container_width=True,
                       help="Baixa o trecho (uma vez só: a montagem reaproveita) e desenha um quadro com tudo "
                            "aplicado — cor, zoom, legenda e a marca apagada. Leva segundos, não o minuto do vídeo."):
        with st.spinner("Buscando o trecho e desenhando um quadro..."):
            try:
                clipe = _clipe_do_corte(url_video, video_id, indice, corte, altura)
                ffmpeg = localizar_ffmpeg()
                props = ed.sondar_clipe(clipe, ffmpeg)
                amostra = []
                if legenda["ligada"]:
                    blocos_base = legendas_editadas or lg.montar_legendas(falas, corte["inicio_segundos"], corte["fim_segundos"],
                                                                          contexto=contexto_legenda)["blocos"]
                    amostra = uf.amostra_da_legenda(blocos_base)
                uf.gerar_previa(chave("md"), clipe, ffmpeg, props, escolha_marca,
                                uf.segundo_da_previa(amostra, props["duracao"]), legendas=amostra, **montagem)
            except (FalhaNoCorte, ed.FalhaNaEdicao, RuntimeError) as erro:
                st.error(f"Não consegui gerar a prévia: {erro}")
    uf.mostrar_previa(chave("md"))

    if b_montar.button("🎬 Montar o vídeo pronto", type="primary", disabled=bool(problemas), key=chave("btn"),
                       use_container_width=True):
        barra = st.progress(0.0, text="Buscando o trecho no YouTube...")
        client = _cliente(api_key)
        voz = voz_escolhida.rsplit("(", 1)[1].rstrip(")") if voz_escolhida != SEM_VOZ else None
        carimbo = time.strftime("%Y%m%d_%H%M%S")
        resultados = {}
        try:
            clipe = _clipe_do_corte(url_video, video_id, indice, corte, altura)
            ffmpeg = localizar_ffmpeg()
            barra.progress(0.02, text="Procurando marca d'água...")
            regiao, aviso_marca = uf.resolver_marca(escolha_marca, clipe, ffmpeg, ed.sondar_clipe(clipe, ffmpeg),
                                                    chave("md"))
            legendas, aviso_legenda, aviso_sincronia = [], None, None
            if legenda["ligada"]:
                if legenda.get("whisper_local"):
                    barra.progress(0.04, text="Ouvindo o áudio na CPU com Whisper (R$ 0)...")
                    prompt_w = uf.prompt_inicial_whisper(legenda.get("prompt_guia", ""))
                    reconhecido = uf.falas_do_clipe_whisper(clipe, ffmpeg, idioma_fala, prompt_w)
                    dur_clipe = ed.sondar_clipe(clipe, ffmpeg)["duracao"]
                    montadas = lg.montar_legendas(reconhecido["falas"], 0.0, dur_clipe, ouvidas=reconhecido["palavras"],
                                                  contexto=contexto_legenda)
                    legendas = montadas["blocos"]
                    aviso_sincronia = "⏱️ Legenda gerada pelo áudio na CPU via Whisper."
                else:
                    ouvidas = None
                    if sincronizar:
                        barra.progress(0.04, text="Ouvindo o trecho para sincronizar a legenda (~metade da duração)...")
                        ouvidas = uf.ouvidas_do_clipe(res["transcricao"], clipe, ffmpeg, corte["inicio_segundos"],
                                                      corte["fim_segundos"], idioma_fala,
                                                      prompt_inicial=legenda.get("prompt_guia", ""))
                    montadas = lg.montar_legendas(falas, corte["inicio_segundos"], corte["fim_segundos"],
                                                  client if legenda["revisar"] else None, ouvidas=ouvidas,
                                                  contexto=contexto_legenda)
                    aviso_sincronia = uf.aviso_de_sincronia(montadas["sincronia"])
                    legendas = montadas["blocos"]
                    aviso_legenda = montadas["motivo_degradado"] if legenda["revisar"] else None

                # Se o usuário revisou/editou frases na tabela do editor:
                if legendas_editadas:
                    for i, b_edit in enumerate(legendas_editadas):
                        if i < len(legendas):
                            legendas[i]["texto"] = b_edit["texto"]
            for n, codigo in enumerate(idiomas):
                inicio_faixa = n / len(idiomas)
                barra.progress(inicio_faixa, text=f"{IDIOMAS[codigo]}: traduzindo os textos...")
                na_tela = {"titulo_clipe": titulo_clipe, "chamada": chamada, "botao": botao_final,
                           "titulo_post": titulo_post, "descricao": descricao}
                # o pacote de texto só precisa de tradução do que de fato aparece ou é publicado
                if capa is not None:
                    na_tela |= {"capa_titulo": capa["titulo"], "capa_fala": capa["fala"]}
                textos, legendas_idioma, aviso = _traduzir_tudo(na_tela, legendas, codigo, client, idioma_fala,
                                                                legenda["acompanha_idioma"])

                capa_idioma = None
                if capa is not None:
                    capa_idioma = _com_correcao({**capa, "titulo": textos["capa_titulo"], "fala": textos["capa_fala"]})
                nome = nome_do_arquivo(textos["titulo_post"] or titulo_clipe or corte["titulo"],
                                       indice + 1, codigo, carimbo, com_idioma=len(idiomas) > 1)
                dados = ed.montar_reels(clipe, **{**montagem, "titulo": textos["titulo_clipe"]},
                                        legendas=legendas_idioma, marca_dagua=regiao, capa=capa_idioma,
                                        fecho=_cartao_final(textos["chamada"], textos["botao"]) if com_fecho else None,
                                        voz=voz_do_idioma(voz, codigo), config_audio=config_audio,
                                        nome_arquivo=nome, pasta_saida=PASTA_REELS,
                                        progresso=lambda p, msg: barra.progress(
                                            min(1.0, inicio_faixa + p / len(idiomas)), text=f"{IDIOMAS[codigo]}: {msg}"))

                resultados[codigo] = {**dados, "nome": nome, "aviso": aviso or aviso_legenda, "titulo_post": textos["titulo_post"],
                                      "descricao": textos["descricao"], "hashtags": hashtags, "aviso_marca": aviso_marca,
                                      "aviso_sincronia": aviso_sincronia}
        except (FalhaNoCorte, ed.FalhaNaEdicao, rg.FalhaRenderizacao, RuntimeError) as erro:
            barra.empty()
            st.error(f"Não consegui montar o vídeo: {erro}")
        else:
            barra.empty()
            st.session_state[chave("videos")] = resultados

    prontos = st.session_state.get(chave("videos"))
    if prontos:
        st.divider()
        if len(prontos) == 1:
            _mostrar(next(iter(prontos.values())), next(iter(prontos)))
        else:
            for aba, (codigo, dados) in zip(st.tabs([IDIOMAS[c] for c in prontos]), prontos.items()):
                with aba:
                    _mostrar(dados, codigo)
