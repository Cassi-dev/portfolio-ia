import io
import json
import urllib.request

import pytest
from pydantic import ValidationError

from agente_map_reduce import avisos_de_degradacao, etapa_map, etapa_reduce, gerar_quiz, montar_fatias
from cortador_video import sugerir_cortes_virais
from esquemas_video import CorteViral, PerguntaQuiz, Topico
from gerador_roteiro import gerar_roteiro_viral
from transcricao_youtube import (
    extrair_id_video,
    obter_metadados_video,
    segundos_para_tempo,
    tempo_para_segundos,
    texto_para_prompt,
)

ID = "M7lc1UVf-VE"


def sintese_json():
    return json.dumps({
        "resumo_executivo": "Resumo.",
        "topicos_com_minutagem": [{"timestamp": "00:10", "titulo": "Intro", "descricao": "Abertura"}],
        "conclusao": "Fim.",
    })


def quiz_json(n=5):
    return json.dumps({"perguntas": [
        {"pergunta": f"P{i}?", "opcoes": ["A) a", "B) b", "C) c", "D) d"], "resposta_correta": 2, "explicacao": "e"}
        for i in range(n)
    ]})


def cortes_json(fim=95):
    return json.dumps({"cortes": [{"titulo": "T", "inicio_segundos": 50, "fim_segundos": fim, "motivo_viral": "m"}]})


def roteiro_json():
    cena = {"tempo": "0s a 3s", "bloco": "Gancho", "fala": "f", "direcao_visual": "d"}
    return json.dumps({"titulos_capa": ["t"], "cenas": [cena] * 4, "legenda_instagram": "l", "hashtags": "#a #b"})


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={ID}",
    f"https://www.youtube.com/watch?feature=share&v={ID}",
    f"https://youtu.be/{ID}?t=10",
    f"https://www.youtube.com/shorts/{ID}",
    f"https://www.youtube.com/embed/{ID}",
    ID,
])
def test_extrai_id_de_urls_de_video(url):
    assert extrair_id_video(url) == ID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/channel/UCabcdefghijklmnopqrstu",
    "https://www.youtube.com/playlist?list=PLabcdefghijklmnopqr",
    "https://exemplo.com/nada",
    "",
])
def test_nao_confunde_outras_urls_com_video(url):
    assert extrair_id_video(url) is None


def test_conversao_de_tempo_ida_e_volta():
    assert segundos_para_tempo(59) == "00:59"
    assert segundos_para_tempo(3661) == "01:01:01"
    assert tempo_para_segundos("01:01") == 61
    assert tempo_para_segundos("1:01:01") == 3661
    assert all(tempo_para_segundos(x) is None for x in ["abc", "10", "", "-1:00", "1:2:3:4"])


def test_metadados_do_video(monkeypatch):
    corpo = json.dumps({"title": "Aula de IA", "author_name": "Canal X"}).encode()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout: io.BytesIO(corpo))
    assert obter_metadados_video(ID) == {"titulo": "Aula de IA", "canal": "Canal X"}


def test_metadados_falham_sem_quebrar(monkeypatch):
    def falha(url, timeout):
        raise OSError("sem rede")
    monkeypatch.setattr(urllib.request, "urlopen", falha)
    assert obter_metadados_video(ID) == {"titulo": f"Vídeo {ID}", "canal": ""}


def test_fatias_respeitam_o_limite_e_nao_perdem_texto():
    blocos = [{"texto": "x" * 10} for _ in range(3)]
    assert [len(f) for f in montar_fatias(blocos, limite_chars=15)] == [1, 1, 1]
    assert [len(f) for f in montar_fatias(blocos, limite_chars=1000)] == [3]
    assert sum(len(f) for f in montar_fatias(blocos, limite_chars=25)) == 3


def test_transcricao_curta_vai_inteira_e_longa_e_amostrada_por_todo_o_video():
    blocos = [{"texto": f"linha {i:03d}"} for i in range(100)]
    formatar = lambda b: b["texto"]

    texto, amostrado = texto_para_prompt(blocos, max_chars=100_000, formatar=formatar)
    assert not amostrado and len(texto.splitlines()) == 100

    texto, amostrado = texto_para_prompt(blocos, max_chars=250, formatar=formatar)
    linhas = texto.splitlines()
    assert amostrado and len(texto) <= 250
    assert linhas[0] == "linha 000" and int(linhas[-1].split()[1]) >= 90


