"""
Controles de edição que as três telas de montagem compartilham: vídeo pronto (aba Roteiro), Edição e o editor
de vídeo local. Cada função desenha os campos e devolve o que a montagem precisa, sem montar nada.
"""
from dataclasses import replace
from pathlib import Path

import streamlit as st

import audio_estudio as ae
import editor_reels as ed
import efeitos as ef
import marca_dagua as md
import momentos as mo
import fala_local
import publicacao as pub


REVISADA = "Legenda do vídeo, revisada pela IA (1 chamada)"
COMO_ESTA = "Legenda do vídeo como está (sem IA, custo zero)"
WHISPER_LOCAL = "Transcrever áudio na CPU (Whisper local, R$ 0)"
TRADUZIDA = "Traduzida para português (1 chamada)"
NO_ORIGINAL = "No idioma da fala, como está (sem IA)"
DA_IMAGEM = "Não gerar: manter só a legenda que já está na imagem"
DA_RECEITA = "receita"                  # estilo de legenda escolhido pela receita de edição


# ==============================================================================
# LEGENDA
# ==============================================================================
def idioma_da_fala(transcricao: dict) -> str:
    """
    "pt", "ja", "en"... pela sigla guardada na análise. Análises antigas só guardaram o nome
    ("Portuguese (auto-generated)"): aí só dá para saber se é português ou não ("" = outro, desconhecido).
    """
    codigo = pub.idioma_base(transcricao.get("codigo_idioma", ""))
    if codigo:
        return codigo
    return "pt" if "portug" in str(transcricao.get("idioma", "")).lower() else ""


def transcricao_em_portugues(transcricao: dict) -> bool:
    return idioma_da_fala(transcricao) == "pt"


def campos_legenda(chave, disponivel: bool = True, idioma_fala: str = "pt", nome_idioma: str = "",
                   amostra: str = "", tem_chave: bool = True) -> dict:
    """
    O que fazer com a legenda, com o custo de cada escolha escrito nela:

    - fala em português: a legenda do vídeo revisada pela IA (1 chamada), transcrever áudio na CPU (Whisper local),
      como está (nenhuma), ou nada;
    - fala em outro idioma: traduzida para português (1 chamada — sem revisão antes: a tradução já sai
      pontuada), no idioma da fala como está (nenhuma), ou nada.

    "Não gerar" é para o vídeo que já traz legenda na própria imagem: nada é desenhado por cima e a faixa de
    cinema é desligada, porque ela cortaria justamente a parte de baixo da imagem, onde essa legenda fica.

    A opção "no idioma da fala" some quando a escrita não tem fonte no vídeo (japonês, chinês, coreano,
    árabe...): sairia um quadradinho por letra.

    Devolve {"ligada", "revisar", "traduzir", "whisper_local", "prompt_guia", "acompanha_idioma", "da_imagem", "estilo", "com_caixa"}.
    """
    estrangeira = idioma_fala != "pt"
    if estrangeira:
        opcoes = [TRADUZIDA]
        if pub.escrita_desenhavel(amostra):
            opcoes.append(NO_ORIGINAL)
    else:
        opcoes = [REVISADA]
        if fala_local.disponivel():
            opcoes.append(WHISPER_LOCAL)
        opcoes.append(COMO_ESTA)
    opcoes.append(DA_IMAGEM)
    padrao = 0 if (estrangeira or tem_chave) else (opcoes.index(WHISPER_LOCAL) if WHISPER_LOCAL in opcoes else opcoes.index(COMO_ESTA))
    ajuda = ("A revisão corrige pontuação e erros da legenda automática; 'Whisper local' ouve o áudio na CPU com custo zero; "
             "'como está' usa o texto do YouTube sem mexer.")
    if not disponivel:
        ajuda = "Esta análise é anterior à legenda queimada: analise o vídeo de novo."
    elif estrangeira:
        ajuda = (f"A fala está em {nome_idioma or 'outro idioma'}: a IA traduz a legenda para português numa "
                 "chamada só, e o tempo continua o do áudio.")
    c1, c2, c3 = st.columns([1.6, 1.4, 1])
    escolha = c1.radio("Legenda", opcoes, index=padrao if disponivel else len(opcoes) - 1, key=f"{chave}_leg",
                       disabled=not disponivel, help=ajuda)
    ligada = escolha != DA_IMAGEM and disponivel
    traduzir = ligada and escolha == TRADUZIDA
    revisar = ligada and escolha == REVISADA
    whisper_local = ligada and escolha == WHISPER_LOCAL

    prompt_guia = ""
    if ligada:
        prompt_guia = st.text_input(
            "💡 Técnicas em japonês, termos e nomes (opcional)",
            key=f"{chave}_prompt_guia",
            placeholder="Ex: Bankai, Getsuga Tensho, Rengoku, Akaza, Hinokami Kagura",
            help="Ensina a IA e a CPU a grafar corretamente técnicas em japonês e nomes próprios sem traduzir para português nem inventar palavras."
        )

    if (traduzir or revisar) and not tem_chave:
        st.warning("Sem a chave do Gemini não dá para " + ("traduzir: a legenda sairia em "
                   f"{nome_idioma or 'outro idioma'}" + ("." if pub.escrita_desenhavel(amostra) else
                   ", que a fonte do vídeo nem desenha — ela vai ficar de fora.") if traduzir else
                   "revisar: a legenda sai como está no YouTube."))
    return {"ligada": ligada, "revisar": revisar, "traduzir": traduzir, "whisper_local": whisper_local,
            "prompt_guia": prompt_guia, "da_imagem": escolha == DA_IMAGEM,
            "acompanha_idioma": ligada and escolha != NO_ORIGINAL, **campos_estilo_legenda(chave, ligada, c2, c3)}


