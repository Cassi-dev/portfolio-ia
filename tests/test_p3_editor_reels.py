"""Editor de Reels do Projeto 3: corte do YouTube + roteiro viram um .mp4 pronto para postar."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import editor_reels as ed
import renderizador_generico as rg
from legendas import montar_legendas
from temas_video import PRESETS, TEMA_PADRAO

TEMA = PRESETS[TEMA_PADRAO]
ESTILO = rg.criar_estilo(TEMA, "@meucanal")

SAIDA_FFMPEG = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'corte.mp4':
  Duration: 00:01:04.50, start: 0.000000, bitrate: 612 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709), 1920x1080 [SAR 1:1 DAR 16:9], 402 kb/s, 60 fps
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 195 kb/s
"""


# --- leitura do clipe -----------------------------------------------------------------------------

def test_le_tamanho_duracao_e_audio_do_que_o_ffmpeg_imprime():
    props = ed.ler_propriedades(SAIDA_FFMPEG)
    assert (props["largura"], props["altura"]) == (1920, 1080)
    assert props["duracao"] == pytest.approx(64.5)
    assert props["tem_audio"] is True


def test_o_codigo_hexadecimal_do_codec_nao_e_confundido_com_o_tamanho():
    """"(avc1 / 0x31637661)" vem antes do "1920x1080" na mesma linha."""
    assert ed.ler_propriedades(SAIDA_FFMPEG)["largura"] == 1920


def test_clipe_mudo_e_reconhecido():
    assert ed.ler_propriedades(SAIDA_FFMPEG.replace("Audio", "Legenda"))["tem_audio"] is False


def test_saida_sem_video_nao_inventa_tamanho():
    assert ed.ler_propriedades("Invalid data found when processing input")["largura"] is None


def test_clipe_ilegivel_explica_em_portugues(monkeypatch, tmp_path):
    monkeypatch.setattr(ed.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="Invalid data"))
    with pytest.raises(ed.FalhaNaEdicao, match="não consegui ler o clipe"):
        ed.sondar_clipe(tmp_path / "x.mp4", "ffmpeg")


# --- geometria ------------------------------------------------------------------------------------

def test_sem_nada_escrito_em_cima_o_video_ocupa_a_largura_inteira():
    """8% a mais de imagem e de resolução do que quando há título ou etiqueta no topo."""
    largo, _, _, _ = ed.geometria_do_clipe(1920, 1080, ed.CAIXA_CLIPE_LIMPA)
    estreito, _, _, _ = ed.geometria_do_clipe(1920, 1080, ed.CAIXA_CLIPE)
    assert largo == ed.LARGURA and largo >= estreito


def test_video_16x9_cabe_inteiro_na_caixa_e_fica_centralizado():
    w, h, x, y = ed.geometria_do_clipe(1920, 1080, ed.CAIXA_CLIPE)
    x1, y1, x2, y2 = ed.CAIXA_CLIPE
    assert w == x2 - x1 and abs(h - w * 1080 / 1920) <= 2        # proporção mantida, arredondada para par
    assert x == x1 and y1 < y < y2 and y + h <= y2
    assert (y - y1) == pytest.approx((y2 - (y + h)), abs=1)


def test_video_vertical_cabe_pela_altura():
    w, h, x, y = ed.geometria_do_clipe(1080, 1920, ed.CAIXA_CLIPE)
    x1, y1, x2, y2 = ed.CAIXA_CLIPE
    assert h == y2 - y1 and w < x2 - x1 and y == y1


@pytest.mark.parametrize("largura,altura", [(1920, 1080), (1080, 1920), (640, 480), (1281, 721)])
def test_tamanho_sempre_par(largura, altura):
    """O yuv420p exige largura e altura pares; ímpar faz o ffmpeg abortar."""
    w, h, _, _ = ed.geometria_do_clipe(largura, altura)
    assert w % 2 == 0 and h % 2 == 0


def test_com_titulo_o_video_desce_para_nao_encostar_nele():
    _, altura, _, topo = ed.geometria_do_clipe(1920, 1080, ed.CAIXA_CLIPE)
    assert topo > ed.Y_TITULO + 3 * rg.altura_linha(rg.fonte(True, 54)) + 56
    assert topo + altura < ed.BASE_LEGENDA - 200


