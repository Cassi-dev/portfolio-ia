"""Direção de arte: filtro de cor, textura, zoom de ênfase, transição — e a legenda que acompanha a fala."""
import subprocess

import pytest
from PIL import Image

import editor_reels as ed
import efeitos as ef
import legendas as lg
import renderizador_generico as rg
from core.midia import localizar_ffmpeg
from temas_video import PRESETS, TEMA_PADRAO

TEMA = PRESETS[TEMA_PADRAO]
ESTILO = rg.criar_estilo(TEMA, "", None)


def bloco(texto, inicio, fim, palavras=None):
    return {"texto": texto, "inicio": inicio, "fim": fim, "palavras": palavras or []}


def _clipe(tmp_path, nome="c.mp4", segundos=3, cor="testsrc2"):
    ffmpeg = localizar_ffmpeg()
    saida = tmp_path / nome
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{cor}=size=640x360:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", str(segundos),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(saida)], check=True)
    return saida


# --- filtros de cor e textura ----------------------------------------------------------------------

def test_original_nao_mexe_na_cor():
    assert ef.filtro_de_cor(ef.SEM_ARTE) == ""


def test_filtro_desconhecido_cai_no_original():
    assert ef.filtro_de_cor(ef.DirecaoDeArte(look="nao-existe")) == ""


def test_vinheta_escurece_os_cantos_e_deixa_o_centro_intacto():
    vinheta = ed.desenhar_vinheta()
    assert vinheta.size == (ed.LARGURA, ed.ALTURA)
    assert vinheta.getpixel((ed.LARGURA // 2, ed.ALTURA // 2))[3] == 0
    assert vinheta.getpixel((2, 2))[3] > 120


def test_vinheta_entra_por_baixo_da_legenda(tmp_path):
    """Escurece a imagem, não o texto: a vinheta é a primeira arte sobreposta."""
    chamadas = []
    import subprocess as sp

    class Proc:
        returncode, stderr = 0, ""
    props = {"largura": 640, "altura": 360, "duracao": 3.0, "tem_audio": True}
    original = sp.run
    try:
        sp.run = lambda comando, **k: chamadas.append(comando) or Proc()
        ed.tratar_clipe("c.mp4", estilo=ESTILO, titulo="", legendas=[bloco("oi", 0.0, 1.0)], saida=tmp_path / "s.mp4",
                        ffmpeg="ffmpeg", pasta_arte=tmp_path, props=props, arte=ef.DirecaoDeArte(vinheta=True))
    finally:
        sp.run = original
    comando = chamadas[0]
    assert comando.index(str(tmp_path / "vinheta.png")) < comando.index("concat")


def test_todo_filtro_de_cor_roda_no_ffmpeg_desta_maquina():
    """Um nome de opção errado só aparece na hora de renderizar; aqui aparece antes."""
    ffmpeg = localizar_ffmpeg()
    for nome, (_, filtro) in ef.LOOKS.items():
        cadeia = filtro or "null"
        proc = subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5",
                               "-t", "0.4", "-vf", cadeia, "-f", "null", "-"], capture_output=True, text=True)
        assert proc.returncode == 0, f"{nome}: {proc.stderr[-300:]}"


def test_a_cor_vai_na_frente_e_no_fundo_ja_reduzidos():
    """Mesma cor nos dois (o fundo é o próprio vídeo), e pintada onde há menos pixels."""
    filtro = ed.filtro_de_composicao((960, 540, 60, 690), [], 10.0, "0x0@1", cor="hue=s=0")
    fundo = next(p for p in filtro.split(";") if p.startswith("[fundo_cru]"))
    frente = next(p for p in filtro.split(";") if p.startswith("[frente_cru]"))
    assert fundo.index("boxblur") < fundo.index("hue=s=0") < fundo.index(f"scale={ed.LARGURA}:{ed.ALTURA}")
    assert frente.index("scale=960:540") < frente.index("hue=s=0")


def test_na_tela_cheia_a_cor_vem_depois_do_corte():
    filtro = ed.filtro_de_composicao(None, [], 10.0, "0x0@1", cor="hue=s=0")
    assert filtro.index(f"crop={ed.LARGURA}:{ed.ALTURA}") < filtro.index("hue=s=0")


