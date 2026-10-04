"""
Encontrar e apagar a marca d'água que já vem queimada no vídeo de origem.

Como encontrar, sem saber onde ela está: **o contorno da marca é o mesmo em todo quadro; o do conteúdo, não.**
Amostrando quadros ao longo do clipe, calcula-se em cada um a diferença entre pixels vizinhos (o gradiente,
com sinal) e tira-se a mediana no tempo. Onde o vídeo muda, o sinal do gradiente muda junto e a mediana cai
para perto de zero. Na marca, o gradiente aponta sempre para o mesmo lado e sobrevive. É o método de Dekel e
outros ("On the Effectiveness of Visible Watermarks", CVPR 2017).

A primeira versão deste módulo procurava pixels *parados* (variação baixa no tempo). Falhou no primeiro vídeo
real testado: a marca era semitransparente, então o fundo mudando por baixo dela a fazia variar tanto quanto
o resto. A mediana do gradiente não depende disso — a borda da marca continua no mesmo lugar.

Medido em 9 clipes reais de 5 vídeos: a marca "YOUTUBE | BLEACH BRASILEIRO" (semitransparente, recuada do canto)
foi achada nos 3 clipes que a tinham, com a caixa cobrindo a marca inteira; nos 6 sem marca, nada foi acusado.
É uma amostra pequena — por isso a tela mostra onde a caixa caiu antes de montar.

Como apagar: o filtro `delogo` do ffmpeg interpola a região a partir da borda. Ele **não reconstrói** o que
estava embaixo; em fundo liso some, em fundo detalhado deixa um borrão.

Sobre direito: apagar a marca de um canal e republicar o vídeo dele é problema de direito autoral, não de
código. Isto existe para tirar marca do seu próprio material, ou de material licenciado.
"""
import io
import subprocess

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

LARGURA_ANALISE = 640          # texto de marca tem traço fino: em 320 px ele some junto com o ruído
QUADROS = 40
LIMIAR_BORDA = 4.0             # mediana do gradiente acima disso (em níveis de cinza) é borda que não se mexe
JUNTAR = (5, 9)                # engorda as bordas para as letras de uma palavra virarem uma mancha só
PIXELS_MINIMOS = 0.0003        # fração do quadro com borda fixa que a mancha precisa ter
AREA_MAXIMA = 0.15             # caixa maior que isso não é marca, é conteúdo parado
PROPORCAO_MAXIMA = 12.0        # mais comprida que isso é linha (borda de tarja preta), não marca
MIOLO_MINIMO = 0.05            # retângulo liso parado só tem borda no contorno; marca tem desenho dentro
PARADO_DEMAIS = 0.06           # se tanto do quadro tem borda fixa, o vídeo mal se mexe: não dá para separar
MARGEM = 0.30                  # marca fica perto da borda; o que está no meio da tela é conteúdo
FOLGA = 3                      # píxeis (na escala da análise) a mais em volta, para pegar a borda da marca
APARAR = 0.15                  # linha ou coluna da caixa com menos borda que isso (em relação à mais cheia) sai
SOBRA_CURTA = 8                # ... mas só se a ponta fraca for mais comprida que isso (escala da análise)
PERTO = 0.04                   # peças da marca (ícone, texto) a menos disso, em fração da largura, são uma só

# Como o usuário quer tratar a marca.
AUTOMATICO, MANUAL, SEM_MARCA = "auto", "manual", "nenhum"
MODOS = {AUTOMATICO: "Procurar e apagar, se houver", MANUAL: "Eu marco onde está", SEM_MARCA: "Não apagar"}


# ==============================================================================
# AMOSTRAGEM
# ==============================================================================
def amostrar_quadros(clipe, ffmpeg: str, duracao: float, tamanho, quantos: int = QUADROS,
                     largura: int = LARGURA_ANALISE) -> np.ndarray:
    """
    `quantos` quadros em cinza, espalhados pelo clipe inteiro (e não os primeiros segundos: uma cena longa
    no começo faria o conteúdo parecer tão fixo quanto a marca). Devolve um array (n, altura, largura).
    """
    altura = max(2, int(round(tamanho[1] * largura / tamanho[0] / 2)) * 2)
    fps = quantos / max(1.0, float(duracao))
    proc = subprocess.run(
        [ffmpeg, "-loglevel", "error", "-i", str(clipe), "-vf",
         f"fps={fps:.5f},scale={largura}:{altura},format=gray", "-frames:v", str(quantos),
         "-f", "rawvideo", "-"],
        capture_output=True)
    n = len(proc.stdout) // (largura * altura)
    return np.frombuffer(proc.stdout[:n * largura * altura], np.uint8).reshape(n, altura, largura).astype(np.float32)