def test_o_cartao_de_titulo_nunca_alcanca_o_video():
    """Quando há título, o vídeo usa a caixa mais baixa — senão um passaria por cima do outro."""
    alto_maximo = 3 * rg.altura_linha(rg.fonte(True, 54)) + 56
    assert ed.Y_TITULO + alto_maximo <= ed.CAIXA_CLIPE[1]


def _falas(*trios):
    return [{"texto": t, "start": i, "dur": d} for t, i, d in trios]


# --- artes ----------------------------------------------------------------------------------------

def test_moldura_e_transparente_fora_dos_elementos():
    img = ed.desenhar_moldura(ESTILO, "Um título qualquer", "corte 1")
    assert img.size == (ed.LARGURA, ed.ALTURA) and img.mode == "RGBA"
    assert img.getpixel((5, 5))[3] == 0 and img.getpixel((1075, 1915))[3] == 0


def test_a_moldura_nao_contorna_o_video():
    """Quem separa a imagem do fundo é o desfoque; uma borda colorida só marcaria a peça como template."""
    img = ed.desenhar_moldura(ESTILO, "Um título", "etiqueta")
    assert img.getbbox()[3] < ed.CAIXA_CLIPE[1]          # nada desenhado na altura do vídeo


def test_sem_marca_etiqueta_nem_titulo_a_camada_sai_vazia():
    """Camada vazia não vira entrada do ffmpeg: é o padrão de só imagem e legenda."""
    limpo = rg.criar_estilo(TEMA, "")
    assert ed.desenhar_moldura(limpo, "", "").getbbox() is None
    assert ed.desenhar_moldura(limpo, "com título", "").getbbox() is not None


def test_titulo_absurdamente_longo_nao_sai_do_cartao():
    img = ed.desenhar_moldura(ESTILO, "palavra " * 90)
    alto_maximo = 3 * rg.altura_linha(rg.fonte(True, 54)) + 56
    desenhado = img.crop((0, 0, ed.LARGURA, ed.CAIXA_CLIPE[1] - 10)).getbbox()
    assert desenhado[3] <= ed.Y_TITULO + alto_maximo + 2


@pytest.mark.parametrize("texto", ["Oi", "uma frase de tamanho comum no meio do vídeo", "palavra " * 60])
def test_legenda_nao_invade_o_video_nem_a_area_da_interface(texto):
    caixa = ed.desenhar_legenda(ESTILO, texto).getbbox()
    _, altura_video, _, topo_video = ed.geometria_do_clipe(1920, 1080, ed.CAIXA_CLIPE_LIMPA)
    assert 45 <= caixa[0] and caixa[2] <= 1035
    assert caixa[1] > topo_video + altura_video and caixa[3] <= ed.BASE_LEGENDA + 8


def test_legenda_de_uma_linha_fica_mais_embaixo_que_a_de_tres():
    uma = ed.desenhar_legenda(ESTILO, "curta").getbbox()
    tres = ed.desenhar_legenda(ESTILO, "palavra " * 30).getbbox()
    assert uma[1] > tres[1] and uma[3] == pytest.approx(tres[3], abs=12)


def test_por_padrao_a_legenda_nao_tem_caixa_atras():
    """Caixa preta sobre a imagem foi o que o uso real reprovou: o texto vai direto no vídeo, com contorno."""
    sem = ed.desenhar_legenda(ESTILO, "uma frase de legenda")
    com = ed.desenhar_legenda(ESTILO, "uma frase de legenda", com_caixa=True)
    # o cartão pinta uma faixa inteira; só o texto pinta bem menos pixels
    assert _pixels_opacos(sem) < _pixels_opacos(com) / 3


def test_a_legenda_sem_caixa_tem_contorno_para_ler_sobre_qualquer_imagem():
    img = ed.desenhar_legenda(ESTILO, "uma frase")
    cores = {cor[:3] for _, cor in img.getcolors(maxcolors=1 << 20) if cor[3] > 200}
    assert rg.cor_sobre(ESTILO.texto) in cores and tuple(ESTILO.texto) in cores


def _pixels_opacos(img):
    return sum(img.getchannel("A").histogram()[129:])


def test_emoji_nao_vira_quadradinho_na_legenda():
    """A fonte do vídeo não desenha emoji; ele é removido antes (mesma regra do renderizador)."""
    com = ed.desenhar_legenda(ESTILO, "isso aqui é bom 🔥").tobytes()
    sem = ed.desenhar_legenda(ESTILO, "isso aqui é bom").tobytes()
    assert com == sem


