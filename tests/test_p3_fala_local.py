"""Reconhecimento de fala local: o texto de uma fonte, o tempo medido no áudio."""
import numpy as np
import pytest

import fala_local as fl
import legendas as lg
import transcricao_youtube as ty


def w(texto, inicio, fim):
    return {"texto": texto, "inicio": inicio, "fim": fim}


# --- alinhamento ------------------------------------------------------------------------------------

def test_palavras_iguais_herdam_o_tempo_ouvido():
    texto = [w("Senhor", 0.9, 1.4), w("Rengoku,", 1.4, 2.1), w("tá", 2.1, 2.3)]
    ouvidas = [w("Senhor", 0.53, 0.9), w("Rengoku.", 1.13, 1.65), w("tá", 2.02, 2.2)]
    alinhadas, cobertura = fl.alinhar(texto, ouvidas)
    assert cobertura == 1.0
    assert [a["inicio"] for a in alinhadas] == [0.53, 1.13, 2.02]
    assert [a["texto"] for a in alinhadas] == ["Senhor", "Rengoku,", "tá"]      # o texto é o da fonte, não o ouvido


def test_palavra_trocada_herda_o_tempo_da_ouvida_no_mesmo_lugar():
    """O whisper ouviu "Leng" onde a legenda diz "Ele": o tempo de "Leng" vale para "Ele"."""
    texto = [w("para.", 25.0, 26.0), w("Ele", 28.9, 29.3), w("não", 29.3, 29.6), w("vai", 29.6, 29.9)]
    ouvidas = [w("para.", 25.5, 25.9), w("Leng,", 29.13, 29.49), w("não", 29.6, 29.7), w("vai", 29.7, 29.9)]
    alinhadas, _ = fl.alinhar(texto, ouvidas)
    assert alinhadas[1]["inicio"] == 29.13


def test_palavra_nao_ouvida_fica_colada_na_vizinha_e_nao_atravessa_o_silencio():
    """O whisper não ouviu "Mamãe": ela ia parar 8 s antes de ser dita, espalhada pelo silêncio."""
    texto = [w("tristeza.", 32.3, 33.0), w("Mamãe,", 40.2, 41.0), w("acha", 41.0, 41.3), w("que", 41.3, 41.5)]
    ouvidas = [w("tristeza.", 32.27, 33.01), w("Acha", 41.09, 41.4), w("que", 41.4, 41.6)]
    alinhadas, _ = fl.alinhar(texto, ouvidas)
    mamae = alinhadas[1]
    assert 40.3 <= mamae["inicio"] < mamae["fim"] <= 41.09


def test_palavra_nao_ouvida_no_meio_da_frase_cola_na_anterior():
    texto = [w("eu", 0.0, 0.2), w("tenho", 0.2, 0.5), w("certeza", 0.5, 1.0), w("absoluta", 3.0, 3.5)]
    ouvidas = [w("eu", 0.1, 0.2), w("tenho", 0.2, 0.4), w("absoluta", 3.1, 3.5)]
    alinhadas, _ = fl.alinhar(texto, ouvidas)
    assert alinhadas[2]["inicio"] == pytest.approx(0.4)


def test_trecho_trocado_nao_se_espalha_pelo_silencio():
    """'superestimando' ganhou 4,3 s porque o trecho atravessava 3 s de silêncio."""
    intervalos = [(21.7, 22.4), (25.7, 26.3)]
    partes = fl._espalhar([14, 1, 1], intervalos)
    assert all(fim - ini < 1.5 for ini, fim in partes)
    assert partes[0][0] == pytest.approx(21.7) and partes[-1][1] == pytest.approx(26.3)


def test_mesma_contagem_nos_dois_lados_pareia_uma_para_uma():
    texto = [w("me", 0.0, 0.2), w("superestimando.", 0.2, 5.0), w("R", 5.0, 5.5), w("90.", 5.5, 6.0)]
    ouvidas = [w("me", 0.1, 0.2), w("superestido.", 0.3, 1.1), w("Rado", 4.0, 4.4), w("90.", 4.4, 4.8)]
    alinhadas, _ = fl.alinhar(texto, ouvidas)
    assert (alinhadas[1]["inicio"], alinhadas[1]["fim"]) == (0.3, 1.1)


def test_texto_e_audio_que_nao_batem_ficam_como_vieram():
    """Outra língua, outra cena: sem par suficiente, mexer no tempo seria inventar."""
    texto = [w("uma", 0.0, 0.5), w("frase", 0.5, 1.0), w("qualquer", 1.0, 1.5)]
    ouvidas = [w("totally", 0.2, 0.6), w("different", 0.6, 1.2)]
    alinhadas, cobertura = fl.alinhar(texto, ouvidas)
    assert cobertura < fl.COBERTURA_MINIMA and alinhadas == texto


def test_japones_alinha_letra_a_letra():
    texto = [w("ようやく見せるか、", 0.6, 3.0), w("お前の真価を。", 3.0, 6.0)]
    ouvidas = [w("ようやく", 0.11, 0.9), w("見せるか", 0.9, 1.89), w("お前の", 2.75, 3.6), w("万回を", 3.6, 5.43)]
    alinhadas, cobertura = fl.alinhar(texto, ouvidas)
    assert cobertura > 0.6
    assert alinhadas[0]["inicio"] == pytest.approx(0.11) and alinhadas[1]["inicio"] == pytest.approx(2.75, abs=0.05)


