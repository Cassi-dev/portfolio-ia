from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parents[1]


def abrir(caminho, timeout=120):
    at = AppTest.from_file(str(RAIZ / caminho), default_timeout=timeout)
    at.run()
    return at


def clicar(at, trecho_do_rotulo):
    botao = next(b for b in at.button if trecho_do_rotulo in b.label)
    botao.click().run()


def campo(at, trecho_do_rotulo):
    return next(c for c in at.text_input if trecho_do_rotulo in c.label)


def textos(elementos):
    return " ".join(str(e.value) for e in elementos)


def test_p5_abre_e_avisa_modo_offline_para_pergunta_conhecida():
    at = abrir("projeto_05_gerador_sql/app_sql.py")
    assert not at.exception
    clicar(at, "Gerar SQL")
    assert not at.exception
    aviso = textos(at.warning)
    assert "Modo degradado" in aviso and "NÃO responde" not in aviso
    assert len(at.dataframe) == 1


def test_p5_avisa_quando_pergunta_offline_nao_e_reconhecida():
    at = abrir("projeto_05_gerador_sql/app_sql.py")
    campo(at, "Digite sua dúvida").set_value("Qual o ticket médio por estado?").run()
    clicar(at, "Gerar SQL")
    assert "NÃO responde" in textos(at.warning)


P3 = "projeto_03_resumidor_youtube/app_youtube.py"


def modo(at, trecho):
    """Troca o modo do app do P3 pelo texto da opção (a ordem das opções não importa)."""
    radio = at.radio[0]
    radio.set_value(next(o for o in radio.options if trecho in o)).run()


def analisar_video_de_exemplo(monkeypatch, blocos_video, falas=None, idioma="Portuguese", codigo_idioma=None):
    import transcricao_youtube

    transcricao = {
        "video_id": "M7lc1UVf-VE", "idioma": idioma, "duracao_segundos": 500.0,
        "duracao_formatada": "08:20", "total_blocos": len(blocos_video), "blocos": blocos_video,
    }
    if falas is not None:
        transcricao["falas"] = falas
    if codigo_idioma:
        transcricao["codigo_idioma"] = codigo_idioma
    monkeypatch.setattr(transcricao_youtube, "obter_transcricao_formatada", lambda video_id: transcricao)
    monkeypatch.setattr(transcricao_youtube, "obter_metadados_video", lambda video_id: {"titulo": "Aula de IA", "canal": "Canal X"})
    at = abrir(P3)
    modo(at, "Analisar Vídeo")
    clicar(at, "Analisar Vídeo")
    return at


def test_p3_abre_no_modo_de_qualquer_assunto_e_o_reels_da_tacto_continua_disponivel():
    at = abrir(P3)
    assert not at.exception
    assert at.radio[0].value.startswith("🎞️") and len(at.radio[0].options) == 4
    assert "Criar roteiro" in [b.label for b in at.button][0]
    modo(at, "TACTO")
    assert not at.exception and any("Reels" in b.label for b in at.button)


def test_p3_modo_livre_sem_chave_avisa_e_deixa_editar_o_roteiro_e_o_video_sai_mudo(tmp_path, monkeypatch):
    import renderizador_generico
    import ui_reels_livre

    monkeypatch.setattr(renderizador_generico, "PASTA_SAIDA", tmp_path)
    at = abrir(P3, timeout=240)
    clicar(at, "Criar roteiro")
    assert not at.exception
    assert "Modo degradado" in textos(at.warning)
    layouts = [s.value for s in at.selectbox if s.label == "Layout"]
    assert len(layouts) >= 2 and layouts[0] == "titulo"

    next(s for s in at.selectbox if s.label == "Voz da locução").select(ui_reels_livre.SEM_VOZ).run()
    clicar(at, "Renderizar vídeo")
    assert not at.exception and not at.error
    assert len(list(tmp_path.glob("*.mp4"))) == 1
    assert any("Vídeo pronto" in str(s.value) for s in at.success)