def test_schemas_rejeitam_respostas_malformadas():
    with pytest.raises(ValidationError):
        Topico(timestamp="abc", titulo="t", descricao="d")
    with pytest.raises(ValidationError):
        PerguntaQuiz(pergunta="p", opcoes=["a", "b", "c"], resposta_correta=0, explicacao="e")
    with pytest.raises(ValidationError):
        PerguntaQuiz(pergunta="p", opcoes=["a", "b", "c", "d"], resposta_correta=4, explicacao="e")
    with pytest.raises(ValidationError):
        CorteViral(titulo="t", inicio_segundos=50, fim_segundos=10, motivo_viral="m")
    with pytest.raises(ValidationError):
        CorteViral(titulo="t", inicio_segundos=0, fim_segundos=600, motivo_viral="m")


def test_sem_ia_toda_etapa_avisa_que_esta_degradada(blocos_video):
    resumos = etapa_map(blocos_video)
    assert resumos and all(r["degradado"] for r in resumos)

    sintese = etapa_reduce(resumos)
    assert sintese["degradado"] and sintese["conclusao"] == ""
    assert sintese["resumo_executivo"].startswith("Sem síntese por IA")

    quiz = gerar_quiz(sintese)
    assert quiz["degradado"] and quiz["perguntas"] == []

    cortes = sugerir_cortes_virais({"blocos": blocos_video})
    assert cortes["degradado"] and len(cortes["cortes"]) == 5

    roteiro = gerar_roteiro_viral({"blocos": blocos_video})
    assert roteiro["degradado"] and "NÃO é baseado no vídeo" in roteiro["motivo_degradado"]

    res = {"resumos_map": resumos, "sintese": sintese, "quiz": quiz, "cortes": cortes, "roteiro": roteiro}
    assert len(avisos_de_degradacao(res)) == 5


def test_com_ia_valida_nada_fica_degradado(blocos_video, cliente_falso):
    resumos = etapa_map(blocos_video, client=cliente_falso("- ponto 1\n- ponto 2"))
    assert not any(r["degradado"] for r in resumos)

    sintese = etapa_reduce(resumos, client=cliente_falso(sintese_json()))
    assert not sintese["degradado"] and sintese["conclusao"] == "Fim."

    quiz = gerar_quiz(sintese, client=cliente_falso(quiz_json()))
    assert not quiz["degradado"] and len(quiz["perguntas"]) == 5 and quiz["perguntas"][0]["resposta_correta"] == 2

    cortes = sugerir_cortes_virais({"blocos": blocos_video, "duracao_segundos": 500}, client=cliente_falso(cortes_json()))
    assert not cortes["degradado"] and cortes["cortes"][0]["fim_segundos"] == 95

    roteiro = gerar_roteiro_viral({"blocos": blocos_video}, client=cliente_falso(roteiro_json()))
    assert not roteiro["degradado"] and len(roteiro["cenas"]) == 4

    res = {"resumos_map": resumos, "sintese": sintese, "quiz": quiz, "cortes": cortes, "roteiro": roteiro}
    assert avisos_de_degradacao(res) == []


def test_map_manda_o_contexto_do_video_e_preserva_a_ordem(cliente_falso):
    blocos = [
        {"timestamp_segundos": i * 60.0, "timestamp_formatado": f"{i:02d}:00", "texto": "palavra " * 20}
        for i in range(6)
    ]
    cliente = cliente_falso("resumo")
    resumos = etapa_map(blocos, client=cliente, limite_chars=200, contexto="Vídeo: Aula X (canal Y).\n\n")
    assert len(resumos) > 1
    assert [r["inicio"] for r in resumos] == sorted(r["inicio"] for r in resumos)
    assert all(c["contents"].startswith("Vídeo: Aula X (canal Y).") for c in cliente.models.chamadas)


def test_json_invalido_da_ia_vira_aviso_e_nao_texto_generico(blocos_video, cliente_falso):
    resumos = etapa_map(blocos_video, client=cliente_falso("ok"))
    sintese = etapa_reduce(resumos, client=cliente_falso("isto não é json"))
    assert sintese["degradado"] and "formato" in sintese["motivo_degradado"]

    quiz = gerar_quiz(sintese, client=cliente_falso(quiz_json(n=3)))
    assert quiz["degradado"] and quiz["perguntas"] == []


