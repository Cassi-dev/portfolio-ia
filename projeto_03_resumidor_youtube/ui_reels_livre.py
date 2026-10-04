"""Tela "Criar vídeo de qualquer assunto" do app do Projeto 3: contexto -> roteiro editável -> vídeo .mp4."""
import io
import time

import streamlit as st
from PIL import Image

import criador_reels as cr
import renderizador_generico as rg
from core.llm import FalhaLLM, criar_cliente
from esquemas_reels import LAYOUTS, MAX_BOTAO, MAX_ROTULO, MAX_TAG, MAX_TITULO, problemas_da_cena
from temas_video import PRESETS, TEMA_PADRAO

ROTULOS_LAYOUT = {"titulo": "Título (frase de impacto)", "lista": "Lista (2 a 4 itens)", "numero": "Número em destaque",
                  "comparacao": "Comparação (2 lados)", "cta": "Chamada final (botão)"}
SEM_VOZ = "Sem voz (vídeo mudo)"
VOZES = [f"{nome} ({id_})" for id_, nome in rg.VOZES.items()] + [SEM_VOZ]
ORIGEM_TEXTO, ORIGEM_YOUTUBE = "Escrever ou colar um texto", "Usar o resumo do vídeo do YouTube que analisei"
CONTEXTO_EXEMPLO = (
    "Trocar as lâmpadas da casa por LED reduz o consumo de energia em até 80% em comparação com as incandescentes. "
    "Uma lâmpada LED dura em média 25.000 horas, enquanto a incandescente dura cerca de 1.000 horas. "
    "Deixar aparelhos em modo de espera continua consumindo energia o dia todo. "
    "Tirar da tomada o que não está em uso é um jeito simples de economizar. "
    "Aproveitar a luz natural durante o dia também diminui a conta no fim do mês."
)


def _contexto_do_youtube() -> str:
    res = st.session_state.get("resultado_youtube", {})
    sintese, meta = res.get("sintese", {}), res.get("metadados", {})
    partes = [meta.get("titulo", ""), sintese.get("resumo_executivo", "")]
    partes += [f"{t.get('titulo', '')}: {t.get('descricao', '')}" for t in sintese.get("topicos_com_minutagem", [])]
    partes.append(sintese.get("conclusao", ""))
    return "\n".join(p for p in partes if p)


def _cliente(api_key: str):
    if not api_key.strip():
        return None
    try:
        return criar_cliente(api_key)
    except FalhaLLM as erro:
        st.warning(f"Não foi possível iniciar o Gemini ({erro}). Seguindo sem IA.")
        return None


def _linhas(texto: str) -> list[str]:
    return [l.strip() for l in texto.splitlines() if l.strip()]


def _campos_da_cena(i: int, base: dict, v: int) -> dict:
    """Desenha os campos de edição de uma cena e devolve a cena com os valores atuais dos widgets."""
    k = lambda nome: f"rl{v}_{i}_{nome}"
    layout = st.selectbox("Layout", LAYOUTS, index=LAYOUTS.index(base["layout"]), format_func=ROTULOS_LAYOUT.get, key=k("layout"))
    cena = {"layout": layout, "rotulos": [], "destaque_valor": "", "destaque_rotulo": "", "botao": ""}
    c1, c2 = st.columns([1, 2])
    cena["tag"] = c1.text_input("Etiqueta", base["tag"], max_chars=MAX_TAG, key=k("tag"))
    cena["titulo"] = c2.text_input("Título na tela", base["titulo"], max_chars=MAX_TITULO, key=k("titulo"))
    cena["fala"] = st.text_area("Fala (o que a voz narra e aparece na legenda)", base["fala"], height=110, key=k("fala"))

    itens_base = "\n".join(base["itens"])
    if layout == "lista":
        cena["itens"] = _linhas(st.text_area("Itens (um por linha, de 2 a 4)", itens_base, height=110, key=k("itens")))
    elif layout == "comparacao":
        cena["itens"] = _linhas(st.text_area("Os dois lados (uma linha para cada)", itens_base, height=90, key=k("itens")))
        r = (base["rotulos"] + ["ANTES", "DEPOIS"])[:2]
        r1, r2 = st.columns(2)
        cena["rotulos"] = [r1.text_input("Rótulo do 1º lado", r[0], max_chars=MAX_ROTULO, key=k("rot1")),
                           r2.text_input("Rótulo do 2º lado", r[1], max_chars=MAX_ROTULO, key=k("rot2"))]
    else:
        if layout == "numero":
            n1, n2 = st.columns([1, 2])
            cena["destaque_valor"] = n1.text_input("Número", base["destaque_valor"], max_chars=24, key=k("valor"),
                                                   help='Como aparece no seu texto, ex.: "27%" ou "R$ 50.000". Conta de 0 até ele no vídeo.')
            cena["destaque_rotulo"] = n2.text_input("O que ele mede", base["destaque_rotulo"], max_chars=80, key=k("rotulo"))
        if layout == "cta":
            cena["botao"] = st.text_input("Texto do botão", base["botao"], max_chars=MAX_BOTAO, key=k("botao"))
        cena["itens"] = _linhas(st.text_area("Linhas de apoio (opcional, até 2)", itens_base, height=68, key=k("itens")))[:2]
    return cena