def test_p3_modo_livre_bloqueia_a_renderizacao_quando_a_cena_editada_esta_incompleta():
    at = abrir(P3, timeout=240)
    clicar(at, "Criar roteiro")
    next(s for s in at.selectbox if s.label == "Layout").select("lista").run()          # lista sem itens
    assert not at.exception
    assert "a lista precisa de 2 a 4 itens" in textos(at.error)
    assert next(b for b in at.button if "Renderizar" in b.label).disabled


def test_p3_modo_livre_pede_contexto():
    at = abrir(P3)
    next(t for t in at.text_area if t.label == "Contexto do vídeo").set_value("  ").run()
    clicar(at, "Criar roteiro")
    assert "escreva ou cole o contexto" in textos(at.error)


def test_p3_analise_de_video_sem_ia_mostra_abas_e_aviso(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video)

    assert not at.exception
    assert "Modo degradado" in textos(at.warning)
    assert [t.label for t in at.tabs] == ["📝 Resumo", "📌 Tópicos", "📄 Conteúdo em TXT", "🧠 Quiz", "✂️ Cortes",
                                          "🎬 Roteiro", "✨ Edição"]
    assert "Quiz indisponível" in textos(at.info)


@pytest.fixture(autouse=True)
def _sem_whisper_local_por_padrao(monkeypatch):
    """
    O padrão da legenda depende de haver Whisper local NESTE computador: com ele e sem chave de API, o padrão é
    "Whisper local" (custo zero e o tempo das palavras já medido no áudio); sem ele, "como está". Os testes de
    tela partem de "sem Whisper" para não variarem de máquina em máquina; os que querem o contrário ligam
    explicitamente com monkeypatch.
    """
    import fala_local
    monkeypatch.setattr(fala_local, "disponivel", lambda: False)


def radio_de_legenda(at, prefixo):
    return next(r for r in at.radio if r.label == "Legenda" and r.key.startswith(prefixo))


def campo_por_rotulo(at, trecho):
    return next(c for c in list(at.text_input) + list(at.text_area) if trecho in c.label)


