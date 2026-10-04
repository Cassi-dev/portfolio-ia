"""Apagar a marca d'água que vem queimada no vídeo de origem."""
import numpy as np
import pytest
from PIL import Image
from scipy import ndimage

import editor_reels as ed
import marca_dagua as md

TAMANHO = (1920, 1080)
ALT, LARG = 180, 320                       # quadros de teste pequenos; a escala para o original é 6x


def _fundo(aleatorio):
    """
    Conteúdo que muda a cada quadro, mas liso como vídeo de verdade: ruído puro teria borda em todo lugar.
    Com desfoque menor (sigma 6) o fundo sintético já passa a ter 1,8% de "borda fixa" por acaso e aparece
    alarme falso — o vídeo real medido é mais liso que isso, mas fica registrado onde o método tem limite.
    """
    ruido = ndimage.gaussian_filter(aleatorio.normal(size=(ALT, LARG)), 8)
    return (128 + ruido / ruido.std() * 45).clip(0, 255)


def _desenho_da_marca():
    """Letras (traços finos) e um separador vertical mais alto que elas — como "YOUTUBE | BLEACH"."""
    m = np.zeros((ALT, LARG), bool)
    for x in range(40, 100, 5):
        m[130:144, x:x + 2] = True
    m[126:148, 104:106] = True
    return m


def _quadros(n=20, marca=None, alfa=0.35, semente=7, fundo=None):
    aleatorio = np.random.default_rng(semente)
    quadros = []
    for _ in range(n):
        q = _fundo(aleatorio) if fundo is None else fundo.copy()
        if marca is not None:
            q = np.where(marca, (1 - alfa) * q + alfa * 230, q)          # semitransparente: o fundo vaza
        quadros.append(q.astype(np.float32))
    return quadros


# --- a detecção ------------------------------------------------------------------------------------

def test_acha_marca_semitransparente_sobre_fundo_que_muda():
    """O caso que a primeira versão errou: o fundo muda por baixo da marca, então ela não fica 'parada'."""
    achado = md.detectar(_quadros(marca=_desenho_da_marca()), TAMANHO)
    assert achado is not None
    x, y, w, h = achado
    assert x <= 40 * 6 and x + w >= 106 * 6                  # cobre da primeira letra ao separador
    assert y <= 126 * 6 and y + h >= 148 * 6                 # inclusive o traço que passa das letras


def test_a_caixa_nao_engole_meio_video():
    x, y, w, h = md.detectar(_quadros(marca=_desenho_da_marca()), TAMANHO)
    assert w * h < 0.05 * TAMANHO[0] * TAMANHO[1]


def test_video_sem_marca_nao_acusa_nada():
    assert md.detectar(_quadros(), TAMANHO) is None


def test_video_parado_nao_da_conclusao():
    """Com a mesma imagem em todo quadro, tudo é 'borda fixa' — não há como separar marca de conteúdo."""
    parado = _fundo(np.random.default_rng(1))
    assert md.detectar(_quadros(fundo=parado, marca=_desenho_da_marca()), TAMANHO) is None


def test_retangulo_liso_parado_nao_e_marca():
    """Tarja preta e caixa lisa têm borda fixa só no contorno; marca tem desenho dentro."""
    bloco = np.zeros((ALT, LARG), bool)
    bloco[125:165, 20:120] = True
    assert md.detectar(_quadros(marca=bloco, alfa=1.0), TAMANHO) is None


def test_linha_de_tarja_nao_e_marca():
    linha = np.zeros((ALT, LARG), bool)
    linha[175:177, :] = True
    assert md.detectar(_quadros(marca=linha, alfa=1.0), TAMANHO) is None


def test_desenho_no_meio_da_tela_e_conteudo():
    meio = np.zeros((ALT, LARG), bool)
    for x in range(140, 180, 5):
        meio[84:96, x:x + 2] = True
    assert md.detectar(_quadros(marca=meio), TAMANHO) is None


def test_poucos_quadros_nao_dao_conclusao():
    assert md.detectar(_quadros(n=4, marca=_desenho_da_marca()), TAMANHO) is None
    assert md.detectar([], TAMANHO) is None


def test_ponta_comprida_e_fraca_sai_da_caixa_e_a_curta_fica():
    """Contorno do conteúdo encostado na marca sai; o traço que passa um pouco das letras fica."""
    mascara = np.zeros((100, 100), bool)
    mascara[40:50, 10:60] = True                 # miolo denso
    mascara[50:90, 30] = True                    # ponta fina e comprida para baixo (conteúdo)
    mascara[37:40, 58] = True                    # ponta fina e curta para cima (o traço da marca)
    fy, fx = md._aparar((slice(37, 90), slice(10, 60)), mascara)
    assert fy.start == 37                        # a curta ficou
    assert fy.stop < 70                          # a comprida foi embora
    assert fy.stop >= 50                         # ... sem comer o miolo