def test_o_video_cai_para_a_taxa_da_saida_antes_dos_filtros():
    """Fonte a 50 quadros/s: sem isso, cada filtro processava mais da metade de quadros que a saída descartava."""
    for geometria in (None, (960, 540, 60, 690)):
        assert ed.filtro_de_composicao(geometria, [], 10.0, "0x0@1").startswith(f"[0:v]fps={ed.FPS},")


# --- zoom de ênfase ----------------------------------------------------------------------------------

def test_zoom_alterna_um_bloco_sim_outro_nao():
    legendas = [bloco("a", 0.0, 1.8), bloco("b", 2.0, 3.8), bloco("c", 4.0, 5.8), bloco("d", 6.0, 7.8)]
    assert ef.janelas_de_zoom(legendas, 9.0) == [(2.0, 4.0), (6.0, 9.0)]


def test_a_janela_vai_ate_o_proximo_bloco_para_nao_mudar_no_meio_da_palavra():
    legendas = [bloco("a", 0.0, 1.0), bloco("b", 2.0, 2.5), bloco("c", 5.0, 6.0)]
    assert ef.janelas_de_zoom(legendas, 8.0) == [(2.0, 5.0)]


def test_sem_legenda_o_zoom_alterna_num_ritmo_fixo():
    assert ef.janelas_de_zoom([], 10.0, a_cada=3.0) == [(3.0, 6.0), (9.0, 10.0)]


def test_zoom_desligado_nao_acrescenta_filtro():
    assert ef.filtro_de_zoom("v0", "vz", [(1, 2)], 1.0, 1080, 1920) == ["[v0]null[vz]"]


def test_zoom_liga_so_nas_janelas_e_mantem_o_tamanho_do_quadro():
    partes = ";".join(ef.filtro_de_zoom("v0", "vz", [(1.0, 2.0), (3.0, 4.0)], 1.15, 1080, 1920))
    assert "enable='between(t,1.00,2.00)+between(t,3.00,4.00)'" in partes
    assert "scale=1080:1920" in partes and "crop=iw/1.15:ih/1.15" in partes


def test_o_zoom_nao_amplia_a_legenda():
    faixa = [{"entrada": 1, "faixa": True, "y": ed.FAIXA_Y0}]
    filtro = ed.filtro_de_composicao(None, faixa, 10.0, "0x0@1", zoom=([(1.0, 2.0)], 1.1))
    assert filtro.index("crop=iw/1.1") < filtro.index("overlay=0:960")


# --- transições --------------------------------------------------------------------------------------

def test_corte_seco_e_um_trecho_so_nao_usam_transicao():
    assert not ef.usa_transicao(ef.SEM_ARTE, [5, 5])
    assert not ef.usa_transicao(ef.DirecaoDeArte(transicao="fade"), [5])


def test_trecho_curto_demais_para_ceder_a_passagem_desliga_a_transicao():
    assert not ef.usa_transicao(ef.DirecaoDeArte(transicao="fade"), [5, 0.5])
    assert ef.usa_transicao(ef.DirecaoDeArte(transicao="fade"), [5, 3])


def test_cada_transicao_come_um_pedaco_do_trecho_anterior():
    assert ef.inicios_com_transicao([10, 8, 6], d=0.5) == [0.0, 9.5, 17.0]


def test_filtro_de_transicao_encadeia_video_e_audio():
    filtro = ef.filtro_de_transicoes([10, 8, 6], "fadewhite", d=0.5)
    assert "xfade=transition=fadewhite:duration=0.500:offset=9.500" in filtro
    assert "offset=17.000" in filtro and filtro.count("acrossfade") == 2
    assert filtro.endswith("[afinal]")


# --- legenda palavra a palavra ----------------------------------------------------------------------

def test_quando_a_contagem_bate_vale_o_tempo_do_audio():
    ouvidas = [{"texto": "a", "inicio": 0.0, "fim": 0.4}, {"texto": "b", "inicio": 0.5, "fim": 1.0}]
    tempos = lg.tempos_das_palavras(bloco("A, B.", 0.0, 1.5, ouvidas))
    assert [t["texto"] for t in tempos] == ["A,", "B."] and tempos[1]["inicio"] == 0.5