def campo_sincronia(chave, legenda: dict, ja_medido: bool = False) -> bool:
    """
    Sincronizar a legenda pelo áudio: o texto continua o da transcrição e o tempo de cada palavra passa a ser
    o medido pelo reconhecimento de fala local (fala_local.py). Grátis, e leva ~metade da duração do trecho.
    Quando a transcrição já veio do reconhecimento local, o tempo já é medido e não há o que escolher.
    """
    if not legenda.get("ligada") or legenda.get("whisper_local"):
        return False
    if ja_medido:
        st.caption("⏱️ O tempo de cada palavra já é o medido no áudio (a transcrição veio do reconhecimento local).")
        return True
    if not fala_local.disponivel():
        return False
    return st.checkbox("⏱️ Sincronizar a legenda pelo áudio (no computador, grátis — leva ~metade da duração do trecho)",
                       value=True, key=f"{chave}_sinc",
                       help="Sem isso, o tempo de cada palavra é estimado pelo tamanho dela. Medido contra um "
                            "gabarito, a estimativa erra 0,12 s em média e até 0,95 s; o áudio, 0,05 s e até 0,30 s.")


def ouvidas_do_clipe(transcricao: dict, clipe, ffmpeg: str, inicio: float, fim: float, idioma: str = "",
                     prompt_inicial: str = "") -> list:
    """As palavras medidas no áudio do trecho: da transcrição local, se ela existe; senão, ouvindo o clipe agora."""
    if transcricao.get("palavras_ouvidas"):
        return fala_local.ouvidas_no_trecho(transcricao["palavras_ouvidas"], inicio, fim)
    kw = {"prompt_inicial": prompt_inicial} if prompt_inicial else {}
    return fala_local.reconhecer_clipe(clipe, ffmpeg, idioma or None, **kw)["palavras"]


def falas_do_clipe_whisper(clipe, ffmpeg: str, idioma: str = "", prompt_inicial: str = "") -> dict:
    """Reconhece fala e palavras diretamente do clipe com Whisper local guiado."""
    kw = {"prompt_inicial": prompt_inicial} if prompt_inicial else {}
    return fala_local.reconhecer_clipe(clipe, ffmpeg, idioma or None, **kw)


def prompt_inicial_whisper(prompt_usuario: str = "") -> str:
    """Instrução-base de diálogo claro e termos em romaji combinada com os termos do usuário."""
    base = "Diálogo claro e pontuado. Nomes de técnicas e termos em japonês (como Bankai, Getsuga Tensho, Rasengan, Reiatsu) grafados em romaji."
    return f"{base} {prompt_usuario}".strip() if prompt_usuario else base