# --- comando do ffmpeg (montado e conferido sem rodar nada) ---------------------------------------

def test_filtro_inteiro_desfoca_o_fundo_e_encaixa_o_video():
    filtro = ed.filtro_de_composicao((960, 540, 60, 690), [], 15.0, "0x00F0FF@0.95")
    assert "split=2" in filtro and "boxblur" in filtro
    assert "scale=960:540" in filtro and "overlay=60:690" in filtro


def test_filtro_que_preenche_a_tela_nao_gasta_tempo_desfocando():
    filtro = ed.filtro_de_composicao(None, [], 15.0, "0x00F0FF@0.95")
    assert "boxblur" not in filtro and "split" not in filtro
    assert f"crop={ed.LARGURA}:{ed.ALTURA}" in filtro


def test_o_desfoque_e_feito_em_escala_reduzida():
    """Borrar em 1080x1920 custava 4 vezes mais tempo pelo mesmo borrão."""
    filtro = ed.filtro_de_composicao((960, 540, 60, 690), [], 15.0, "0x0@1")
    assert f"scale={ed.LARGURA // 4}:{ed.ALTURA // 4}" in filtro.split("boxblur")[0]


def test_cada_legenda_vira_uma_sobreposicao_com_hora_de_entrar_e_sair():
    sobreposicoes = [{"entrada": 1, "inicio": None, "fim": None},
                     {"entrada": 2, "inicio": 0.0, "fim": 2.4},
                     {"entrada": 3, "inicio": 2.4, "fim": 5.0}]
    filtro = ed.filtro_de_composicao((960, 540, 60, 690), sobreposicoes, 15.0, "0x0@1")
    assert "[2:v]overlay=0:0:enable='between(t,0.00,2.40)'" in filtro
    assert "[1:v]overlay=0:0[v1]" in filtro                      # a moldura fica o tempo todo
    assert filtro.endswith("[final]")


def test_a_barra_de_progresso_percorre_a_duracao_do_clipe_dentro_das_margens():
    filtro = ed.filtro_de_composicao(None, [], 42.0, "0x00F0FF@0.95", com_barra=True)
    assert "drawbox=x=60" in filtro and "w='(iw-120)*t/42.000'" in filtro and "color=0x00F0FF@0.95" in filtro


def test_sem_barra_nao_sobra_filtro_nenhum_no_rodape():
    assert "drawbox" not in ed.filtro_de_composicao(None, [], 42.0, "0x0@1")


def test_a_ampliacao_liga_a_nitidez_e_a_reducao_nao():
    """Realçar contorno faz sentido quando a imagem é esticada; numa redução, só criaria artefato."""
    filtro_ampliando = ed.filtro_de_composicao(None, [], 10.0, "0x0@1", nitidez=True)
    assert ed.NITIDEZ in filtro_ampliando and "flags=lanczos" in filtro_ampliando
    assert ed.NITIDEZ not in ed.filtro_de_composicao(None, [], 10.0, "0x0@1")


@pytest.mark.parametrize("largura,altura,enquadramento,esperado", [
    (1920, 1080, ed.PREENCHER, 1.78),      # 16:9 em tela cheia: o miolo é esticado
    (3840, 2160, ed.PREENCHER, 0.89),      # 4K em tela cheia: ainda sobra resolução
    (1920, 1080, ed.INTEIRO, 0.56),        # vídeo inteiro: sempre reduz
])
def test_ampliacao_diz_quanto_a_imagem_e_esticada(largura, altura, enquadramento, esperado):
    props = {"largura": largura, "altura": altura}
    assert ed.ampliacao(props, enquadramento) == pytest.approx(esperado, abs=0.01)


def test_cada_arte_entra_como_uma_imagem_e_o_audio_vem_do_clipe():
    comando = ed.comando_de_composicao("ffmpeg", "c.mp4", ["a.png", "b.png"], "F", 15.0, "s.mp4", tem_audio=True)
    assert comando.count("-i") == 3 and comando[5] == "c.mp4"
    assert comando[comando.index("-map") + 1] == "[final]" and "0:a:0" in comando


def test_clipe_sem_audio_ganha_silencio_para_nao_quebrar_a_juncao():
    comando = ed.comando_de_composicao("ffmpeg", "c.mp4", ["a.png"], "F", 15.0, "s.mp4", tem_audio=False)
    assert "anullsrc=r=44100:cl=stereo" in comando and "2:a" in comando