def _mostrar_video(dados: dict):
    with open(dados["caminho"], "rb") as f:
        conteudo = f.read()
    col_v, col_i = st.columns([1, 1.6])
    with col_v:
        st.video(conteudo)
    with col_i:
        st.success(f"Vídeo pronto: {dados['duracao_segundos']:.0f} s, 1080x1920 (9:16), {dados['voz']}.")
        st.download_button("📥 Baixar vídeo (.mp4)", conteudo, file_name=dados["nome"], mime="video/mp4", use_container_width=True)
        st.caption(f"Salvo em `{dados['caminho']}`")


def tela_criar_video(api_key: str) -> None:
    st.markdown("### 1. Sobre o que é o vídeo?")
    origens = [ORIGEM_TEXTO] + ([ORIGEM_YOUTUBE] if "resultado_youtube" in st.session_state else [])
    origem = st.radio("Origem do contexto", origens, horizontal=True, label_visibility="collapsed")
    padrao = _contexto_do_youtube() if origem == ORIGEM_YOUTUBE else CONTEXTO_EXEMPLO
    contexto = st.text_area("Contexto do vídeo", padrao, height=170, key=f"rl_ctx_{origens.index(origem)}",
                            help="Cole o assunto, um artigo, notas de reunião, a descrição de um produto... O vídeo só usa fatos e "
                                 "números que estiverem aqui. O texto de exemplo é só para você testar: troque pelo seu.")
    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1.6])
    duracao = c1.select_slider("Duração alvo (s)", [15, 30, 45, 60, 90], value=45)
    tom = c2.selectbox("Tom", cr.TONS)
    publico = c3.text_input("Público (opcional)", placeholder="ex.: donos de restaurante")
    cta = c4.text_input("Chamada final (opcional)", placeholder="ex.: Siga para mais dicas", max_chars=MAX_BOTAO)

    with st.expander("🎨 Aparência e voz", expanded=False):
        a1, a2, a3, a4 = st.columns([1.3, 1, 1, 1.2])
        nome_tema = a1.selectbox("Tema visual", list(PRESETS), index=list(PRESETS).index(TEMA_PADRAO))
        marca = a2.text_input("Marca (canto do cabeçalho)", placeholder="ex.: @meucanal", max_chars=30)
        arquivo_logo = a3.file_uploader("Logo (opcional)", type=["png", "jpg", "jpeg"])
        voz_escolhida = a4.selectbox("Voz da locução", VOZES)

    if st.button("✍️ Criar roteiro", type="primary"):
        try:
            with st.spinner("Escrevendo o roteiro..." if api_key.strip() else "Dividindo o texto em cenas..."):
                resultado = cr.criar_plano(contexto, _cliente(api_key), duracao_alvo=duracao, tom=tom, publico=publico, cta=cta)
        except cr.ContextoVazio as erro:
            st.error(str(erro))
        else:
            st.session_state.rl = {"resultado": resultado, "versao": st.session_state.get("rl", {}).get("versao", 0) + 1, "contexto": contexto}
            st.session_state.pop("rl_video", None)

    if "rl" not in st.session_state:
        st.info("Escreva o contexto e clique em **Criar roteiro**. Você revisa e edita cada cena antes de gerar o vídeo.")
        return

    dados, v = st.session_state.rl["resultado"], st.session_state.rl["versao"]
    plano = dados["plano"]
    st.divider()
    st.markdown("### 2. Revise o roteiro")
    if dados["degradado"]:
        st.warning(f"⚠️ **Modo degradado:** {dados['motivo_degradado']}.")
    for aviso in dados["avisos"]:
        st.info(aviso)

    tema = PRESETS[nome_tema]
    logo = None
    if arquivo_logo is not None:
        try:
            logo = Image.open(io.BytesIO(arquivo_logo.getvalue()))
        except OSError:
            st.warning("Não consegui abrir o logo enviado; seguindo sem ele.")
    estilo = rg.criar_estilo(tema, marca, logo)

    cenas, total = [], len(plano["cenas"])
    for i, base in enumerate(plano["cenas"], 1):
        with st.container(border=True):
            st.markdown(f"**Cena {i} de {total}**")
            col_previa, col_campos = st.columns([1, 2.2])
            with col_campos:
                cena = _campos_da_cena(i, base, v)
                cena["itens"] = cena.get("itens", [])
            cenas.append(cena)
            with col_previa:
                if problemas_da_cena(cena):
                    st.warning("Complete os campos para ver a prévia: " + "; ".join(problemas_da_cena(cena)) + ".")
                else:
                    st.image(rg.quadro_de_previa(cena, i, total, estilo), caption="Prévia (com tudo já na tela)")

    legenda = st.text_area("Legenda para postar", plano["legenda_instagram"], height=120, key=f"rl{v}_legenda")
    hashtags = st.text_area("Hashtags", plano["hashtags"], height=60, key=f"rl{v}_hashtags")

    plano_atual = {**plano, "cenas": cenas, "legenda_instagram": legenda, "hashtags": hashtags}
    problemas = cr.plano_valido(plano_atual)
    st.divider()
    st.markdown("### 3. Gerar o vídeo")
    if problemas:
        st.error("Antes de gerar, corrija:\n\n" + "\n".join(f"- {p}" for p in problemas))
    usar_voz = voz_escolhida != SEM_VOZ
    palavras = sum(len(c["fala"].split()) for c in cenas)
    estimativa = palavras / cr.PALAVRAS_POR_SEGUNDO + 0.95 * total
    st.caption(f"Duração estimada: cerca de {estimativa:.0f} s. A renderização leva algo em torno de {estimativa * 0.8 + 8:.0f} s"
               + (" e a locução precisa de internet." if usar_voz else "."))

    if st.button("🚀 Renderizar vídeo", disabled=bool(problemas)):
        barra = st.progress(0.0, text="Começando...")
        try:
            id_voz = voz_escolhida.rsplit("(", 1)[1].rstrip(")") if usar_voz else None
            nome = f"{rg.nome_de_arquivo(plano['titulo_video'])[:-4]}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            resultado = rg.renderizar_video(plano_atual, tema, voz=id_voz, marca=marca, logo=logo, nome_arquivo=nome,
                                            progresso=lambda p, msg: barra.progress(min(1.0, p), text=msg))
        except rg.FalhaRenderizacao as erro:
            barra.empty()
            st.error(str(erro))
        else:
            barra.empty()
            st.session_state.rl_video = {**resultado, "nome": nome, "voz": f"voz {rg.VOZES.get(id_voz, id_voz)}" if id_voz else "sem voz"}

    if "rl_video" in st.session_state:
        _mostrar_video(st.session_state.rl_video)