def editor_de_legendas(chave: str, blocos_iniciais: list,
                       titulo: str = "✏️ Revisar / Editar falas da legenda (opcional)") -> list:
    """
    Exibe uma tabela compacta (st.data_editor) permitindo ao usuário revisar e editar o texto
    de cada bloco de legenda antes da renderização. Retorna a lista de blocos (atualizada com as edições).
    """
    if not blocos_iniciais:
        return []

    chave_estado = f"{chave}_blocos_legendas"
    # Inicializa ou sincroniza se ainda não estiver no estado ou mudou contagem
    if chave_estado not in st.session_state or len(st.session_state[chave_estado]) != len(blocos_iniciais):
        st.session_state[chave_estado] = [dict(b) for b in blocos_iniciais]

    with st.expander(titulo, expanded=False):
        st.caption("💡 Clique na coluna **Texto da Legenda** para corrigir qualquer palavra, gíria ou pontuação. "
                   "A prévia e o vídeo gerado usarão exatamente o texto corrigido.")

        linhas = []
        for i, b in enumerate(st.session_state[chave_estado]):
            linhas.append({
                "#": i + 1,
                "Início": f"{float(b.get('inicio', 0.0)):.2f}s",
                "Fim": f"{float(b.get('fim', 0.0)):.2f}s",
                "Texto da Legenda": str(b.get("texto", ""))
            })

        editados = st.data_editor(
            linhas,
            key=f"{chave}_tabela_legendas",
            disabled=["#", "Início", "Fim"],
            column_config={
                "#": st.column_config.NumberColumn("#", width="small"),
                "Início": st.column_config.TextColumn("Início", width="small"),
                "Fim": st.column_config.TextColumn("Fim", width="small"),
                "Texto da Legenda": st.column_config.TextColumn("Texto da Legenda", width="large")
            },
            hide_index=True,
            use_container_width=True
        )

        # Atualiza o texto dos blocos no session_state com as modificações do usuário
        if editados:
            for i, linha in enumerate(editados):
                if i < len(st.session_state[chave_estado]):
                    novo_texto = str(linha.get("Texto da Legenda", "")).strip()
                    if novo_texto:
                        st.session_state[chave_estado][i]["texto"] = novo_texto

    return st.session_state[chave_estado]


def aviso_de_sincronia(sincronia) -> str | None:
    """Frase para a tela; None quando não houve sincronia pedida."""
    if sincronia is None:
        return None
    if sincronia < fala_local.COBERTURA_MINIMA:
        return (f"O áudio não bateu com o texto da legenda (só {sincronia:.0%} das palavras acharam par): ficou o "
                "tempo estimado.")
    return f"⏱️ Legenda sincronizada pelo áudio: {sincronia:.0%} das palavras acharam par no que foi ouvido."


def proteger_legenda_da_imagem(arte: ef.DirecaoDeArte, legenda: dict) -> ef.DirecaoDeArte:
    """
    Quem escolheu manter a legenda que já está na imagem não pode perdê-la para a faixa de cinema: o recorte
    para 2,39:1 tira 12% de cima e de baixo do vídeo, e a legenda queimada mora nos 15% de baixo.
    """
    if legenda.get("da_imagem") and arte.cinemascope:
        st.caption("🎞️ Faixa de cinema desligada: ela cortaria a legenda que já está na imagem.")
        return replace(arte, cinemascope=False)
    return arte


def estilo_da_legenda(escolhido: str, arte: ef.DirecaoDeArte) -> str:
    """"Automático" vira o estilo da receita; sem receita, o clássico."""
    if escolhido == DA_RECEITA:
        return arte.estilo_legenda or ed.CLASSICA
    return escolhido


def amostra_da_legenda(blocos: list) -> list:
    """
    A legenda da prévia vai sem tradução (traduzir a cada clique gastaria chamada). Se a fala está numa
    escrita que a fonte não desenha, a prévia sai sem legenda em vez de uma fileira de quadradinhos.
    """
    return [b for b in blocos if pub.escrita_desenhavel(b["texto"])]


