"""Vídeo que não vem da análise do YouTube: arquivo do computador, link de outra rede, .srt e transcrição."""
import json
import subprocess

import pytest

import editor_reels as ed
import fonte_local as fl
import legendas as lg
import transcricao_audio as ta
import ui_ferramentas as uf
from core.degradacao import MOTIVO_SEM_CHAVE
from core.midia import localizar_ffmpeg
from ui_video_pronto import arquivo_do_corte


def _video(tmp_path, segundos=4):
    saida = tmp_path / "origem.mp4"
    subprocess.run([localizar_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100", "-t", str(segundos),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(saida)], check=True)
    return saida


# --- arquivo enviado ---------------------------------------------------------------------------------

def test_o_envio_e_guardado_com_nome_legivel_e_sem_duplicar(tmp_path):
    primeiro = fl.salvar_envio("Minha Gravação.MP4", b"conteudo", tmp_path)
    segundo = fl.salvar_envio("Minha Gravação.MP4", b"conteudo", tmp_path)
    assert primeiro == segundo and primeiro.suffix == ".mp4" and primeiro.name.startswith("minha_gravacao_")
    assert len(list(tmp_path.iterdir())) == 1


def test_mesmo_nome_com_conteudo_diferente_nao_sobrescreve(tmp_path):
    assert fl.salvar_envio("v.mp4", b"a", tmp_path) != fl.salvar_envio("v.mp4", b"b", tmp_path)


def test_formato_que_nao_e_video_e_recusado(tmp_path):
    with pytest.raises(fl.FalhaNaFonte, match="não suportado"):
        fl.salvar_envio("planilha.xlsx", b"x", tmp_path)


def test_recorta_o_trecho_do_arquivo_no_ponto_exato(tmp_path):
    ffmpeg = localizar_ffmpeg()
    clipe = fl.cortar_arquivo(_video(tmp_path), 1.0, 3.0, tmp_path / "t.mp4", ffmpeg)
    props = ed.sondar_clipe(clipe, ffmpeg)
    assert props["duracao"] == pytest.approx(2.0, abs=0.1) and props["tem_audio"]


def test_intervalo_invertido_e_recusado(tmp_path):
    with pytest.raises(fl.FalhaNaFonte, match="intervalo"):
        fl.cortar_arquivo("x.mp4", 3, 1, tmp_path / "t.mp4", "ffmpeg")


def test_o_trecho_do_arquivo_e_reaproveitado(tmp_path, monkeypatch):
    ffmpeg = localizar_ffmpeg()
    fonte = {"tipo": "arquivo", "caminho": str(_video(tmp_path))}
    primeiro = fl.clipe_da_fonte(fonte, 0.0, 2.0, ffmpeg, pasta=tmp_path / "cache")
    monkeypatch.setattr(fl, "cortar_arquivo", lambda *a, **k: pytest.fail("recortou de novo"))
    assert fl.clipe_da_fonte(fonte, 0.0, 2.0, ffmpeg, pasta=tmp_path / "cache") == primeiro


# --- link de outra rede ----------------------------------------------------------------------------

def test_link_lido_sem_baixar_nada():
    info = fl.informacoes_do_link("https://vimeo.com/1", extrair=lambda u: {
        "title": "Um vídeo", "duration": 42, "extractor_key": "Vimeo"})
    assert info == {"titulo": "Um vídeo", "duracao": 42.0, "site": "Vimeo", "url": "https://vimeo.com/1"}


def test_texto_que_nao_e_link_nem_chega_ao_yt_dlp():
    with pytest.raises(fl.FalhaNaFonte, match="link"):
        fl.informacoes_do_link("meu vídeo", extrair=lambda u: pytest.fail("chamou o yt-dlp"))


def test_site_que_pede_login_explica_o_caminho_do_arquivo():
    def pede_login(url):
        raise RuntimeError("ERROR: [Instagram] abc: Requested content is not available, rate-limit reached or login required")
    with pytest.raises(fl.FalhaNaFonte, match="login.*arquivo"):
        fl.informacoes_do_link("https://www.instagram.com/reel/abc/", extrair=pede_login)


def test_perfil_ou_lista_e_recusado():
    with pytest.raises(fl.FalhaNaFonte, match="um vídeo só"):
        fl.informacoes_do_link("https://www.tiktok.com/@conta", extrair=lambda u: {"_type": "playlist", "entries": []})


def test_transmissao_sem_duracao_e_recusada():
    with pytest.raises(fl.FalhaNaFonte, match="duração"):
        fl.informacoes_do_link("https://twitch.tv/x", extrair=lambda u: {"title": "ao vivo", "duration": None})


def test_do_link_so_o_trecho_e_baixado_e_fica_guardado(tmp_path):
    chamadas = []

    def baixar(url, inicio, fim, saida, ffmpeg=None, altura_max=None):
        chamadas.append((url, inicio, fim, altura_max))
        saida.write_bytes(b"mp4")

    fonte = {"tipo": "link", "url": "https://vimeo.com/1", "titulo": "x"}
    a = fl.clipe_da_fonte(fonte, 10.0, 25.0, "ffmpeg", 1080, pasta=tmp_path, baixar=baixar)
    b = fl.clipe_da_fonte(fonte, 10.0, 25.0, "ffmpeg", 1080, pasta=tmp_path, baixar=baixar)
    assert a == b and chamadas == [("https://vimeo.com/1", 10.0, 25.0, 1080)]


# --- legenda de .srt -------------------------------------------------------------------------------

SRT = ("﻿1\r\n00:00:01,000 --> 00:00:02,500\r\n<i>Primeira</i> linha\r\nsegunda linha\r\n\r\n"
       "2\r\n00:00:03.200 --> 00:00:04,000\r\n{\\an8}Outra fala\r\n\r\n"
       "3\r\n00:00:05,000 --> 00:00:04,000\r\ntempo invertido\r\n")


def test_srt_vira_falas_no_formato_da_transcricao():
    falas = lg.falas_do_srt(SRT)
    assert falas == [{"texto": "Primeira linha segunda linha", "start": 1.0, "dur": 1.5},
                     {"texto": "Outra fala", "start": 3.2, "dur": 0.8}]


def test_srt_vazio_ou_quebrado_nao_estoura():
    assert lg.falas_do_srt("") == [] and lg.falas_do_srt("isso não é srt") == []


def test_srt_passa_pela_mesma_montagem_de_legenda():
    blocos = lg.montar_legendas(lg.falas_do_srt(SRT), 0.0, 10.0)["blocos"]
    assert blocos and blocos[0]["inicio"] == pytest.approx(1.0)


# --- transcrição do áudio pela IA ------------------------------------------------------------------

def test_sem_chave_nao_ha_transcricao(tmp_path):
    r = ta.transcrever(tmp_path / "x.mp4", 10.0, None, "ffmpeg")
    assert r["degradado"] and r["falas"] == [] and r["motivo_degradado"] == MOTIVO_SEM_CHAVE


def test_transcricao_sai_no_formato_da_legenda_do_youtube(tmp_path, cliente_falso):
    resposta = json.dumps({"trechos": [{"inicio": 2.0, "fim": 3.5, "texto": "segunda"},
                                       {"inicio": 0.2, "fim": 1.8, "texto": "  primeira   fala "}]})
    cliente = cliente_falso(resposta)
    r = ta.transcrever(_video(tmp_path), 4.0, cliente, localizar_ffmpeg())
    assert not r["degradado"]
    assert r["falas"] == [{"texto": "primeira fala", "start": 0.2, "dur": 1.6},
                          {"texto": "segunda", "start": 2.0, "dur": 1.5}]
    audio, prompt = cliente.models.chamadas[0]["contents"]
    assert "não traduza" in prompt and getattr(audio, "inline_data", None) is not None


def test_tempo_fora_do_clipe_e_descartado_e_o_fim_e_aparado():
    trechos = [ta.TrechoFalado(inicio=1.0, fim=99.0, texto="passa do fim"),
               ta.TrechoFalado(inicio=50.0, fim=51.0, texto="depois do clipe"),
               ta.TrechoFalado(inicio=3.0, fim=2.0, texto="invertido")]
    assert ta.validar(trechos, 10.0) == [{"texto": "passa do fim", "start": 1.0, "dur": 9.0}]


def test_resposta_so_com_tempos_impossiveis_vira_modo_degradado(tmp_path, cliente_falso):
    cliente = cliente_falso(json.dumps({"trechos": [{"inicio": 80.0, "fim": 90.0, "texto": "fora"}]}))
    r = ta.transcrever(_video(tmp_path), 4.0, cliente, localizar_ffmpeg())
    assert r["degradado"] and "fora do clipe" in r["motivo_degradado"]


def test_falha_da_api_vira_modo_degradado(tmp_path, cliente_falso, erro_api):
    r = ta.transcrever(_video(tmp_path), 4.0, cliente_falso(erro_api(500, "interno")), localizar_ffmpeg())
    assert r["degradado"] and r["falas"] == []


# --- pequenos ajustes das telas ------------------------------------------------------------------------

def test_o_arquivo_do_corte_muda_quando_o_tempo_muda():
    """Antes o nome era só o número do corte: esticar o fim reaproveitava o arquivo curto."""
    assert arquivo_do_corte("abc", 1, 10, 40, 1440) != arquivo_do_corte("abc", 1, 10, 45, 1440)


@pytest.mark.parametrize("transcricao,esperado", [
    ({"codigo_idioma": "pt-BR", "idioma": "Portuguese (Brazil)"}, True),
    ({"codigo_idioma": "en", "idioma": "English"}, False),
    ({"idioma": "Português (gerada automaticamente)"}, True),       # análise antiga, sem a sigla
    ({"idioma": "Japanese"}, False),
])
def test_legenda_so_vem_ligada_quando_a_fala_e_em_portugues(transcricao, esperado):
    assert uf.transcricao_em_portugues(transcricao) is esperado


def test_a_previa_cai_numa_legenda_para_ela_aparecer():
    legendas = [{"inicio": 0.0, "fim": 1.0}, {"inicio": 2.0, "fim": 4.0}]
    assert uf.segundo_da_previa(legendas, 30.0) == 3.0
    assert uf.segundo_da_previa([], 30.0) == 10.0