def test_texto_traduzido_reparte_o_tempo_falado_pelas_palavras():
    ouvidas = [{"texto": "oi", "inicio": 1.0, "fim": 1.5}, {"texto": "gente", "inicio": 1.5, "fim": 3.0}]
    tempos = lg.tempos_das_palavras(bloco("hello there everyone", 1.0, 3.5, ouvidas))
    assert len(tempos) == 3 and tempos[0]["inicio"] == 1.0 and tempos[-1]["fim"] == pytest.approx(3.0)
    assert tempos[0]["fim"] <= tempos[1]["inicio"] <= tempos[2]["inicio"]


def test_bloco_sem_palavras_guardadas_usa_o_proprio_intervalo():
    tempos = lg.tempos_das_palavras(bloco("duas palavras", 2.0, 4.0))
    assert tempos[0]["inicio"] == 2.0 and tempos[-1]["fim"] <= 4.0


def test_os_blocos_levam_o_tempo_de_cada_palavra():
    palavras = lg.palavras_com_tempo([{"texto": "uma frase curta.", "start": 0.0, "dur": 2.0}])
    assert len(lg.agrupar_palavras(palavras)[0]["palavras"]) == 3


def test_impacto_parte_em_ate_tres_palavras_e_respeita_a_virgula():
    pedacos = lg.em_pedacos_curtos(bloco("Não, espera um pouco aqui agora", 0.0, 3.0))
    assert [p["texto"] for p in pedacos] == ["Não,", "espera um pouco", "aqui agora"]
    assert all(a["fim"] <= b["inicio"] + 1e-9 for a, b in zip(pedacos, pedacos[1:]))


def test_classica_tem_um_estado_por_bloco():
    estados = ed.estados_da_legenda([bloco("um dois", 0, 1), bloco("tres", 1.2, 2)], ed.CLASSICA)
    assert len(estados) == 2 and all(e["destaque"] is None for e in estados)


def test_destaque_tem_um_estado_por_palavra_sem_buraco_entre_elas():
    estados = ed.estados_da_legenda([bloco("um dois tres", 0.0, 3.0)], ed.DESTAQUE)
    assert [e["destaque"] for e in estados] == [0, 1, 2]
    assert estados[0]["fim"] == estados[1]["inicio"] and estados[-1]["fim"] == 3.0


def test_impacto_sai_em_caixa_alta_e_em_pedacos():
    estados = ed.estados_da_legenda([bloco("um dois tres quatro", 0.0, 4.0)], ed.IMPACTO)
    assert all(e["impacto"] for e in estados) and {e["texto"] for e in estados} == {"um dois tres", "quatro"}


def test_a_palavra_da_vez_sai_na_cor_de_destaque():
    img = ed.desenhar_legenda(ESTILO, "palavra outra", destaque=0).convert("RGB")
    cores = {c for _, c in img.getcolors(1_000_000)}
    assert tuple(ESTILO.destaque) in cores
    assert tuple(ESTILO.destaque) not in {c for _, c in ed.desenhar_legenda(ESTILO, "palavra outra").convert("RGB").getcolors(1_000_000)}


def test_a_faixa_cobre_o_clipe_inteiro_com_vazios_entre_os_blocos(tmp_path):
    faixa = ed.faixa_de_legendas([bloco("um", 1.0, 2.0), bloco("dois", 3.0, 4.0)], ESTILO, tmp_path, 6.0)
    linhas = faixa.lista.read_text(encoding="utf-8").splitlines()
    duracoes = [float(l.split()[1]) for l in linhas if l.startswith("duration")]
    assert sum(duracoes) == pytest.approx(6.0)
    assert duracoes == pytest.approx([1.0, 1.0, 1.0, 1.0, 2.0])      # vazio, um, vazio, dois, vazio
    assert linhas[-1].endswith("legenda_vazia.png'")                 # o último se repete, senão o concat o ignora


def test_estado_repetido_reaproveita_o_png(tmp_path):
    ed.faixa_de_legendas([bloco("igual", 0.0, 1.0), bloco("igual", 2.0, 3.0)], ESTILO, tmp_path, 4.0)
    assert len(list(tmp_path.glob("legenda_0*.png"))) == 1