def test_erro_da_api_vira_aviso_com_o_motivo(blocos_video, cliente_falso):
    resumos = etapa_map(blocos_video, client=cliente_falso(RuntimeError("cota esgotada")))
    assert all("cota esgotada" in r["motivo_degradado"] for r in resumos)
    sintese = etapa_reduce(resumos, client=cliente_falso(RuntimeError("cota esgotada")))
    assert sintese["degradado"] and "cota esgotada" in sintese["motivo_degradado"]


def test_cortes_que_passam_do_fim_do_video_sao_descartados(blocos_video, cliente_falso):
    cortes = sugerir_cortes_virais({"blocos": blocos_video, "duracao_segundos": 100}, client=cliente_falso(cortes_json(fim=150)))
    assert cortes["degradado"] and "duração" in cortes["motivo_degradado"]


def test_moeda_br_usa_ponto_de_milhar_e_virgula_decimal():
    from renderizador_video_tacto import moeda_br
    assert moeda_br(1234.5) == "1.234,50"
    assert moeda_br(1234567.891) == "1.234.567,89"
    assert moeda_br(0) == "0,00"


def test_video_le_os_numeros_do_pwa_do_banco_em_vez_de_valores_fixos(banco_temp):
    from renderizador_video_tacto import metricas_pwa
    m = metricas_pwa(banco_temp.CAMINHO_BANCO)
    esperado = banco_temp.executar_consulta(
        "SELECT COUNT(*), SUM(valor_total) FROM pedidos WHERE canal_venda = 'PWA TACTO' AND status = 'Concluído'"
    ).df.iloc[0]
    assert m["pedidos"] == esperado.iloc[0] and m["total"] == pytest.approx(esperado.iloc[1])
    assert m["ticket"] == pytest.approx(m["total"] / m["pedidos"])


def test_video_sem_banco_de_demonstracao_nao_inventa_numeros(tmp_path):
    from renderizador_video_tacto import metricas_pwa
    assert metricas_pwa(str(tmp_path / "nao_existe.db")) is None


# --- corte de clipe: o ffmpeg do projeto, sem depender do download parcial do yt-dlp -------------------------

import subprocess as _subprocess
from pathlib import Path
from types import SimpleNamespace

import cortador_video
from cortador_video import FalhaNoCorte, baixar_e_cortar_clipe, fontes_do_video


def test_formato_com_audio_junto_vira_um_stream_so():
    info = {"url": "https://stream/muxed.mp4", "format_id": "18"}
    assert fontes_do_video("u", lambda url: info) == (["https://stream/muxed.mp4"], "18")


def test_video_e_audio_separados_viram_dois_streams():
    info = {"requested_formats": [{"url": "https://v", "format_id": "137"},
                                  {"url": "https://a", "format_id": "140"}]}
    urls, formato = fontes_do_video("u", lambda url: info)
    assert urls == ["https://v", "https://a"] and formato == "137+140"


def test_video_sem_stream_explica_em_portugues():
    with pytest.raises(FalhaNoCorte, match="restrito ou privado"):
        fontes_do_video("u", lambda url: {})


def test_erro_do_youtube_vira_falha_legivel():
    def explode(url):
        raise RuntimeError("Video unavailable")

    with pytest.raises(FalhaNoCorte, match="não consegui ler o vídeo"):
        fontes_do_video("u", explode)


@pytest.mark.parametrize("inicio,fim", [(30, 30), (40, 10)])
def test_intervalo_invalido_e_recusado(inicio, fim, tmp_path):
    with pytest.raises(FalhaNoCorte, match="intervalo inválido"):
        baixar_e_cortar_clipe("u", inicio, fim, tmp_path / "x.mp4", extrair=lambda url: {"url": "https://s"})


def _ffmpeg_falso(monkeypatch, codigo=0, stderr="", escreve=b"dados"):
    capturado = {}

    def executar(comando, **kwargs):
        capturado["comando"] = comando
        if escreve:
            Path(comando[-1]).write_bytes(escreve)
        return SimpleNamespace(returncode=codigo, stderr=stderr)

    monkeypatch.setattr(cortador_video.subprocess, "run", executar)
    return capturado