def traduzir_varios(listas: list, destino: str, client, origem: str) -> tuple:
    """
    As legendas de vários trechos traduzidas numa chamada só (a Edição tem até 6 trechos). Devolve (listas,
    aviso). Se a tradução falhar e a fala não puder ser desenhada, os trechos saem sem legenda, com aviso.
    """
    todos = [b for blocos in listas for b in blocos]
    traduzidos, aviso = pub.traduzir_legendas(todos, destino, client, origem)
    if aviso and not pub.escrita_desenhavel(" ".join(b["texto"] for b in traduzidos)):
        return [[] for _ in listas], (f"{aviso}. A fala está numa escrita que a fonte do vídeo não desenha, "
                                      "então o vídeo saiu sem legenda")
    saida, i = [], 0
    for blocos in listas:
        saida.append(traduzidos[i:i + len(blocos)])
        i += len(blocos)
    return saida, aviso


def campos_estilo_legenda(chave, habilitado: bool, col_estilo=None, col_caixa=None) -> dict:
    col_estilo, col_caixa = col_estilo or st, col_caixa or st
    opcoes = {DA_RECEITA: "Automático (o da receita de edição)", **ed.ESTILOS_LEGENDA}
    estilo = col_estilo.selectbox("Estilo da legenda", list(opcoes), format_func=opcoes.get,
                                  key=f"{chave}_estilo_leg", disabled=not habilitado,
                                  help="Palavra em destaque e Impacto acompanham a fala palavra por palavra, na "
                                       "cor de destaque do tema. Sem receita, o automático é o clássico.")
    col_caixa.write("")
    com_caixa = col_caixa.checkbox("Caixa atrás da legenda", value=False, key=f"{chave}_caixa",
                                   disabled=not habilitado,
                                   help="Desligada, a legenda fica direto sobre a imagem, com contorno nas letras.")
    return {"estilo": estilo, "com_caixa": com_caixa}


# ==============================================================================
# DIREÇÃO DE ARTE
# ==============================================================================
PERSONALIZADA = "personalizada"


def campos_direcao_de_arte(chave, com_transicao: bool = False) -> ef.DirecaoDeArte:
    """
    Primeiro a receita (o estilo de edição de cada situação de anime); "Personalizada" abre os controles um
    a um. As chaves dos controles de uma receita levam o nome dela: trocar de receita traz os valores da nova,
    em vez de carregar os da anterior.
    """
    opcoes = [PERSONALIZADA] + list(ef.RECEITAS)
    nome = st.selectbox("Receita de edição", opcoes, key=f"{chave}_receita",
                        format_func=lambda k: "Personalizada (eu escolho cada efeito)" if k == PERSONALIZADA
                        else ef.RECEITAS[k][0],
                        help="Cada receita junta o que um editor faria naquele tipo de cena. Os efeitos de "
                             "golpe caem onde o som explode e o plano troca — medido no próprio clipe, sem IA.")
    if nome != PERSONALIZADA:
        base = ef.receita(nome)
        st.caption(ef.RECEITAS[nome][1])
        c1, c2 = st.columns(2)
        lenta = base.camera_lenta
        ramping = base.speed_ramping
        rastro = base.rastro_movimento
        glitch = base.glitch
        impacto = base.quadro_de_impacto
        if base.golpes_por_minuto:
            lenta = c1.checkbox("Câmera lenta no golpe mais forte", value=base.camera_lenta, key=f"{chave}_lenta_{nome}",
                                help="Meia velocidade por pouco mais de 1 s em volta do golpe; o som estica junto, "
                                     "sem engrossar a voz. O vídeo fica 1,2 s mais longo.")
            ramping = c1.checkbox("⚡ Speed Ramping multi-golpe (1,5x → 0,5x)", value=False,
                                  key=f"{chave}_ramp_{nome}",
                                  help="Acelera antes dos 3 golpes mais fortes e freia em câmera lenta no impacto.")
            e1, e2, e3 = st.columns(3)
            usar_manga = e1.checkbox("🖋️ Impact Frame Mangá P&B", value=False, key=f"{chave}_manga_{nome}",
                                     help="Troca o quadro de impacto por nanquim P&B de altíssimo contraste.")
            if usar_manga:
                impacto = "manga"
            rastro = e2.checkbox("💨 Motion Blur (rastro)", value=False, key=f"{chave}_blur_{nome}")
            glitch = e3.checkbox("📺 Glitch digital nos golpes", value=False, key=f"{chave}_glitch_{nome}")
        transicao = "corte"
        if com_transicao:
            transicao = c2.selectbox("Transição entre trechos", list(ef.TRANSICOES), format_func=ef.TRANSICOES.get,
                                     index=list(ef.TRANSICOES).index(base.transicao), key=f"{chave}_trans_{nome}")
        return replace(base, camera_lenta=lenta and not ramping, speed_ramping=ramping,
                       quadro_de_impacto=impacto, rastro_movimento=rastro, glitch=glitch, transicao=transicao)
    return _campos_personalizados(chave, com_transicao)