def test_o_video_sai_no_mesmo_formato_dos_cartoes():
    """Se um parâmetro divergir, juntar sem recodificar falha e o vídeo é recomprimido à toa."""
    comando = ed.comando_de_composicao("ffmpeg", "c.mp4", [], "F", 15.0, "s.mp4", tem_audio=True)
    for parametro in ("libx264", "yuv420p", "aac", "44100"):
        assert parametro in comando
    assert comando[comando.index("-r") + 1] == str(rg.FPS)


def test_cor_do_tema_vira_cor_do_ffmpeg():
    assert ed.cor_ffmpeg((0, 240, 255), 0.95) == "0x00F0FF@0.95"


def test_erro_do_ffmpeg_ao_tratar_o_clipe_vira_mensagem_legivel(monkeypatch, tmp_path):
    monkeypatch.setattr(ed.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stderr="Filter not found"))
    with pytest.raises(ed.FalhaNaEdicao, match="Filter not found"):
        ed.tratar_clipe("c.mp4", estilo=ESTILO, titulo="t", saida=tmp_path / "s.mp4", ffmpeg="f",
                        pasta_arte=tmp_path, props={"largura": 1920, "altura": 1080, "duracao": 5.0, "tem_audio": True})


# --- junção ---------------------------------------------------------------------------------------

def _gravador(monkeypatch, codigos):
    chamadas = []

    def executar(comando, **kwargs):
        chamadas.append(comando)
        return SimpleNamespace(returncode=codigos[len(chamadas) - 1], stderr="não bateu o formato")

    monkeypatch.setattr(ed.subprocess, "run", executar)
    return chamadas


def test_junta_sem_recodificar_quando_da_certo(monkeypatch, tmp_path):
    chamadas = _gravador(monkeypatch, [0])
    ed.juntar(["a.mp4", "b.mp4"], tmp_path / "f.mp4", "ffmpeg", tmp_path)
    assert len(chamadas) == 1 and "copy" in chamadas[0]
    assert "file 'a.mp4'" in (tmp_path / "partes.txt").read_text(encoding="utf-8")


def test_se_a_copia_falhar_recodifica(monkeypatch, tmp_path):
    chamadas = _gravador(monkeypatch, [1, 0])
    ed.juntar(["a.mp4", "b.mp4"], tmp_path / "f.mp4", "ffmpeg", tmp_path)
    assert len(chamadas) == 2 and "libx264" in chamadas[1]


def test_se_os_dois_jeitos_falharem_a_mensagem_diz(monkeypatch, tmp_path):
    _gravador(monkeypatch, [1, 1])
    with pytest.raises(ed.FalhaNaEdicao, match="juntar as partes"):
        ed.juntar(["a.mp4", "b.mp4"], tmp_path / "f.mp4", "ffmpeg", tmp_path)


def test_so_o_clipe_nao_passa_pela_juncao(tmp_path):
    """Sem cartões não há o que juntar: uma passagem a menos de ffmpeg no caminho mais comum."""
    origem = tmp_path / "tratado.mp4"
    origem.write_bytes(b"video")
    ed.juntar([str(origem)], tmp_path / "final.mp4", "ffmpeg-que-nao-existe", tmp_path)
    assert (tmp_path / "final.mp4").read_bytes() == b"video" and not origem.exists()


def test_montar_sem_o_clipe_avisa_em_vez_de_estourar(tmp_path):
    with pytest.raises(ed.FalhaNaEdicao, match="fatie o corte antes"):
        ed.montar_reels(tmp_path / "nao_existe.mp4", tema=TEMA, titulo="t")


# --- legenda em arquivo (.srt) ---------------------------------------------------------------------

def test_srt_no_formato_que_o_youtube_aceita(tmp_path):
    blocos = [{"texto": "primeira fala", "inicio": 0.0, "fim": 2.4},
              {"texto": "segunda fala", "inicio": 2.4, "fim": 5.0}]
    conteudo = Path(ed.escrever_srt(blocos, tmp_path / "l.srt")).read_text(encoding="utf-8")
    assert conteudo.startswith("1\n00:00:00,000 --> 00:00:02,400\nprimeira fala\n")
    assert "\n2\n00:00:02,400 --> 00:00:05,000\nsegunda fala\n" in conteudo