def test_comando_busca_antes_de_ler_limita_a_duracao_e_recodifica(monkeypatch, tmp_path):
    capturado = _ffmpeg_falso(monkeypatch)
    saida = tmp_path / "corte.mp4"
    baixar_e_cortar_clipe("u", 30, 75, saida, extrair=lambda url: {"url": "https://s", "format_id": "18"},
                          ffmpeg="ffmpeg-de-mentira")
    comando = capturado["comando"]
    assert comando[0] == "ffmpeg-de-mentira"
    # -ss antes do -i é o que faz a busca ser rápida em vez de ler o vídeo desde o começo
    assert comando[comando.index("-i") - 4:comando.index("-i")] == ["-ss", "30", "-t", "45"]
    assert "libx264" in comando and "aac" in comando and comando[-1] == str(saida)


def test_dois_streams_sao_mapeados_para_video_e_audio(monkeypatch, tmp_path):
    capturado = _ffmpeg_falso(monkeypatch)
    info = {"requested_formats": [{"url": "https://v", "format_id": "137"}, {"url": "https://a", "format_id": "140"}]}
    baixar_e_cortar_clipe("u", 0, 10, tmp_path / "c.mp4", extrair=lambda url: info, ffmpeg="f")
    comando = capturado["comando"]
    assert comando.count("-i") == 2 and comando.count("-ss") == 2
    assert "-map" in comando and "0:v:0" in comando and "1:a:0" in comando


def test_erro_do_ffmpeg_vira_mensagem_com_o_motivo(monkeypatch, tmp_path):
    _ffmpeg_falso(monkeypatch, codigo=1, stderr="Server returned 403 Forbidden", escreve=b"")
    with pytest.raises(FalhaNoCorte, match="403 Forbidden"):
        baixar_e_cortar_clipe("u", 0, 10, tmp_path / "c.mp4", extrair=lambda url: {"url": "https://s"}, ffmpeg="f")


def test_ffmpeg_que_termina_sem_erro_mas_nao_gera_arquivo(monkeypatch, tmp_path):
    _ffmpeg_falso(monkeypatch, codigo=0, escreve=b"")
    with pytest.raises(FalhaNoCorte, match="não gerou arquivo"):
        baixar_e_cortar_clipe("u", 0, 10, tmp_path / "c.mp4", extrair=lambda url: {"url": "https://s"}, ffmpeg="f")


def test_ffmpeg_inexistente_explica(monkeypatch, tmp_path):
    def sem_executavel(comando, **kwargs):
        raise OSError("arquivo não encontrado")

    monkeypatch.setattr(cortador_video.subprocess, "run", sem_executavel)
    with pytest.raises(FalhaNoCorte, match="não consegui executar o ffmpeg"):
        baixar_e_cortar_clipe("u", 0, 10, tmp_path / "c.mp4", extrair=lambda url: {"url": "https://s"}, ffmpeg="f")


# --- qualidade: o corte saía em 360p porque forçávamos o player_client "android" -------------------

def _yt_dlp_falso(monkeypatch, falhas=0, resultado=None):
    """Substitui o yt_dlp e devolve a lista de opções de cada tentativa."""
    chamadas = []
    resultado = resultado or {"url": "https://s", "format_id": "18"}

    class Falso:
        def __init__(self, opcoes):
            chamadas.append(opcoes)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            if len(chamadas) <= falhas:
                raise RuntimeError("Sign in to confirm you're not a bot")
            return resultado

    monkeypatch.setattr(cortador_video.yt_dlp, "YoutubeDL", Falso)
    return chamadas


def test_formato_pede_video_e_audio_separados_primeiro():
    """No YouTube, o que já vem com áudio junto para em 360p: a alta definição só existe separada."""
    formato = cortador_video.formato_para(720)
    assert formato.startswith("bestvideo[height<=720]")
    assert formato.count("height<=720") == 3 and formato.endswith("/best")


def test_o_seletor_nao_prende_o_codec_para_nao_perder_1440p_e_4k():
    """O H.264 do YouTube para em 1080p; pedir avc1 primeiro jogaria fora as resoluções maiores."""
    assert "avc1" not in cortador_video.formato_para(2160)
    assert cortador_video.ALTURA_PADRAO == 1440 and 2160 in cortador_video.ALTURAS