# ==============================================================================
# DETECÇÃO
# ==============================================================================
def bordas_fixas(quadros) -> np.ndarray:
    """Módulo da mediana, no tempo, do gradiente com sinal. Alto só onde a borda não muda entre os quadros."""
    pilha = np.asarray(quadros, dtype=np.float32)
    gx = np.zeros_like(pilha)
    gy = np.zeros_like(pilha)
    gx[:, :, :-1] = np.diff(pilha, axis=2)
    gy[:, :-1, :] = np.diff(pilha, axis=1)
    return np.hypot(np.median(gx, axis=0), np.median(gy, axis=0))


def _e_marca(caixa, mascara, altura: int, largura: int) -> bool:
    fy, fx = caixa
    alto, largo = fy.stop - fy.start, fx.stop - fx.start
    if alto * largo > AREA_MAXIMA * altura * largura:
        return False
    if max(alto / largo, largo / alto) > PROPORCAO_MAXIMA:
        return False
    cy, cx = (fy.start + fy.stop) / 2 / altura, (fx.start + fx.stop) / 2 / largura
    if MARGEM < cy < 1 - MARGEM and MARGEM < cx < 1 - MARGEM:
        return False
    my, mx = alto // 4, largo // 4
    miolo = mascara[fy.start + my:fy.stop - my, fx.start + mx:fx.stop - mx]
    return miolo.size > 0 and miolo.mean() >= MIOLO_MINIMO


def _juntar_vizinhas(caixa, outras, distancia: float) -> tuple:
    """
    Marca costuma ter peças separadas — ícone, texto, um separador — que viram manchas diferentes. As que
    passaram no teste de marca e estão a menos de `distancia` da escolhida entram na mesma caixa; senão o
    delogo apagaria o texto e deixaria o ícone.
    """
    fy, fx = caixa
    mudou = True
    while mudou:
        mudou = False
        for oy, ox in list(outras):
            longe_x = max(ox.start - fx.stop, fx.start - ox.stop)
            longe_y = max(oy.start - fy.stop, fy.start - oy.stop)
            if longe_x <= distancia and longe_y <= distancia:
                fy = slice(min(fy.start, oy.start), max(fy.stop, oy.stop))
                fx = slice(min(fx.start, ox.start), max(fx.stop, ox.stop))
                outras.remove((oy, ox))
                mudou = True
    return fy, fx


def _aparar(caixa, mascara, fracao: float = APARAR, sobra_curta: int = SOBRA_CURTA) -> tuple:
    """
    Tira da caixa as pontas com pouca borda. Num clipe curto e parado, um contorno do conteúdo pode encostar
    na marca e virar a mesma mancha; ele é fino, a marca é densa, e o perfil separa os dois.

    Só sai ponta comprida. Ponta curta é quase sempre a própria marca: no primeiro vídeo testado, o traço
    vertical entre "YOUTUBE" e "BLEACH" passa alguns píxeis acima e abaixo das letras; aparado, ele ficou na
    borda da caixa, e o delogo — que preenche a caixa a partir da borda — o esticou por cima de tudo.
    """
    def pontas(perfil, inicio):
        fortes = np.flatnonzero(perfil >= fracao * perfil.max())
        # a ponta aparada ainda deixa `sobra_curta` junto do miolo, pelo mesmo motivo do traço
        comeco = max(0, fortes[0] - sobra_curta)
        fim = min(len(perfil), fortes[-1] + 1 + sobra_curta)
        return slice(inicio + comeco, inicio + fim)

    fy, fx = caixa
    trecho = mascara[fy, fx]
    return pontas(trecho.sum(axis=1), fy.start), pontas(trecho.sum(axis=0), fx.start)