def test_sem_nada_ouvido_nada_muda():
    texto = [w("oi", 0.0, 0.5)]
    assert fl.alinhar(texto, []) == (texto, 0.0)


def test_ouvidas_de_um_trecho_ficam_relativas_ao_comeco_dele():
    palavras = [w("antes", 9.0, 9.5), w("dentro", 10.2, 10.6), w("depois", 20.5, 21.0)]
    assert fl.ouvidas_no_trecho(palavras, 10.0, 20.0) == [w("dentro", 0.2, 0.6)]


# --- a legenda usando o tempo ouvido --------------------------------------------------------------------

def test_a_legenda_usa_o_tempo_ouvido_e_diz_a_sincronia():
    falas = [{"texto": "fluxo do tempo nunca para.", "start": 25.0, "dur": 4.0}]
    ouvidas = [w("fluxo", 0.5, 0.9), w("do", 0.9, 1.0), w("tempo", 1.0, 1.3), w("nunca", 1.3, 1.6), w("para.", 1.6, 2.0)]
    montadas = lg.montar_legendas(falas, 25.0, 30.0, ouvidas=ouvidas)
    assert montadas["sincronia"] == 1.0
    assert montadas["blocos"][0]["inicio"] == pytest.approx(0.5)          # estimado seria 0,0


def test_sem_audio_a_sincronia_e_nenhuma():
    falas = [{"texto": "uma fala.", "start": 0.0, "dur": 2.0}]
    assert lg.montar_legendas(falas, 0.0, 5.0)["sincronia"] is None


def test_japones_vira_uma_unidade_por_oracao():
    """Sem espaço, a legenda japonesa inteira de um pedaço era uma 'palavra' de 13 s."""
    palavras = lg.palavras_com_tempo([{"texto": "ようやく見せるか、お前の真価を。お前が得る力の全て。", "start": 0.0, "dur": 9.0}])
    assert [p["texto"] for p in palavras] == ["ようやく見せるか、", "お前の真価を。", "お前が得る力の全て。"]


def test_pontuacao_japonesa_fecha_frase():
    assert lg.fecha_frase("何！？") and lg.fecha_frase("お前の真価を。")


# --- vídeo sem legenda, transcrito no computador --------------------------------------------------------

def test_transcricao_local_sai_no_formato_da_analise(monkeypatch):
    monkeypatch.setattr(fl, "audio_do_video", lambda url, ffmpeg: np.zeros(16000 * 70, np.float32))
    monkeypatch.setattr(fl, "reconhecer_audio", lambda audio, idioma=None, progresso=None: {
        "falas": [{"texto": f"fala {i}.", "start": i * 5.0, "dur": 3.0} for i in range(14)],
        "palavras": [w("fala", 0.1, 0.4)], "idioma": "pt"})
    dados = fl.transcrever_video("abc", "https://youtu.be/abc", "ffmpeg")
    assert dados["codigo_idioma"] == "pt" and "reconhecido no computador" in dados["idioma"]
    assert dados["blocos"] and dados["falas"][0]["texto"] == "fala 0." and dados["palavras_ouvidas"]


def test_video_sem_fala_nenhuma_explica(monkeypatch):
    monkeypatch.setattr(fl, "audio_do_video", lambda url, ffmpeg: np.zeros(16000, np.float32))
    monkeypatch.setattr(fl, "reconhecer_audio", lambda audio, idioma=None, progresso=None:
                        {"falas": [], "palavras": [], "idioma": "pt"})
    with pytest.raises(ty.SemTranscricao, match="não ouviu fala"):
        fl.transcrever_video("abc", "https://youtu.be/abc", "ffmpeg")


def test_a_legenda_do_youtube_e_a_local_montam_o_mesmo_dicionario():
    falas = [{"texto": "uma fala.", "start": 0.0, "dur": 2.0}]
    do_youtube = ty.transcricao_de_falas("abc", falas, "Portuguese", "pt")
    local = ty.transcricao_de_falas("abc", falas, "Português (reconhecido no computador)", "pt", [w("uma", 0.1, 0.3)])
    assert set(local) - set(do_youtube) == {"palavras_ouvidas"}


def test_transcricao_local_passa_prompt_inicial(monkeypatch):
    capturado = {}

    def mock_reconhecer(audio, idioma=None, progresso=None, prompt_inicial=None):
        capturado["prompt"] = prompt_inicial
        return {"falas": [{"texto": "Rengoku venceu.", "start": 0.0, "dur": 2.0}],
                "palavras": [w("Rengoku", 0.1, 0.9)], "idioma": "pt"}

    monkeypatch.setattr(fl, "audio_do_video", lambda url, ffmpeg: np.zeros(16000, np.float32))
    monkeypatch.setattr(fl, "reconhecer_audio", mock_reconhecer)
    dados = fl.transcrever_video("abc", "https://youtu.be/abc", "ffmpeg", prompt_inicial="Rengoku, Akaza")
    assert capturado.get("prompt") == "Rengoku, Akaza"
    assert dados["falas"][0]["texto"] == "Rengoku venceu."


def test_fala_local_disponivel_retorna_bool():
    assert isinstance(fl.disponivel(), bool)
    assert fl.disponivel() is True