def _campos_personalizados(chave, com_transicao: bool) -> ef.DirecaoDeArte:
    c1, c2, c3 = st.columns([1.3, 1.5, 1.2 if com_transicao else 0.9])
    look = c1.selectbox("Filtro de cor", list(ef.LOOKS), format_func=lambda k: ef.LOOKS[k][0], key=f"{chave}_look")
    zoom = c2.selectbox("Zoom", list(ef.ZOOMS), format_func=lambda k: ef.ZOOMS[k][0], key=f"{chave}_zoom",
                        help="A imagem aproxima numa troca de frase e volta na seguinte — o corte de zoom dos "
                             "vídeos curtos. Sem legenda, alterna a cada 3 segundos.")
    transicao = "corte"
    if com_transicao:
        transicao = c3.selectbox("Transição entre trechos", list(ef.TRANSICOES), format_func=ef.TRANSICOES.get,
                                 key=f"{chave}_trans",
                                 help="Qualquer uma diferente do corte seco recodifica a peça inteira uma vez a "
                                      "mais: soma uns 20 a 30 s à montagem.")
    d1, d2, d3 = st.columns(3)
    vinheta = d1.checkbox("Vinheta (bordas escurecidas)", value=False, key=f"{chave}_vinheta")
    brilho = d2.checkbox("Brilho (halo nas luzes)", value=False, key=f"{chave}_brilho")
    cinemascope = d3.checkbox("Faixa de cinema (2,39:1)", value=False, key=f"{chave}_cinema",
                              help="Só no enquadramento de vídeo inteiro: a imagem vira uma faixa larga.")
    st.markdown("**Nos golpes** — onde o som explode e o plano troca, medido no clipe")
    g1, g2, g3 = st.columns(3)
    por_minuto = g1.slider("Golpes marcados por minuto", 0, 30, 0, key=f"{chave}_golpes",
                           help="Os mais fortes primeiro, com pelo menos 1 s entre eles. 0 desliga tudo abaixo.")
    impacto = g2.selectbox("Quadro de impacto", ["", "negativo", "vermelho", "manga"], key=f"{chave}_impacto",
                           format_func={"": "Nenhum", "negativo": "Invertido (negativo)",
                                        "vermelho": "Vermelho", "manga": "Mangá P&B (nanquim)"}.get,
                           help="O 'impact frame' do anime: um ou dois quadros de cor estourada no auge do golpe.")
    tremida = g3.slider("Tremida (pixels)", 0, 40, 0, key=f"{chave}_tremida")
    h1, h2, h3, h4 = st.columns(4)
    flash = h1.checkbox("Flash branco", value=False, key=f"{chave}_flash")
    rgb = h2.checkbox("Separação RGB", value=False, key=f"{chave}_rgb")
    aproxima = h3.checkbox("Aproximar no golpe", value=False, key=f"{chave}_aproxima")
    lenta = h4.checkbox("Câmera lenta no mais forte", value=False, key=f"{chave}_lenta")
    m1, m2, m3 = st.columns(3)
    ramping = m1.checkbox("⚡ Speed Ramping multi-golpe", value=False, key=f"{chave}_ramp")
    rastro = m2.checkbox("💨 Motion Blur (rastro)", value=False, key=f"{chave}_blur")
    glitch = m3.checkbox("📺 Glitch digital", value=False, key=f"{chave}_glitch")
    return ef.DirecaoDeArte(look=look, vinheta=vinheta, zoom=zoom, transicao=transicao, golpes_por_minuto=por_minuto,
                            quadro_de_impacto=impacto, flash=flash, tremida=tremida, separacao_rgb=rgb,
                            zoom_no_golpe=1.12 if aproxima else 1.0, camera_lenta=lenta and not ramping,
                            speed_ramping=ramping, rastro_movimento=rastro, glitch=glitch,
                            brilho=brilho, cinemascope=cinemascope)