def test_o_srt_conta_o_tempo_do_cartao_de_abertura():
    """O .srt acompanha o vídeo final; se a capa dura 5 s, a legenda do clipe começa em 5 s."""
    assert ed._tempo_srt(0.0) == "00:00:00,000"
    assert ed._tempo_srt(3725.5) == "01:02:05,500"


def test_srt_com_deslocamento(tmp_path):
    caminho = ed.escrever_srt([{"texto": "fala", "inicio": 1.0, "fim": 2.0}], tmp_path / "l.srt", deslocamento=4.5)
    assert "00:00:05,500 --> 00:00:06,500" in Path(caminho).read_text(encoding="utf-8")


def test_o_video_montado_leva_o_srt_junto(tmp_path):
    from core.midia import localizar_ffmpeg

    clipe = _clipe_de_teste(tmp_path / "clipe.mp4", localizar_ffmpeg(), segundos=2)
    dados = ed.montar_reels(clipe, tema=TEMA, titulo="T", nome_arquivo="com_srt.mp4", pasta_saida=tmp_path,
                            legendas=[{"texto": "uma fala", "inicio": 0.2, "fim": 1.5}])
    assert Path(dados["srt"]).exists() and dados["srt"].endswith(".srt")


def test_sem_legenda_nao_sai_srt(tmp_path):
    from core.midia import localizar_ffmpeg

    clipe = _clipe_de_teste(tmp_path / "clipe.mp4", localizar_ffmpeg(), segundos=2)
    assert ed.montar_reels(clipe, tema=TEMA, titulo="T", nome_arquivo="sem_srt.mp4", pasta_saida=tmp_path)["srt"] is None


# --- capa e fecho a partir do roteiro --------------------------------------------------------------

ROTEIRO = {
    "titulos_capa": ["O erro que todo mundo comete"],
    "cenas": [{"tempo": "0s a 3s", "bloco": "Gancho", "fala": "Você faz isso errado. Todo dia.", "direcao_visual": ""},
              {"tempo": "3s a 15s", "bloco": "Dor", "fala": "E custa caro.", "direcao_visual": ""},
              {"tempo": "45s a 60s", "bloco": "CTA", "fala": "Segue pra parte dois. Tem mais.", "direcao_visual": ""}],
    "legenda_instagram": "legenda", "hashtags": "#a #b",
}


def test_o_gancho_vira_a_capa_e_o_cta_vira_o_fecho():
    capa, fecho = ed.cenas_do_roteiro(ROTEIRO, "título do corte")
    assert capa["layout"] == "titulo" and capa["titulo"] == "O erro que todo mundo comete"
    assert capa["fala"].startswith("Você faz isso errado")
    assert fecho["layout"] == "cta" and fecho["titulo"] == "Segue pra parte dois."


def test_sem_bloco_reconhecivel_usa_a_primeira_e_a_ultima_cena():
    roteiro = {"cenas": [{"bloco": "Abertura", "fala": "Primeira."}, {"bloco": "Meio", "fala": "Última."}]}
    capa, fecho = ed.cenas_do_roteiro(roteiro, "título do corte")
    assert capa["fala"] == "Primeira." and fecho["fala"] == "Última."
    assert capa["titulo"] == "título do corte"                   # sem títulos de capa, usa o do corte


def test_roteiro_degradado_nao_entra_no_video():
    """
    Sem chave (ou se a IA falhar só nessa etapa), o roteiro vira o modelo fixo da TACTO Studio. Na aba ele
    aparece como texto, com aviso; queimado na capa e no fecho, viraria propaganda de outra empresa em cima
    do vídeo de quem publica. Aconteceu em uso real antes desta guarda.
    """
    from gerador_roteiro import gerar_roteiro_viral

    modelo = gerar_roteiro_viral({"blocos": [{"texto": "vídeo sobre redes neurais"}]}, client=None)
    assert modelo["degradado"] and "TACTO Studio" in str(modelo)

    capa, fecho = ed.cenas_do_roteiro(modelo, "Como a rede enxerga um número")
    escrito = " ".join([capa["titulo"], capa["fala"], fecho["titulo"], fecho["fala"]]).lower()
    for palavra in ("tacto", "ifood", "marketplace", "restaurante", "bio"):
        assert palavra not in escrito
    assert capa["titulo"] == "Como a rede enxerga um número"      # sobra o que veio do vídeo