# --- a região escolhida à mão ------------------------------------------------------------------------

def test_regiao_manual_em_fracoes_do_quadro():
    assert md.regiao_manual(0.10, 0.75, 0.20, 0.10, TAMANHO) == (192, 810, 384, 108)


def test_regiao_manual_nunca_sai_do_quadro():
    x, y, w, h = md.regiao_manual(0.95, 0.95, 0.30, 0.30, TAMANHO)
    assert x + w <= TAMANHO[0] and y + h <= TAMANHO[1] and x >= 0 and y >= 0


def test_em_fracoes_desfaz_a_regiao_manual():
    regiao = md.regiao_manual(0.10, 0.75, 0.20, 0.10, TAMANHO)
    assert md.em_fracoes(regiao, TAMANHO) == pytest.approx({"x": 0.10, "y": 0.75, "largura": 0.20, "altura": 0.10})


def test_a_caixa_e_desenhada_por_cima_do_quadro_para_conferir():
    quadro = Image.new("RGB", (192, 108), (0, 0, 0))
    marcado = md.marcar_regiao(quadro, (20, 30, 50, 20))
    assert marcado.getpixel((20, 40))[0] > 200 and marcado.getpixel((100, 100)) == (0, 0, 0)
    assert quadro.getpixel((20, 40)) == (0, 0, 0)            # o original não é alterado


def test_os_modos_tem_o_automatico_como_opcao():
    assert set(md.MODOS) == {md.AUTOMATICO, md.MANUAL, md.SEM_MARCA}


# --- o filtro do ffmpeg ----------------------------------------------------------------------------

def test_o_filtro_sai_no_formato_do_delogo():
    assert md.filtro_delogo((100, 200, 300, 50), TAMANHO) == "delogo=x=100:y=200:w=300:h=50"


def test_a_caixa_nunca_encosta_na_borda():
    """O delogo aborta a renderização se a região tocar o limite do quadro."""
    filtro = md.filtro_delogo((0, 0, 5000, 5000), TAMANHO)
    valores = dict(p.split("=") for p in filtro.replace("delogo=", "").split(":"))
    assert int(valores["x"]) >= 1 and int(valores["y"]) >= 1
    assert int(valores["x"]) + int(valores["w"]) < TAMANHO[0]
    assert int(valores["y"]) + int(valores["h"]) < TAMANHO[1]


def test_o_delogo_entra_antes_de_reduzir_o_video():
    """Apagar no tamanho original preserva detalhe; e no modo desfocado a marca apareceria também no fundo."""
    filtro = ed.filtro_de_composicao(None, [], 10.0, "0x0@1", delogo="delogo=x=1:y=2:w=3:h=4")
    assert filtro.startswith(f"[0:v]delogo=x=1:y=2:w=3:h=4,fps={ed.FPS},scale=")

    com_fundo = ed.filtro_de_composicao((960, 540, 60, 690), [], 10.0, "0x0@1", delogo="delogo=x=1:y=2:w=3:h=4")
    assert com_fundo.startswith(f"[0:v]delogo=x=1:y=2:w=3:h=4,fps={ed.FPS},split=2")


def test_sem_marca_o_filtro_fica_como_era():
    assert ed.filtro_de_composicao(None, [], 10.0, "0x0@1").startswith(f"[0:v]fps={ed.FPS},scale=")


# --- de ponta a ponta, com ffmpeg de verdade -------------------------------------------------------

def test_procura_num_clipe_de_verdade(tmp_path):
    """Grava um clipe com marca e confere que a amostragem pelo ffmpeg chega ao mesmo resultado."""
    from core.midia import localizar_ffmpeg
    import subprocess
    ffmpeg = localizar_ffmpeg()
    pasta = tmp_path / "q"
    pasta.mkdir()
    for i, q in enumerate(_quadros(n=24, marca=_desenho_da_marca())):
        Image.fromarray(q.astype(np.uint8)).convert("RGB").save(pasta / f"{i:03d}.png")
    clipe = tmp_path / "c.mp4"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "2", "-i", str(pasta / "%03d.png"),
                    "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(clipe)], check=True)
    props = ed.sondar_clipe(clipe, ffmpeg)
    achado = md.procurar(clipe, ffmpeg, props)
    assert achado is not None
    x, y, w, h = achado
    assert x <= 40 and x + w >= 106 and y <= 126 and y + h >= 148