def test_estado_mais_curto_que_um_quadro_e_descartado(tmp_path):
    faixa = ed.faixa_de_legendas([bloco("um", 0.0, 0.01), bloco("dois", 1.0, 2.0)], ESTILO, tmp_path, 3.0)
    assert len(list(tmp_path.glob("legenda_0*.png"))) == 1 and faixa is not None


def test_sem_legenda_nao_ha_faixa(tmp_path):
    assert ed.faixa_de_legendas([], ESTILO, tmp_path, 3.0) is None


def test_a_faixa_entra_pelo_concat_e_nao_como_imagem():
    comando = ed.comando_de_composicao("ffmpeg", "c.mp4", [ed.FaixaDeImagens(__import__("pathlib").Path("l.ffconcat"))],
                                       "F", 5.0, "s.mp4", tem_audio=True)
    i = comando.index("l.ffconcat")
    assert comando[i - 5:i] == ["-f", "concat", "-safe", "0", "-i"]


def test_a_previa_grava_um_quadro_so_e_sem_som():
    comando = ed.comando_de_composicao("ffmpeg", "c.mp4", [], "F", 5.0, "p.png", tem_audio=True, previa_em=2.5)
    assert comando[-5:] == ["-ss", "2.500", "-frames:v", "1", "p.png"] and "-c:a" not in comando


# --- com ffmpeg de verdade -------------------------------------------------------------------------

def test_previa_sai_em_9x16_com_a_legenda_desenhada(tmp_path):
    clipe = _clipe(tmp_path)
    quadro = ed.previa(clipe, tema=TEMA, em=1.0, legendas=[bloco("legenda visível", 0.5, 2.5)],
                       arte=ef.DirecaoDeArte(look="pb"), estilo_legenda=ed.DESTAQUE)
    assert quadro.size == (1080, 1920)
    faixa = quadro.crop((0, ed.FAIXA_Y0, 1080, ed.BASE_LEGENDA))
    assert faixa.getextrema() != ((0, 0), (0, 0), (0, 0))


def test_monta_com_karaoke_cor_zoom_e_textura(tmp_path):
    clipe = _clipe(tmp_path)
    legendas = lg.agrupar_palavras(lg.palavras_com_tempo(
        [{"texto": "primeira frase aqui.", "start": 0.0, "dur": 1.4}, {"texto": "segunda frase.", "start": 1.5, "dur": 1.4}]))
    arte = ef.DirecaoDeArte(look="cinema", vinheta=True, zoom="forte")
    dados = ed.montar_reels(clipe, tema=TEMA, titulo="", legendas=legendas, arte=arte, estilo_legenda=ed.IMPACTO,
                            nome_arquivo="k.mp4", pasta_saida=tmp_path / "saida")
    props = ed.sondar_clipe(dados["caminho"], localizar_ffmpeg())
    assert (props["largura"], props["altura"]) == (1080, 1920) and props["duracao"] == pytest.approx(3.0, abs=0.15)


def test_edicao_com_transicao_encurta_a_peca_e_desloca_a_legenda(tmp_path):
    a, b = _clipe(tmp_path, "a.mp4", 3), _clipe(tmp_path, "b.mp4", 3, cor="smptebars")
    trechos = [{"clipe": a, "legendas": [bloco("um", 0.5, 1.5)]}, {"clipe": b, "legendas": [bloco("dois", 0.5, 1.5)]}]
    dados = ed.montar_edicao(trechos, tema=TEMA, arte=ef.DirecaoDeArte(transicao="fadewhite"),
                             nome_arquivo="t.mp4", pasta_saida=tmp_path / "saida")
    assert dados["transicao"] == "fadewhite"
    assert dados["duracao_segundos"] == pytest.approx(6.0 - ef.DURACAO_TRANSICAO, abs=0.05)
    real = ed.sondar_clipe(dados["caminho"], localizar_ffmpeg())["duracao"]
    assert real == pytest.approx(6.0 - ef.DURACAO_TRANSICAO, abs=0.15)
    srt = (tmp_path / "saida" / "t.srt").read_text(encoding="utf-8")
    assert "00:00:03,150 --> 00:00:04,150" in srt                    # 0,5 s depois do início do trecho 2 (2,65 s)