def test_a_qualidade_escolhida_chega_ao_yt_dlp(monkeypatch, tmp_path):
    chamadas = _yt_dlp_falso(monkeypatch)
    _ffmpeg_falso(monkeypatch)
    baixar_e_cortar_clipe("u", 0, 10, tmp_path / "c.mp4", ffmpeg="f", altura_max=720)
    assert "height<=720" in chamadas[0]["format"]


def test_a_primeira_tentativa_nao_forca_cliente_nenhum(monkeypatch):
    chamadas = _yt_dlp_falso(monkeypatch)
    fontes_do_video("u")
    assert len(chamadas) == 1 and "extractor_args" not in chamadas[0]


def test_se_o_youtube_recusar_tenta_de_novo_pelo_cliente_android(monkeypatch):
    chamadas = _yt_dlp_falso(monkeypatch, falhas=1)
    fontes_do_video("u")
    assert chamadas[1]["extractor_args"]["youtube"]["player_client"] == ["android"]


def test_se_as_duas_tentativas_falharem_a_mensagem_explica(monkeypatch):
    _yt_dlp_falso(monkeypatch, falhas=2)
    with pytest.raises(FalhaNoCorte, match="não consegui ler o vídeo"):
        fontes_do_video("u")


def test_o_video_vem_antes_do_audio_mesmo_se_o_yt_dlp_inverter():
    info = {"requested_formats": [{"url": "https://a", "format_id": "140", "vcodec": "none", "acodec": "mp4a"},
                                  {"url": "https://v", "format_id": "299", "vcodec": "avc1", "acodec": "none",
                                   "height": 1080}]}
    urls, rotulo = fontes_do_video("u", lambda url: info)
    assert urls == ["https://v", "https://a"] and rotulo.startswith("1080p")


def test_o_rotulo_diz_a_altura_do_que_veio():
    info = {"url": "https://s", "format_id": "18", "height": 360}
    assert fontes_do_video("u", lambda url: info)[1] == "360p (18)"


@pytest.mark.network
def test_corte_real_nao_sai_mais_em_360p(tmp_path):
    """O que o usuário relatou: imagem ruim porque só chegava o formato 18."""
    import re

    from core.midia import localizar_ffmpeg

    saida = tmp_path / "hd.mp4"
    baixar_e_cortar_clipe("https://www.youtube.com/watch?v=aircAruvnKk", 60, 66, saida)
    info = _subprocess.run([localizar_ffmpeg(), "-i", str(saida)], capture_output=True, text=True,
                           errors="ignore").stderr
    altura = int(re.search(r"[\s,](\d{2,5})x(\d{2,5})", info.split("Video:", 1)[1]).group(2))
    assert altura >= 720, f"veio em {altura}p"


@pytest.mark.network
def test_corta_um_video_real_com_imagem_e_som(tmp_path):
    """O cenário que quebrou em uso real: yt-dlp abortava por não achar o ffmpeg empacotado."""
    from core.midia import localizar_ffmpeg

    saida = tmp_path / "corte.mp4"
    baixar_e_cortar_clipe("https://www.youtube.com/watch?v=M7lc1UVf-VE", 10, 20, saida)
    assert saida.stat().st_size > 10_000
    info = _subprocess.run([localizar_ffmpeg(), "-i", str(saida)], capture_output=True, text=True,
                           errors="ignore").stderr
    assert "Video: h264" in info and "Audio: aac" in info
    assert "Duration: 00:00:10" in info


# --- o corte encaixado na frase ------------------------------------------------------------------

def _palavras(*pares):
    """(texto, inicio) -> palavras de 0,5s, como as que saem da transcrição cronometrada."""
    return [{"texto": t, "inicio": i, "fim": i + 0.5} for t, i in pares]


FALA = _palavras(("Primeira", 0.0), ("frase", 1.0), ("curta.", 2.0),
                 ("Agora", 4.0), ("vem", 5.0), ("o", 6.0), ("contexto", 7.0), ("todo.", 8.0),
                 ("E", 10.0), ("fecha", 11.0), ("aqui.", 12.0))


def test_o_fim_avanca_ate_a_frase_terminar():
    """O que apareceu em uso real: o corte saía antes de a pessoa terminar o raciocínio."""
    inicio, fim = cortador_video.ajustar_ao_limite_da_frase(4.0, 6.5, FALA)
    assert (inicio, fim) == (4.0, 8.5)