def detectar(quadros, tamanho_original=None) -> tuple | None:
    """
    Devolve (x, y, largura, altura) na escala do vídeo original, ou None se não houver marca.

    Das manchas de borda fixa, fica a de mais "massa" (soma da força das bordas) entre as que têm cara de
    marca: nem linha, nem enorme, nem no meio da tela, e com desenho dentro.
    """
    if len(quadros) < 8:                        # com poucos quadros, a mediana não separa nada
        return None
    forca = bordas_fixas(quadros)
    altura, largura = forca.shape
    mascara = forca >= LIMIAR_BORDA
    if mascara.mean() > PARADO_DEMAIS:
        return None
    manchas, quantas = ndimage.label(ndimage.binary_dilation(mascara, np.ones(JUNTAR)))
    if not quantas:
        return None
    caixas = ndimage.find_objects(manchas)
    rotulos = range(1, quantas + 1)
    massa = ndimage.sum_labels(forca * mascara, manchas, rotulos)
    pixels = ndimage.sum_labels(mascara, manchas, rotulos)

    minimo = PIXELS_MINIMOS * altura * largura
    candidatas = [(m, c) for m, p, c in zip(massa, pixels, caixas)
                  if p >= minimo and _e_marca(c, mascara, altura, largura)]
    if not candidatas:
        return None
    candidatas.sort(key=lambda mc: -mc[0])
    fy, fx = _juntar_vizinhas(candidatas[0][1], [c for _, c in candidatas[1:]], PERTO * largura)
    fy, fx = _aparar((fy, fx), mascara)

    ex, ey = 1.0, 1.0
    if tamanho_original:
        ex, ey = tamanho_original[0] / largura, tamanho_original[1] / altura
    x0, y0 = max(0, fx.start - FOLGA), max(0, fy.start - FOLGA)
    x1, y1 = min(largura, fx.stop + FOLGA), min(altura, fy.stop + FOLGA)
    return int(x0 * ex), int(y0 * ey), int((x1 - x0) * ex), int((y1 - y0) * ey)


def procurar(clipe, ffmpeg: str, props: dict) -> tuple | None:
    """`props` é o que editor_reels.sondar_clipe devolve (largura, altura, duração)."""
    tamanho = (props["largura"], props["altura"])
    return detectar(amostrar_quadros(clipe, ffmpeg, props["duracao"], tamanho), tamanho)


# ==============================================================================
# REGIÃO ESCOLHIDA À MÃO E O FILTRO
# ==============================================================================
def regiao_manual(x: float, y: float, largura: float, altura: float, tamanho) -> tuple:
    """Caixa em píxeis a partir de frações do quadro (0,10 = 10%). Sempre inteira dentro do vídeo."""
    lv, av = tamanho
    w, h = max(2, int(lv * largura)), max(2, int(av * altura))
    return min(max(0, int(lv * x)), lv - w), min(max(0, int(av * y)), av - h), w, h


def em_fracoes(regiao, tamanho) -> dict:
    """O inverso de regiao_manual: para pré-preencher os controles com o que a detecção achou."""
    x, y, w, h = regiao
    lv, av = tamanho
    return {"x": x / lv, "y": y / av, "largura": w / lv, "altura": h / av}


def filtro_delogo(regiao, tamanho) -> str:
    """
    Filtro do ffmpeg que apaga a região. O delogo exige a caixa inteiramente dentro do quadro e com pelo
    menos 1 pixel de sobra em cada lado — fora disso ele aborta a renderização.
    """
    largura_video, altura_video = tamanho
    x, y, w, h = regiao
    x, y = max(1, int(x)), max(1, int(y))
    w = max(1, min(int(w), largura_video - x - 1))
    h = max(1, min(int(h), altura_video - y - 1))
    return f"delogo=x={x}:y={y}:w={w}:h={h}"


def quadro_do_clipe(clipe, ffmpeg: str, em: float) -> Image.Image | None:
    proc = subprocess.run([ffmpeg, "-loglevel", "error", "-ss", f"{max(0.0, em):.2f}", "-i", str(clipe),
                           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        return None
    return Image.open(io.BytesIO(proc.stdout)).convert("RGB")


def marcar_regiao(quadro: Image.Image, regiao) -> Image.Image:
    """O quadro com a caixa que vai ser apagada desenhada por cima — para conferir antes de montar."""
    copia = quadro.copy()
    x, y, w, h = regiao
    espessura = max(3, copia.width // 320)
    ImageDraw.Draw(copia).rectangle([x, y, x + w, y + h], outline=(255, 40, 40), width=espessura)
    return copia