def test_roteiro_vazio_nao_quebra():
    capa, fecho = ed.cenas_do_roteiro({}, "sobrou só o corte")
    assert capa["titulo"] == "sobrou só o corte" and fecho["fala"] == ""


def test_as_cenas_sugeridas_passam_pela_validacao_do_renderizador():
    capa, fecho = ed.cenas_do_roteiro(ROTEIRO, "t")
    from esquemas_reels import corrigir_cena, problemas_da_cena
    corrigir_cena(capa)
    corrigir_cena(fecho)
    assert not problemas_da_cena(capa) and not problemas_da_cena(fecho)


@pytest.mark.parametrize("texto,esperado", [
    ("Uma frase. E outra.", "Uma frase."),
    ("Sem ponto final", "Sem ponto final"),
    ("", ""),
])
def test_primeira_frase(texto, esperado):
    assert ed.primeira_frase(texto) == esperado


# --- de ponta a ponta, com ffmpeg de verdade ------------------------------------------------------

def _clipe_de_teste(caminho, ffmpeg, segundos=3):
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=24:duration={segundos}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(caminho)], check=True, capture_output=True)
    return caminho


def test_monta_um_reels_inteiro_com_ffmpeg_de_verdade(tmp_path):
    """Sem rede: clipe sintético, cartões mudos. Prova que o filtro e a junção funcionam de verdade."""
    from core.midia import localizar_ffmpeg

    ffmpeg = localizar_ffmpeg()
    clipe = _clipe_de_teste(tmp_path / "clipe.mp4", ffmpeg)
    capa, fecho = ed.cenas_do_roteiro(ROTEIRO, "título do corte")
    from esquemas_reels import corrigir_cena
    corrigir_cena(capa)
    corrigir_cena(fecho)

    dados = ed.montar_reels(clipe, tema=TEMA, titulo="Um título de teste", etiqueta="corte 1", marca="@canal",
                            legendas=montar_legendas(_falas(("legenda do meio", 1.0, 1.5)), 0, 3)["blocos"],
                            capa=capa, fecho=fecho, voz=None, nome_arquivo="pronto.mp4", pasta_saida=tmp_path)
    saida = Path(dados["caminho"])
    assert saida.exists() and dados["nomes_das_partes"] == ["capa", "clipe", "chamada final"]
    info = subprocess.run([ffmpeg, "-i", str(saida)], capture_output=True, text=True, errors="ignore").stderr
    props = ed.ler_propriedades(info)
    assert (props["largura"], props["altura"]) == (1080, 1920) and props["tem_audio"]
    assert props["duracao"] == pytest.approx(dados["duracao_segundos"], abs=1.0)


def test_preencher_a_tela_tambem_monta_e_sem_cartoes_sai_so_o_clipe(tmp_path):
    from core.midia import localizar_ffmpeg

    ffmpeg = localizar_ffmpeg()
    clipe = _clipe_de_teste(tmp_path / "clipe.mp4", ffmpeg, segundos=2)
    dados = ed.montar_reels(clipe, tema=TEMA, titulo="Título", enquadramento=ed.PREENCHER,
                            nome_arquivo="cheio.mp4", pasta_saida=tmp_path)
    assert dados["nomes_das_partes"] == ["clipe"]
    info = subprocess.run([ffmpeg, "-i", dados["caminho"]], capture_output=True, text=True, errors="ignore").stderr
    assert (ed.ler_propriedades(info)["largura"], ed.ler_propriedades(info)["altura"]) == (1080, 1920)


def test_clipe_mudo_vira_reels_com_faixa_de_audio_silenciosa(tmp_path):
    """Sem isso, juntar com os cartões (que têm áudio) falha ou sai sem som no fim."""
    from core.midia import localizar_ffmpeg

    ffmpeg = localizar_ffmpeg()
    mudo = tmp_path / "mudo.mp4"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mudo)], check=True, capture_output=True)
    dados = ed.montar_reels(mudo, tema=TEMA, titulo="Sem som", nome_arquivo="mudo_pronto.mp4", pasta_saida=tmp_path)
    info = subprocess.run([ffmpeg, "-i", dados["caminho"]], capture_output=True, text=True, errors="ignore").stderr
    assert ed.ler_propriedades(info)["tem_audio"] is True