# ==============================================================================
# ESTÚDIO DE ÁUDIO (TRILHA, AUTO-DUCKING, SFX E CORTE DE SILÊNCIOS) E AFILIADO ML
# ==============================================================================
def campos_audio_estudio(chave) -> ae.ConfigAudio:
    """Controles de trilha sonora com Auto-Ducking, efeitos sonoros de impacto (SFX) e corte de silêncio."""
    st.markdown("**🎧 Estúdio de Áudio e Ritmo**")
    opcoes_trilha = {k: v[0] for k, v in ae.TRILHAS.items()} | {"arquivo": "📂 Enviar arquivo .mp3/.wav próprio"}
    a1, a2 = st.columns([1.6, 1.2])
    escolha_trilha = a1.selectbox("Trilha sonora de fundo", list(opcoes_trilha), format_func=opcoes_trilha.get,
                                  key=f"{chave}_trilha")
    vol_pct = a2.slider("Volume da música (%)", 10, 70, 28, key=f"{chave}_vol_trilha",
                        disabled=escolha_trilha == "nenhuma")
    caminho_trilha = escolha_trilha
    if escolha_trilha == "arquivo":
        enviado = st.file_uploader("Arquivo de música (.mp3 ou .wav)", type=["mp3", "wav"], key=f"{chave}_arq_trilha")
        if enviado is not None:
            pasta_up = ae.PASTA_SONS / "uploads"
            pasta_up.mkdir(parents=True, exist_ok=True)
            destino = pasta_up / Path(enviado.name).name
            destino.write_bytes(enviado.getvalue())
            caminho_trilha = str(destino)
        else:
            caminho_trilha = "nenhuma"

    s1, s2, s3 = st.columns(3)
    ducking = s1.checkbox("🔉 Auto-Ducking na fala", value=True, key=f"{chave}_ducking",
                          disabled=caminho_trilha == "nenhuma",
                          help="Abaixa o volume da música automaticamente quando alguém fala e sobe nas pausas/lutas.")
    sfx = s2.checkbox("💥 SFX nos golpes e card (Bass Drop / Whoosh)", value=False, key=f"{chave}_sfx",
                      help="Injeta impacto sub-grave nos golpes, sopro de zoom e som digital no glitch.")
    cortar_sil = s3.checkbox("✂️ Cortar silêncios (> 0,45s)", value=False, key=f"{chave}_silencio",
                             help="Remove pausas mortas da fala (jump-cut de respiração) e reajusta a legenda.")
    return ae.ConfigAudio(trilha=caminho_trilha, volume_trilha=vol_pct / 100.0, auto_ducking=ducking,
                          sfx_impacto=sfx, cortar_silencios=cortar_sil)


def campo_produto_ml(chave, contexto: str = "") -> dict | None:
    """Seletor de produto afiliado do Mercado Livre (@corte.otakubr) com match automático pelo anime/tema."""
    produtos = ed.carregar_produtos_ml()
    if not produtos:
        return None
    opcoes = [None, "auto"] + produtos
    escolhido = st.selectbox(
        "🛒 Card flutuante de produto Mercado Livre (@corte.otakubr — últimos 3,5 s)",
        opcoes,
        format_func=lambda p: "Nenhum (sem card de produto)" if p is None
        else ("🤖 Automático pelo anime/tema do vídeo" if p == "auto"
              else f"[{p.get('codigo', 'ML')}] {p['nome']} — R$ {float(p.get('preco', 0)):.2f} ({p.get('entrega', 'FULL')})"),
        key=f"{chave}_prod_ml",
        help="Faz subir um card Tokyo Archive nos 3,5 segundos finais sem interromper a cena do anime.",
    )
    if escolhido == "auto":
        sugerido = ed.sugerir_produto_ml(contexto, produtos, usar_destaque_padrao=True)
        if sugerido:
            st.caption(
                f"🎯 **Match automático:** [{sugerido.get('codigo', 'ML')}] {sugerido['nome']} "
                f"({sugerido.get('anime', 'Destaque')}) — R$ {float(sugerido.get('preco', 0)):.2f}"
            )
        return sugerido
    return escolhido