def test_p3_aba_roteiro_monta_o_video_pronto_em_tela_cheia_com_os_textos_preenchidos(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala do vídeo", "start": 0.0, "dur": 2.0}])
    assert not at.exception
    assert any("Montar o vídeo pronto" in b.label for b in at.button)
    assert next(s for s in at.selectbox if "Qual corte" in s.label).value == 0
    assert next(s for s in at.selectbox if s.label == "Enquadramento").value == "inteiro"
    assert radio_de_legenda(at, "vp_").value.startswith("Legenda do vídeo como está")      # sem chave: custo zero

    # Só imagem e legenda por padrão: sem etiqueta, sem título, sem caixa atrás e sem barra.
    assert campo_por_rotulo(at, "Título sobre o clipe").value == ""
    assert campo_por_rotulo(at, "Etiqueta").value == ""
    assert next(c for c in at.checkbox if "Caixa atrás da legenda" in c.label).value is False
    assert next(c for c in at.checkbox if "Barra de progresso" in c.label).value is False

    # Sem chave, título e descrição saem do próprio vídeo; a abertura não vem por padrão.
    assert campo_por_rotulo(at, "Título da postagem").value == "Aula de IA"
    assert campo_por_rotulo(at, "Descrição do vídeo").value
    assert next(c for c in at.checkbox if "cartão de abertura" in c.label).value is False
    assert next(c for c in at.checkbox if "cartão final" in c.label).value is False
    assert next(m for m in at.multiselect if "Idiomas" in m.label).value == ["pt"]


def test_p3_conta_mencionada_entra_na_chamada_final_mesmo_sem_ia(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video)
    next(c for c in at.checkbox if "cartão final" in c.label).set_value(True).run()
    campo_por_rotulo(at, "Conta a mencionar").set_value("@focoti").run()
    clicar(at, "Escrever com IA")
    assert not at.exception
    assert campo_por_rotulo(at, "Frase do cartão final").value == "Siga @focoti para mais"
    assert campo_por_rotulo(at, "Texto do botão").value == "Seguir @focoti"


def test_p3_roteiro_degradado_nao_vira_abertura_do_video(monkeypatch, blocos_video):
    """Sem chave, o roteiro é o modelo da TACTO: ele não pode ser queimado num vídeo sobre outro assunto."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video)
    next(c for c in at.checkbox if "cartão de abertura" in c.label).set_value(True).run()
    assert not at.exception
    assert "não é usado aqui" in textos(at.warning)

    abertura = campo_por_rotulo(at, "Título da abertura").value + campo_por_rotulo(at, "Fala da abertura").value
    assert abertura
    for palavra in ("iFood", "CAC Zero", "TACTO", "restaurante"):
        assert palavra not in abertura
    assert abertura.startswith("Corte #1")


def test_p3_aba_edicao_planeja_trechos_e_deixa_ajustar_antes_de_montar(monkeypatch, blocos_video):
    """A escolha de qual pedaço entra é do usuário: o plano vem editável, e montar é um segundo clique."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video,
                                   falas=[{"texto": f"fala {i}.", "start": i * 20.0, "dur": 3.0} for i in range(20)])
    assert not at.exception
    assert any("Planejar a edição" in b.label for b in at.button)
    assert not any("Montar a edição" in b.label for b in at.button)       # só depois de planejar

    clicar(at, "Planejar a edição")
    assert not at.exception
    assert "Sem leitura de conteúdo" in textos(at.warning)                # sem chave, é mecânico e avisa
    assert any("Montar a edição" in b.label for b in at.button)

    comecos = [c for c in at.number_input if c.key.startswith("ed_ini_")]   # só os da aba de Edição
    assert len(comecos) >= 2 and comecos[0].value < comecos[1].value      # trechos em ordem, ajustáveis
    assert all(c.value for c in at.checkbox if c.label.startswith("Trecho"))


def test_p3_o_corte_do_video_pronto_tambem_tem_ajuste_fino_de_tempo(monkeypatch, blocos_video):
    """Os tempos vêm encaixados na frase, mas quem assiste é que sabe se faltaram dois segundos."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    comeco = next(c for c in at.number_input if c.key.startswith("vp_ini_"))
    fim = next(c for c in at.number_input if c.key.startswith("vp_fim_"))
    assert fim.value > comeco.value

    fim.set_value(comeco.value + 7).run()
    assert not at.exception
    assert "7s" in " ".join(str(m.value) for m in at.caption)


def test_p3_edicao_sem_nenhum_trecho_marcado_bloqueia_a_montagem(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video,
                                   falas=[{"texto": f"fala {i}.", "start": i * 20.0, "dur": 3.0} for i in range(20)])
    clicar(at, "Planejar a edição")
    for caixa in [c for c in at.checkbox if c.label.startswith("Trecho")]:
        caixa.set_value(False)
    at.run()
    assert "mantenha ao menos um trecho" in textos(at.warning)
    assert next(b for b in at.button if "Montar a edição" in b.label).disabled


def test_p3_analise_antiga_sem_as_falas_soltas_nao_oferece_legenda_queimada(monkeypatch, blocos_video):
    """Quem já tinha uma análise aberta na sessão não pode ver a tela quebrar."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video)
    assert not at.exception
    legenda = radio_de_legenda(at, "vp_")
    assert legenda.value.startswith("Não gerar") and legenda.disabled