def test_o_comeco_recua_ate_a_frase_comecar():
    inicio, fim = cortador_video.ajustar_ao_limite_da_frase(6.0, 12.5, FALA)
    assert inicio == 4.0 and fim == 12.5


def test_o_fim_nao_estica_alem_da_duracao_maxima():
    """O teto vem por parâmetro: a edição multi-trecho aperta esse limite por trecho."""
    _, fim = cortador_video.ajustar_ao_limite_da_frase(4.0, 6.5, FALA, duracao_maxima=3.0)
    assert fim == 6.5                                   # esticar até 8,5 passaria do teto
    _, solto = cortador_video.ajustar_ao_limite_da_frase(4.0, 6.5, FALA)
    assert solto == 8.5                                 # com o teto padrão, estica


def test_esticar_e_sempre_preferido_a_encurtar():
    """Encurtar corta conteúdo; esticar só custa segundos. Entre as duas, estica."""
    fala = _palavras(("Abre", 0.0), ("e", 1.0), ("fecha.", 20.0), ("Depois", 40.0), ("vem", 41.0), ("outra.", 42.0))
    _, fim = cortador_video.ajustar_ao_limite_da_frase(0.0, 22.0, fala)
    assert fim == 42.5                                  # 20,5s estava logo atrás, mas cortaria a fala


def test_no_fim_do_video_encurta_por_pouco_em_vez_de_ficar_no_meio_da_frase():
    """Sem frase nenhuma para a frente, aceita recuar — desde que a fronteira esteja logo ali atrás."""
    fala = _palavras(("Abre", 0.0), ("e", 1.0), ("fecha.", 20.0), ("Sobrou", 30.0), ("sem", 31.0), ("ponto", 32.0))
    _, fim = cortador_video.ajustar_ao_limite_da_frase(0.0, 22.0, fala)
    assert fim == 20.5


def test_sem_transcricao_cronometrada_o_corte_fica_como_veio():
    assert cortador_video.ajustar_ao_limite_da_frase(10.0, 40.0, []) == (10.0, 40.0)


def test_o_corte_nunca_fica_vazio():
    inicio, fim = cortador_video.ajustar_ao_limite_da_frase(2.2, 2.4, FALA)
    assert fim > inicio


def test_a_sugestao_sem_ia_devolve_cinco_cortes_espalhados(blocos_video):
    cortes = cortador_video.cortes_heuristicos(blocos_video, 5)
    inicios = [c["inicio_segundos"] for c in cortes]
    assert len(cortes) == 5 and inicios == sorted(set(inicios))
    assert inicios[-1] > inicios[0]


def test_video_curto_nao_repete_o_mesmo_corte():
    blocos = [{"timestamp_segundos": i * 50.0, "timestamp_formatado": "00:00", "texto": "t"} for i in range(2)]
    assert len(cortador_video.cortes_heuristicos(blocos, 5)) == 1


def test_o_prompt_usa_a_marcacao_fina_e_pede_frase_inteira(blocos_video, cliente_falso):
    """Com só os blocos, a IA via uma marcação a cada ~44s e chutava o segundo do corte dentro dela."""
    falas = [{"texto": "palavra", "start": i * 3.0, "dur": 3.0} for i in range(20)]
    dados = {"blocos": blocos_video, "falas": falas, "duracao_segundos": 500}
    cliente = cliente_falso(cortes_json())
    cortador_video.sugerir_cortes_virais(dados, client=cliente)

    prompt = cliente.models.chamadas[0]["contents"]
    assert "[0s] palavra" in prompt and "[57s] palavra" in prompt
    assert "5 MELHORES CORTES" in prompt
    assert "INÍCIO de uma frase" in prompt and "FIM de uma frase" in prompt


def test_o_corte_que_a_ia_escolheu_tambem_e_encaixado_na_frase(blocos_video, cliente_falso):
    falas = [{"texto": "fecha.", "start": 96.0, "dur": 1.0}, {"texto": "seguinte", "start": 98.0, "dur": 1.0}]
    dados = {"blocos": blocos_video, "falas": falas, "duracao_segundos": 500}
    cortes = cortador_video.sugerir_cortes_virais(dados, client=cliente_falso(cortes_json(fim=95)))["cortes"]
    assert cortes[0]["fim_segundos"] == 97                # esticou até a frase fechar