# ==============================================================================
# MARCA D'ÁGUA
# ==============================================================================
def campos_marca_dagua(chave) -> dict:
    """
    Como tratar a marca d'água do vídeo de origem. O padrão é procurar e, se houver, apagar. "Eu marco onde
    está" abre a caixa em frações do quadro — pré-preenchida com o que a busca achou, se ela já rodou.
    """
    modo = st.radio("Marca d'água do vídeo original", list(md.MODOS), format_func=md.MODOS.get, horizontal=True,
                    key=f"{chave}_modo",
                    help="A busca compara dezenas de quadros: o contorno da marca é o mesmo em todos, o do "
                         "conteúdo muda. O ffmpeg apaga interpolando a partir da borda — em fundo liso a marca "
                         "some, em fundo detalhado fica um borrão. Use com vídeo seu ou licenciado.")
    if modo != md.MANUAL:
        return {"modo": modo}
    achada = st.session_state.get(f"{chave}_sugestao") or {"x": 0.05, "y": 0.80, "largura": 0.22, "altura": 0.12}
    c1, c2, c3, c4 = st.columns(4)
    x = c1.slider("Da esquerda (%)", 0, 95, int(round(achada["x"] * 100)), key=f"{chave}_x") / 100
    y = c2.slider("Do topo (%)", 0, 95, int(round(achada["y"] * 100)), key=f"{chave}_y") / 100
    largura = c3.slider("Largura (%)", 2, 60, max(2, int(round(achada["largura"] * 100))), key=f"{chave}_w") / 100
    altura = c4.slider("Altura (%)", 2, 50, max(2, int(round(achada["altura"] * 100))), key=f"{chave}_h") / 100
    return {"modo": modo, "x": x, "y": y, "largura": largura, "altura": altura}


def resolver_marca(escolha: dict, clipe, ffmpeg: str, props: dict, chave=None) -> tuple:
    """
    Devolve (caixa em píxeis ou None, frase dizendo o que aconteceu). No automático, o que a busca achou fica
    guardado como sugestão para o modo manual — para ajustar a caixa sem começar do zero.
    """
    tamanho = (props["largura"], props["altura"])
    modo = (escolha or {}).get("modo", md.SEM_MARCA)
    if modo == md.MANUAL:
        regiao = md.regiao_manual(escolha["x"], escolha["y"], escolha["largura"], escolha["altura"], tamanho)
        return regiao, f"Marca d'água apagada na caixa que você marcou ({_caixa(regiao)})."
    if modo == md.AUTOMATICO:
        regiao = md.procurar(clipe, ffmpeg, props)
        if regiao is None:
            return None, "Procurei marca d'água e não achei nenhuma: nada foi apagado."
        if chave:
            st.session_state[f"{chave}_sugestao"] = md.em_fracoes(regiao, tamanho)
        return regiao, (f"Marca d'água encontrada e apagada ({_caixa(regiao)}). Se a caixa não pegou a marca "
                        "inteira, troque para \"Eu marco onde está\": ela já abre na posição encontrada.")
    return None, None


def resolver_marca_de_varios(escolha: dict, clipes, ffmpeg: str, chave=None) -> tuple:
    """
    Vários trechos do mesmo vídeo têm a mesma marca no mesmo lugar. A busca roda trecho a trecho até achar, e
    a caixa achada vale para todos — um trecho curto ou parado demais, onde a busca sozinha não concluiria,
    também sai sem marca.
    """
    for clipe in clipes:
        props = ed.sondar_clipe(clipe, ffmpeg)
        regiao, aviso = resolver_marca(escolha, clipe, ffmpeg, props, chave)
        if regiao is not None or (escolha or {}).get("modo") != md.AUTOMATICO:
            return regiao, aviso
    return None, "Procurei marca d'água em todos os trechos e não achei nenhuma: nada foi apagado."