def test_p3_video_estrangeiro_ganha_legenda_em_portugues_e_avisa_sem_chave(monkeypatch, blocos_video):
    """Fala em inglês: a legenda sai traduzida para português; sem chave, a tela avisa que não dá."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, idioma="English (auto-generated)", codigo_idioma="en",
                                   falas=[{"texto": "a speech.", "start": 0.0, "dur": 3.0}])
    legenda = radio_de_legenda(at, "vp_")
    assert legenda.value.startswith("Traduzida para português") and not legenda.disabled
    assert any(o.startswith("No idioma da fala") for o in legenda.options)
    assert "não dá para traduzir" in textos(at.warning)
    legenda.set_value(next(o for o in legenda.options if o.startswith("Não gerar"))).run()
    assert not at.exception
    assert next(s for s in at.selectbox if s.label == "Estilo da legenda" and s.key.startswith("vp_")).disabled


def test_p3_fala_em_japones_nao_oferece_legenda_no_original(monkeypatch, blocos_video):
    """A fonte do vídeo não desenha japonês: 'no idioma da fala' sairia uma fileira de quadradinhos."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, idioma="Japanese", codigo_idioma="ja",
                                   falas=[{"texto": "この力は、お前からみんなを守るために", "start": 0.0, "dur": 3.0}])
    legenda = radio_de_legenda(at, "vp_")
    assert not any(o.startswith("No idioma da fala") for o in legenda.options)
    assert legenda.value.startswith("Traduzida para português")