def _caixa(regiao) -> str:
    x, y, w, h = regiao
    return f"{w}x{h} px a partir de x={x}, y={y}"


# ==============================================================================
# PRÉVIA
# ==============================================================================
def segundo_da_previa(legendas, duracao: float) -> float:
    """No meio do primeiro bloco de legenda (para ela aparecer na prévia) ou a um terço do clipe."""
    if legendas:
        primeiro = legendas[min(1, len(legendas) - 1)]
        return round((primeiro["inicio"] + primeiro["fim"]) / 2, 2)
    return round(duracao / 3, 2)


def mostrar_previa(chave) -> None:
    """Mostra a última prévia gerada (guardada na sessão para sobreviver aos reruns do Streamlit)."""
    guardada = st.session_state.get(f"{chave}_previa")
    if not guardada:
        return
    c1, c2 = st.columns([1.6, 1])
    if guardada.get("original") is not None:
        c1.image(guardada["original"], caption="Quadro original" + (" — em vermelho, o que vai ser apagado"
                                                                     if guardada.get("com_caixa") else ""),
                 use_container_width=True)
    c2.image(guardada["final"], caption=f"Como fica no vídeo, em {guardada['em']:.1f}s", use_container_width=True)
    if guardada.get("aviso_marca"):
        st.caption(guardada["aviso_marca"])
    if guardada.get("golpes"):
        lento = guardada.get("lento")
        detalhe_vel = ""
        if isinstance(lento, tuple) and len(lento) == 2 and isinstance(lento[0], (int, float)):
            detalhe_vel = f" Câmera lenta de {lento[0]:.1f}s a {lento[1]:.1f}s do clipe."
        elif lento:
            detalhe_vel = f" Speed Ramping em {len(lento)} curvas de velocidade."
        st.caption(f"💥 {guardada['golpes']} golpe(s) vão ganhar efeito; a prévia mostra o primeiro.{detalhe_vel}")
    if guardada.get("sugestao"):
        st.caption(f"💡 Receita sugerida pelo ritmo do trecho (palpite): {guardada['sugestao']}.")


def gerar_previa(chave, clipe, ffmpeg: str, props: dict, escolha_marca: dict, em: float, **montagem) -> dict:
    """
    Quadro original (com a caixa da marca desenhada) e o quadro final, lado a lado. `montagem` são os
    mesmos argumentos que vão para editor_reels.previa. Devolve a caixa usada, para não procurar de novo.

    Com efeitos de golpe, a prévia cai no primeiro golpe, que é onde dá para ver o efeito. E sempre mede o
    ritmo do clipe para sugerir uma receita — sem IA, só som e cortes de cena.
    """
    regiao, aviso = resolver_marca(escolha_marca, clipe, ffmpeg, props, chave)
    arte = montagem.get("arte", ef.SEM_ARTE)
    plano = ed.planejar_golpes(clipe, ffmpeg, props, arte)
    if plano["golpes"]:
        em = ef.remapear(plano["golpes"][0]["t"], plano["lento"]) + 0.02
    ritmo = ed.ritmo_do_clipe(clipe, ffmpeg)
    sugestao, motivo = mo.sugerir_receita(ritmo)
    original = md.quadro_do_clipe(clipe, ffmpeg, em)
    if original is not None and regiao:
        original = md.marcar_regiao(original, regiao)
    final = ed.previa(clipe, em=em, marca_dagua=regiao, ffmpeg=ffmpeg, plano=plano, **montagem)
    st.session_state[f"{chave}_previa"] = {
        "original": original, "final": final, "em": em, "aviso_marca": aviso, "com_caixa": bool(regiao),
        "sugestao": f"{ef.RECEITAS[sugestao][0]} — {motivo}", "golpes": len(plano["golpes"]),
        "lento": plano["lento"], "receita": arte.receita}
    return {"regiao": regiao, "aviso": aviso}