def test_p3_receita_de_luta_troca_os_controles_pela_descricao(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    receita = next(s for s in at.selectbox if s.label == "Receita de edição" and s.key.startswith("vp_"))
    assert receita.value == "personalizada"
    receita.set_value("luta").run()
    assert not at.exception
    assert not any(s.label == "Filtro de cor" and s.key.startswith("vp_") for s in at.selectbox)
    lenta = next(c for c in at.checkbox if c.label.startswith("Câmera lenta") and c.key.startswith("vp_"))
    assert lenta.value is True
    assert "quadro invertido" in " ".join(str(c.value) for c in at.caption)


def test_p3_video_pronto_tem_direcao_de_arte_e_procura_marca_por_padrao(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    assert next(s for s in at.selectbox if s.label == "Filtro de cor" and s.key.startswith("vp_")).value == "original"
    assert next(s for s in at.selectbox if s.label == "Zoom" and s.key.startswith("vp_")).value == "nenhum"
    marca = next(r for r in at.radio if r.label.startswith("Marca d'água") and r.key.startswith("vp_"))
    assert marca.value == "auto"
    assert any("Prévia" in b.label for b in at.button)

    marca.set_value("manual").run()                              # a caixa manual abre com quatro controles
    assert not at.exception
    assert len([s for s in at.slider if s.key.startswith("vp_md_")]) == 4


def test_p3_edicao_oferece_transicao_entre_trechos(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video,
                                   falas=[{"texto": f"fala {i}.", "start": i * 20.0, "dur": 3.0} for i in range(20)])
    clicar(at, "Planejar a edição")
    transicao = next(s for s in at.selectbox if s.label == "Transição entre trechos")
    assert transicao.value == "corte"
    transicao.set_value("fadewhite").run()
    assert not at.exception


def test_p3_editor_local_abre_e_pede_o_video():
    at = abrir(P3)
    modo(at, "computador")
    assert not at.exception
    assert "Envie um vídeo" in textos(at.info)
    origem = next(r for r in at.radio if r.label == "De onde vem o vídeo")
    origem.set_value(next(o for o in origem.options if "Link" in o)).run()
    assert not at.exception and any("Ler o link" in b.label for b in at.button)


def test_p3_manter_a_legenda_da_imagem_desliga_a_faixa_de_cinema(monkeypatch, blocos_video):
    """A faixa de cinema corta a parte de baixo do vídeo — justamente onde mora a legenda queimada."""
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    next(s for s in at.selectbox if s.label == "Receita de edição" and s.key.startswith("vp_")).set_value("aura").run()
    legenda = radio_de_legenda(at, "vp_")
    legenda.set_value(next(o for o in legenda.options if o.startswith("Não gerar"))).run()
    assert not at.exception
    assert "Faixa de cinema desligada" in " ".join(str(c.value) for c in at.caption)


def test_p3_video_com_legenda_desativada_explica_e_leva_ao_editor(monkeypatch):
    import transcricao_youtube

    def sem_legenda(video_id):
        raise transcricao_youtube.SemTranscricao("Este vídeo está com a legenda desativada no YouTube.", True)
    monkeypatch.setattr(transcricao_youtube, "obter_transcricao_formatada", sem_legenda)
    at = abrir(P3)
    modo(at, "Analisar Vídeo")
    clicar(at, "Analisar Vídeo")
    assert "legenda desativada" in textos(at.error)
    clicar(at, "Editar este vídeo no editor")
    assert not at.exception
    assert at.radio[0].value.startswith("📁")
    assert next(t for t in at.text_input if t.label == "Link do vídeo").value.startswith("https://www.youtube.com")


def test_p3_sem_chave_e_com_whisper_local_o_padrao_da_legenda_e_o_whisper_local(monkeypatch, blocos_video):
    """Decisão de produto (04/10): sem chave de API, havendo Whisper local, ele é o padrão (custo zero)."""
    import fala_local
    monkeypatch.setattr(fala_local, "disponivel", lambda: True)
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    assert not at.exception
    assert radio_de_legenda(at, "vp_").value.startswith("Transcrever áudio na CPU")


def test_p3_sincronizar_pelo_audio_vem_ligado_quando_o_reconhecimento_existe(monkeypatch, blocos_video):
    import fala_local
    monkeypatch.setattr(fala_local, "disponivel", lambda: True)
    at = analisar_video_de_exemplo(monkeypatch, blocos_video, falas=[{"texto": "uma fala.", "start": 0.0, "dur": 3.0}])
    # Com Whisper local disponível e sem chave, o padrão da legenda é "Whisper local": o tempo das palavras já
    # vem medido do áudio e não há o que sincronizar. A sincronização é do modo "como está": escolhe-o.
    radio = radio_de_legenda(at, "vp_")
    radio.set_value(next(o for o in radio.options if o.startswith("Legenda do vídeo como está"))).run()
    assert not at.exception
    sinc = next(c for c in at.checkbox if c.label.startswith("⏱️ Sincronizar") and c.key.startswith("vp_"))
    assert sinc.value is True


def test_p3_video_sem_legenda_transcrito_no_computador_segue_para_a_analise(monkeypatch):
    import fala_local
    import transcricao_youtube

    def sem_legenda(video_id):
        raise transcricao_youtube.SemTranscricao("Este vídeo está com a legenda desativada no YouTube.", True)
    falas = [{"texto": f"fala número {i}.", "start": i * 5.0, "dur": 3.0} for i in range(20)]
    transcrita = transcricao_youtube.transcricao_de_falas(
        "M7lc1UVf-VE", falas, "Português (reconhecido no computador)", "pt",
        [{"texto": "fala", "inicio": 0.1, "fim": 0.4}])
    monkeypatch.setattr(transcricao_youtube, "obter_transcricao_formatada", sem_legenda)
    monkeypatch.setattr(transcricao_youtube, "obter_metadados_video", lambda v: {"titulo": "Vídeo sem legenda", "canal": ""})
    monkeypatch.setattr(fala_local, "disponivel", lambda: True)
    monkeypatch.setattr(fala_local, "transcrever_video", lambda video_id, url, ffmpeg, progresso=None: transcrita)
    at = abrir(P3)
    modo(at, "Analisar Vídeo")
    clicar(at, "Analisar Vídeo")
    clicar(at, "Transcrever no computador")
    assert not at.exception
    assert [t.label for t in at.tabs][:1] == ["📝 Resumo"]
    # O aviso de que o tempo já é o medido no áudio aparece no modo "como está" (no modo "Whisper local", que é
    # o padrão quando ele existe, a legenda inteira já é do reconhecimento e o aviso não faz sentido).
    radio = radio_de_legenda(at, "vp_")
    radio.set_value(next(o for o in radio.options if o.startswith("Legenda do vídeo como está"))).run()
    assert not at.exception
    assert "já é o medido no áudio" in " ".join(str(c.value) for c in at.caption)


def test_p3_resumo_do_video_analisado_pode_virar_contexto_de_um_novo_video(monkeypatch, blocos_video):
    at = analisar_video_de_exemplo(monkeypatch, blocos_video)
    modo(at, "qualquer assunto")
    origem = next(r for r in at.radio if r.label == "Origem do contexto")
    assert any("YouTube" in o for o in origem.options)
    origem.set_value(next(o for o in origem.options if "YouTube" in o)).run()
    assert not at.exception
    assert "Aula de IA" in next(t for t in at.text_area if t.label == "Contexto do vídeo").value


def test_p3_url_invalida_mostra_erro_em_vez_de_ficar_calado():
    at = abrir(P3)
    modo(at, "Analisar Vídeo")
    campo(at, "Cole a URL").set_value("https://www.youtube.com/channel/UCabcdefghijklmnopqrstu").run()
    clicar(at, "Analisar Vídeo")
    assert "URL inválida" in textos(at.error)


def test_p4_analisa_os_curriculos_ficticios_e_mostra_ranking_reprovados_e_aviso():
    at = abrir("projeto_04_triador_curriculos/app_triador.py", timeout=240)
    assert not at.exception
    obrig = next(t for t in at.text_area if "obrigatórios" in t.label)
    assert obrig.value.splitlines() == ["Python", "SQL", "Git", "APIs REST"]        # extraídos da vaga de exemplo

    clicar(at, "Analisar currículos")
    assert not at.exception
    assert "Modo degradado" in textos(at.warning)
    metricas = {m.label: m.value for m in at.metric}
    # 24 currículos de nota 1 a 3 passam no filtro; os 16 de nota 0 (júnior recheado, outra stack, sem Git, marketing) não
    assert (metricas["Analisados"], metricas["Passaram no filtro"], metricas["Reprovados nos requisitos"]) == ("40", "24", "16")
    assert len(at.dataframe) == 1


def test_p4_sem_requisitos_nao_pontua_e_avisa():
    at = abrir("projeto_04_triador_curriculos/app_triador.py", timeout=240)
    next(t for t in at.text_area if "obrigatórios" in t.label).set_value("")
    next(t for t in at.text_area if "desejáveis" in t.label).set_value("").run()
    clicar(at, "Analisar currículos")
    assert "ao menos um requisito" in textos(at.error)


BANCO_P1 = RAIZ / "projeto_01_chatbot_rag" / "banco_vetorial"


precisa_do_indice = pytest.mark.skipif(not BANCO_P1.exists(), reason="rode projeto_01_chatbot_rag/1_processar_documentos.py antes")


def conteudo_do_chat(at):
    return " ".join(m.markdown[0].value for m in at.chat_message if m.markdown)


@precisa_do_indice
def test_p1_padrao_com_reranker_responde_com_fonte_e_secao_recusa_o_que_nao_sabe_e_tem_feedback(monkeypatch):
    monkeypatch.setenv("RAG_LOG", "0")
    at = abrir("projeto_01_chatbot_rag/app.py", timeout=300)
    assert not at.exception
    assert next(s for s in at.selectbox if "Modo de busca" in s.label).value == "vetorial_rerank"

    at.chat_input[0].set_value("Quantos dias tenho para pedir reembolso integral?").run()
    assert not at.exception
    conteudo = conteudo_do_chat(at)
    assert "politica_reembolso_e_ti.txt" in conteudo and "reembolso e cancelamento" in conteudo      # arquivo e seção
    assert any(b.label == "👍" for b in at.button) and any(b.label == "👎" for b in at.button)

    at.chat_input[0].set_value("Qual é a melhor receita de pudim de leite condensado?").run()
    assert "Modo Não Sei" in textos(at.warning)


@precisa_do_indice
def test_p1_modo_so_vetorial_e_filtro_por_documento(monkeypatch):
    monkeypatch.setenv("RAG_LOG", "0")
    at = abrir("projeto_01_chatbot_rag/app.py", timeout=300)
    next(s for s in at.selectbox if "Modo de busca" in s.label).select("vetorial").run()
    next(m for m in at.multiselect if "Buscar somente em" in m.label).select("exercicio_1_roteiro_rag.md").run()

    at.chat_input[0].set_value("Quantos dias tenho para pedir reembolso integral?").run()
    assert not at.exception
    assert "politica_reembolso_e_ti.txt" not in conteudo_do_chat(at).replace("exercicio_1_roteiro_rag.md", "")   # o filtro impede a fonte certa


@precisa_do_indice
def test_p1_lista_os_documentos_indexados():
    at = abrir("projeto_01_chatbot_rag/app.py", timeout=300)
    assert not at.exception
    tabela = next(d for d in at.dataframe if "Arquivo" in d.value.columns)
    assert {"politica_reembolso_e_ti.txt", "exercicio_1_roteiro_rag.md"} <= set(tabela.value["Arquivo"])


@pytest.mark.network
def test_p2_abre_e_avisa_que_esta_no_lexico():
    at = abrir("projeto_02_analisador_acoes/app_mercado.py", timeout=180)
    assert not at.exception
    assert "Modo degradado" in textos(at.warning)


RADAR = "projeto_02_analisador_acoes/app_radar.py"


def test_p2_radar_sem_cadastro_explica_em_vez_de_quebrar():
    at = abrir(RADAR)
    assert not at.exception
    assert "--criar-exemplo" in textos(at.error)


def test_p2_radar_revisa_exclui_gera_e_aprova(tmp_path, monkeypatch):
    """A tela inteira: marcar, desmarcar o ruído, gerar o HTML e aprovar."""
    import monitorados
    import relatorio
    from base_eventos import BaseEventos
    from monitorados import Alvo, Cadastro, Cliente

    cadastro = tmp_path / "m.json"
    banco = tmp_path / "radar.db"
    cliente = Cliente(id="bar", nome="Bar do Zé", perfil="negocio",
                      alvos=[Alvo(id="bar", nome="Bar do Zé", papel="proprio", termos=["Bar do Zé"])])
    monitorados.salvar(Cadastro(clientes=[cliente]), cadastro)
    with BaseEventos(banco) as b:
        ciclo = b.abrir_ciclo("bar")
        b.registrar_eventos("bar", "bar", "noticia", [
            {"titulo": "Bar do Zé ganha prêmio de melhor petisco da cidade", "data": "2026-09-18", "fonte": "Jornal"},
            {"titulo": "Manchete irrelevante que o revisor vai tirar do relatório", "data": "2026-09-17", "fonte": "X"},
        ], ciclo)
        b.fechar_ciclo(ciclo, 2, 2, 0)
    monkeypatch.setattr(relatorio, "PASTA_RELATORIOS", tmp_path / "saida")

    at = abrir(RADAR, timeout=240)
    campo(at, "Cadastro").set_value(str(cadastro))
    campo(at, "Banco do monitor").set_value(str(banco)).run()
    assert not at.exception
    assert "2 item(ns)" in " ".join(str(m.value) for m in at.markdown)

    next(c for c in at.checkbox if "irrelevante" in c.label).set_value(False).run()
    clicar(at, "Gerar Radar")
    assert not at.exception
    assert "gerado em" in textos(at.success)

    with BaseEventos(banco) as b:
        assert b.relatorios("bar")[0]["itens"] == 1
        assert [e["titulo"] for e in b.eventos("bar")] == ["Bar do Zé ganha prêmio de melhor petisco da cidade"]

    clicar(at, "Aprovar (pronto para enviar)")
    assert not at.exception
    with BaseEventos(banco) as b:
        assert b.relatorios("bar")[0]["estado"] == "aprovado"
