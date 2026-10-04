"""
Renderizador de vídeos verticais (1080x1920, 24 fps) para QUALQUER assunto: recebe um plano de cenas (esquemas_reels),
um tema visual e devolve um .mp4 com locução neural opcional.

Diferenças em relação ao renderizador oficial da TACTO (renderizador_video_tacto.py, que segue intacto):
  - nada de texto, número ou logo fixo no código: tudo vem do plano e do tema
  - 5 layouts (titulo, lista, numero, comparacao, cta) escolhidos cena a cena
  - o texto é medido e ajustado (tamanho e linhas) para nunca sair do cartão; emojis são removidos da tela
  - a legenda percorre a fala inteira em blocos, em vez de cortar depois da 4ª linha
  - os quadros vão direto para o ffmpeg por pipe: não há PNGs temporários, e a pasta temporária é apagada mesmo com erro
"""
import asyncio
import math
import random
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.midia import localizar_ffmpeg
from temas_video import Tema, cor_sobre, misturar

LARGURA, ALTURA, FPS = 1080, 1920, 24
FADE_QUADROS = int(0.4 * FPS)
PAUSA_FINAL_CENA = 0.35                # respiro depois da locução, em segundos
DURACAO_MINIMA_CENA = 2.5
PALAVRAS_POR_SEGUNDO = 2.6             # ritmo médio da locução em português
DIRETORIO = Path(__file__).resolve().parent
PASTA_ASSETS = DIRETORIO / "assets_tacto"
PASTA_SAIDA = DIRETORIO / "videos_gerados" / "livre"
VOZES = {"pt-BR-AntonioNeural": "Antonio (masculina, firme)", "pt-BR-FranciscaNeural": "Francisca (feminina, expressiva)"}


class FalhaRenderizacao(RuntimeError):
    """Algo impediu de gerar o vídeo (voz, ffmpeg ou arquivo); a mensagem diz o que e como contornar."""


# ==============================================================================
# TEXTO: fontes, limpeza, quebra de linha e ajuste de tamanho
# ==============================================================================
_FONTES = {
    True: ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
           "DejaVuSans-Bold.ttf", "arialbd.ttf"],
    False: ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
            "DejaVuSans.ttf", "arial.ttf"],
}


@lru_cache(maxsize=None)
def fonte(negrito: bool, tamanho: int) -> ImageFont.FreeTypeFont:
    for caminho in _FONTES[negrito]:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


# Escritas que as fontes do vídeo (Segoe, Arial, DejaVu) não têm: hebraico, árabe, tailandês, chinês, japonês,
# coreano. A legenda automática do YouTube às vezes solta um pedaço delas no meio do português ("가사주") — no
# vídeo, isso virava uma fileira de quadradinhos.
ESCRITAS_SEM_FONTE = ((0x0590, 0x08FF), (0x0E00, 0x0E7F), (0x1100, 0x11FF), (0x2E80, 0x9FFF),
                      (0xAC00, 0xD7AF), (0xF900, 0xFAFF), (0xFF00, 0xFFEF))


def desenhavel(c: str) -> bool:
    return not any(a <= ord(c) <= b for a, b in ESCRITAS_SEM_FONTE)


def limpar_para_tela(texto: str) -> str:
    """
    Tira emojis, caracteres invisíveis e escritas sem fonte (viram quadradinho no vídeo); mantém acentos e
    moedas.
    """
    saida = []
    for c in str(texto):
        if ord(c) > 0xFFFF or ord(c) in (0xFE0F, 0x200D) or unicodedata.category(c) in ("So", "Cs", "Cf", "Co", "Cn"):
            continue
        if not desenhavel(c):
            continue
        saida.append(" " if c in "\n\r\t" or unicodedata.category(c) == "Cc" else c)
    return " ".join("".join(saida).split())


def quebrar(texto: str, f: ImageFont.FreeTypeFont, largura: int) -> list[str]:
    """Quebra por palavras sem passar da largura; palavra maior que a linha é partida por caracteres."""
    linhas, atual = [], ""
    for palavra in texto.split():
        while f.getlength(palavra) > largura and len(palavra) > 1:
            corte = next((i for i in range(len(palavra), 0, -1) if f.getlength(palavra[:i]) <= largura), 1)
            if atual:
                linhas.append(atual)
                atual = ""
            linhas.append(palavra[:corte])
            palavra = palavra[corte:]
        teste = f"{atual} {palavra}".strip()
        if f.getlength(teste) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def ajustar(texto: str, negrito: bool, tamanhos: tuple, largura: int, max_linhas: int):
    """Maior tamanho da lista em que o texto cabe em `max_linhas`; no menor, corta a última linha com reticências."""
    texto = limpar_para_tela(texto)
    for t in tamanhos:
        f = fonte(negrito, t)
        linhas = quebrar(texto, f, largura)
        if len(linhas) <= max_linhas:
            return f, linhas
    f = fonte(negrito, tamanhos[-1])
    linhas = quebrar(texto, f, largura)[:max_linhas]
    if linhas:
        ultima = linhas[-1]
        while ultima and f.getlength(ultima + "…") > largura:
            ultima = ultima[:-1]
        linhas[-1] = ultima.rstrip() + "…"
    return f, linhas


def altura_linha(f) -> int:
    return int(f.size * 1.25)


def desenhar_linhas(draw, x, y, linhas, f, cor, centralizar=False, contorno=0, cor_contorno=None) -> int:
    """
    Desenha as linhas de cima para baixo; devolve o y logo abaixo da última.
    `contorno` desenha uma borda em volta das letras — é o que deixa texto legível direto sobre a imagem,
    sem cartão atrás.
    """
    for linha in linhas:
        draw.text((x, y), linha, font=f, fill=cor, anchor="ma" if centralizar else "la",
                  stroke_width=contorno, stroke_fill=cor_contorno)
        y += altura_linha(f)
    return y


# ==============================================================================
# NÚMERO ANIMADO E LEGENDA
# ==============================================================================
_PADRAO_VALOR = re.compile(r"(\D*?)(\d[\d.,]*\d|\d)(\D*)")


def _formatar_br(valor: float, casas: int) -> str:
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def valor_animado(valor: str, t: float) -> str:
    """
    "R$ 50.000" com t=0,5 vira "R$ 25.000"; com t>=1 devolve o texto original. Valores que não são "prefixo, um número,
    sufixo" (ex.: "2 a 3 dias") ficam parados, sem animação.
    """
    valor = limpar_para_tela(valor)
    if t >= 1:
        return valor
    m = _PADRAO_VALOR.fullmatch(valor)
    if not m:
        return valor
    prefixo, numero, sufixo = m.groups()
    if "," in numero:
        inteiro, decimais = numero.rsplit(",", 1)
        alvo, casas = float(inteiro.replace(".", "") + "." + decimais), len(decimais)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", numero):
        alvo, casas = float(numero.replace(".", "")), 0
    elif "." in numero:
        alvo, casas = float(numero), len(numero.rsplit(".", 1)[1])
    else:
        alvo, casas = float(numero), 0
    return f"{prefixo}{_formatar_br(alvo * max(0.0, t), casas)}{sufixo}"


@lru_cache(maxsize=256)
def fatiar_legenda(fala: str, tamanho: int, largura: int, max_linhas: int) -> tuple:
    """Divide a fala em blocos de até `max_linhas` linhas, para a legenda percorrer o texto inteiro durante a cena."""
    linhas = quebrar(limpar_para_tela(fala), fonte(True, tamanho), largura)
    if not linhas:
        return ((),)
    por_bloco = math.ceil(len(linhas) / math.ceil(len(linhas) / max_linhas))         # 5 linhas viram 3+2, não 4+1
    return tuple(tuple(linhas[i:i + por_bloco]) for i in range(0, len(linhas), por_bloco))


def bloco_da_legenda(blocos: tuple, p: float) -> tuple:
    """Bloco a mostrar no progresso p (0 a 1), proporcional ao tamanho de cada bloco; a fala ocupa os primeiros 92% da cena."""
    pesos = [max(1, sum(len(l) for l in b)) for b in blocos]
    alvo = min(1.0, max(0.0, p) / 0.92) * sum(pesos)
    acumulado = 0
    for bloco, peso in zip(blocos, pesos):
        acumulado += peso
        if alvo <= acumulado:
            return bloco
    return blocos[-1]


def estimar_duracao_fala(texto: str) -> float:
    return len(texto.split()) / PALAVRAS_POR_SEGUNDO + 0.6


# ==============================================================================
# ESTILO E PEÇAS COMUNS DO QUADRO
# ==============================================================================
@dataclass
class Estilo:
    """Tema + marca + logo já preparado. Os atributos de cor do tema podem ser lidos direto (e.destaque, e.texto...)."""
    tema: Tema
    marca: str = ""
    logo: Image.Image | None = None

    def __getattr__(self, nome):
        return getattr(self.tema, nome)


def preparar_logo(logo, altura: int = 44, largura_max: int = 300):
    """Aceita um PIL.Image ou o caminho de um arquivo; devolve RGBA redimensionado, ou None se não der para abrir."""
    if logo is None:
        return None
    try:
        img = logo.convert("RGBA") if isinstance(logo, Image.Image) else Image.open(logo).convert("RGBA")
    except (OSError, ValueError):
        return None
    largura = min(largura_max, max(1, int(img.width * altura / img.height)))
    return img.resize((largura, altura), Image.Resampling.LANCZOS)


def criar_estilo(tema: Tema, marca: str = "", logo=None) -> Estilo:
    """A marca digitada vale mais que a do kit do tema; sem logo enviado, usa o do kit (se existir)."""
    if logo is None and tema.logo:
        logo = PASTA_ASSETS / tema.logo
    return Estilo(tema=tema, marca=limpar_para_tela(marca or tema.marca), logo=preparar_logo(logo))


def ease_out(t: float) -> float:
    return 1 - (1 - min(1.0, max(0.0, t))) ** 3


def _entra(p: float, inicio: float, duracao: float = 0.14) -> float:
    return ease_out((p - inicio) / duracao)


def desenhar_cartao(draw, xy, fill, outline=None, width=2, radius=20):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _particulas(draw, p, e: Estilo, n=9):
    rng = random.Random(7)
    cor = misturar(e.fundo, e.destaque, 0.35)
    for i in range(n):
        x, y, raio = rng.randint(90, LARGURA - 90), rng.randint(300, 1500), rng.randint(3, 6)
        x += int(math.sin(p * math.tau + i * 0.7) * 16)
        y += int(math.cos(p * math.tau + i * 1.1) * 12)
        draw.ellipse((x - raio, y - raio, x + raio, y + raio), fill=cor)


def _cabecalho(draw, img, e: Estilo, numero: int, total: int, tag: str):
    desenhar_cartao(draw, (60, 60, 1020, 150), e.superficie, e.borda, 2, 16)
    if e.logo is not None:
        img.paste(e.logo, (85, 105 - e.logo.height // 2), e.logo)
    elif e.marca:
        f, linhas = ajustar(e.marca.upper(), True, (30, 26, 22), 600, 1)
        draw.text((90, 105), linhas[0], font=f, fill=e.destaque, anchor="lm")
    if total > 1:                                    # cartão único (capa ou fecho de um Reels) não numera
        draw.text((990, 105), f"{numero}/{total}", font=fonte(True, 28), fill=e.texto_suave, anchor="rm")
    if limpar_para_tela(tag):
        f, linhas = ajustar(tag, True, (30, 26, 22), 860, 1)
        cor = e.destaque if numero % 2 else e.destaque2
        desenhar_cartao(draw, (60, 180, 60 + int(f.getlength(linhas[0])) + 50, 245), cor, radius=12)
        draw.text((85, 212), linhas[0], font=f, fill=cor_sobre(cor), anchor="lm")


def _titulo_padrao(draw, e: Estilo, cena: dict):
    f, linhas = ajustar(cena["titulo"], True, (58, 52, 46, 42, 38), 960, 2)
    desenhar_linhas(draw, 60, 280, linhas, f, e.texto)


def _legenda(draw, e: Estilo, fala: str, p: float):
    desenhar_cartao(draw, (60, 1540, 1020, 1850), e.superficie, e.destaque, 3, 20)
    draw.text((90, 1576), "LEGENDA", font=fonte(True, 22), fill=e.destaque, anchor="lm")
    f = fonte(True, 36)
    desenhar_linhas(draw, 90, 1608, bloco_da_legenda(fatiar_legenda(fala, 36, 860, 4), p), f, e.texto)


@lru_cache(maxsize=64)
def _gradiente(largura: int, altura: int, c1: tuple, c2: tuple) -> Image.Image:
    faixa = Image.new("RGB", (largura, 1))
    pixels = faixa.load()
    for x in range(largura):
        pixels[x, 0] = misturar(c1, c2, x / max(1, largura - 1))
    return faixa.resize((largura, altura))


@lru_cache(maxsize=64)
def _mascara(largura: int, altura: int, raio: int) -> Image.Image:
    m = Image.new("L", (largura, altura), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, largura - 1, altura - 1), raio, fill=255)
    return m


# ==============================================================================
# LAYOUTS (cada um desenha o miolo da cena, entre o título e a legenda)
# ==============================================================================
def _layout_lista(draw, img, cena, p, e: Estilo):
    itens = [i for i in cena["itens"] if i.strip()][:4]
    n, topo, base, folga = len(itens), 480, 1490, 26
    altura = min(270, (base - topo - (n - 1) * folga) // max(1, n))
    topo += (base - topo - (n * altura + (n - 1) * folga)) // 2                      # bloco centralizado na área livre
    for i, texto in enumerate(itens):
        t = _entra(p, 0.06 + 0.11 * i)
        if t <= 0:
            continue
        dx, y = int((1 - t) * 500), topo + i * (altura + folga)
        desenhar_cartao(draw, (60 + dx, y, 1020 + dx, y + altura), e.superficie, e.borda, 2, 20)
        cx, cy = 130 + dx, y + altura // 2
        cor = e.destaque if i % 2 == 0 else e.destaque2
        draw.ellipse((cx - 32, cy - 32, cx + 32, cy + 32), fill=cor)
        draw.text((cx, cy), str(i + 1), font=fonte(True, 36), fill=cor_sobre(cor), anchor="mm")
        f, linhas = ajustar(texto, True, (46, 42, 38, 34, 30), 780, 3 if altura >= 170 else 2)
        desenhar_linhas(draw, 190 + dx, cy - len(linhas) * altura_linha(f) // 2, linhas, f, e.texto)


def _layout_numero(draw, img, cena, p, e: Estilo):
    desenhar_cartao(draw, (60, 480, 1020, 940), e.superficie, e.destaque, 3, 26)
    valor = limpar_para_tela(cena["destaque_valor"])
    f, _ = ajustar(valor, True, (190, 170, 150, 130, 110, 90, 72), 880, 1)      # tamanho pelo texto final: não pula
    draw.text((540, 665), valor_animado(valor, _entra(p, 0.05, 0.40)), font=f, fill=e.destaque, anchor="mm")
    fr, linhas = ajustar(cena["destaque_rotulo"], True, (42, 38, 34, 30), 880, 2)
    desenhar_linhas(draw, 540, 790, linhas, fr, e.texto_suave, centralizar=True)
    for i, texto in enumerate([i for i in cena["itens"] if i.strip()][:2]):
        t = _entra(p, 0.45 + 0.12 * i)
        if t <= 0:
            continue
        y = 990 + i * 190 + int((1 - t) * 40)
        desenhar_cartao(draw, (60, y, 1020, y + 160), e.superficie, e.borda, 2, 20)
        cor = e.destaque2 if i % 2 == 0 else e.destaque
        draw.ellipse((90, y + 62, 126, y + 98), fill=cor)
        f2, l2 = ajustar(texto, True, (38, 34, 30), 800, 2)
        desenhar_linhas(draw, 156, y + 80 - len(l2) * altura_linha(f2) // 2, l2, f2, e.texto)


def _layout_comparacao(draw, img, cena, p, e: Estilo):
    rotulos = (list(cena.get("rotulos", [])) + ["ANTES", "DEPOIS"])[:2]
    blocos = [(rotulos[0], cena["itens"][0], e.alerta, 480, 900, -1), (rotulos[1], cena["itens"][1], e.destaque2, 980, 1400, 1)]
    for i, (rotulo, texto, cor, y1, y2, lado) in enumerate(blocos):
        t = _entra(p, 0.06 + 0.26 * i, 0.16)
        if t <= 0:
            continue
        dx = int(lado * (1 - t) * 600)
        desenhar_cartao(draw, (60 + dx, y1, 1020 + dx, y2), e.superficie, cor, 3, 24)
        f = fonte(True, 28)
        rotulo = limpar_para_tela(rotulo)
        desenhar_cartao(draw, (90 + dx, y1 + 28, 90 + dx + int(f.getlength(rotulo)) + 44, y1 + 84), cor, radius=14)
        draw.text((112 + dx, y1 + 56), rotulo, font=f, fill=cor_sobre(cor), anchor="lm")
        ft, linhas = ajustar(texto, True, (48, 44, 40, 36, 32), 840, 4)
        desenhar_linhas(draw, 90 + dx, y1 + 120, linhas, ft, e.texto)
    if p > 0.40:
        draw.polygon([(505, 918), (575, 918), (540, 962)], fill=e.destaque)


def _fundo_de_impacto(draw, p, e: Estilo, centro_y: int):
    raio = 400 + int(math.sin(p * math.tau) * 10)
    draw.ellipse((540 - raio, centro_y - raio, 540 + raio, centro_y + raio), outline=misturar(e.fundo, e.destaque, 0.22), width=6)


def _apoio(draw, e: Estilo, cena, y, p, inicio=0.30) -> int:
    for texto in [i for i in cena["itens"] if i.strip()][:2]:
        if p < inicio:
            break
        f, linhas = ajustar(texto, False, (42, 38, 34), 880, 2)
        y = desenhar_linhas(draw, 540, y, linhas, f, e.texto_suave, centralizar=True) + 8
    return y


def _layout_titulo(draw, img, cena, p, e: Estilo):
    _fundo_de_impacto(draw, p, e, 760)
    t = _entra(p, 0.04, 0.20)
    f, linhas = ajustar(cena["titulo"], True, (92, 84, 76, 68, 60, 54), 900, 5)
    altura = len(linhas) * altura_linha(f)
    y0 = 760 - altura // 2 + int((1 - t) * 50)
    y = desenhar_linhas(draw, 540, y0, linhas, f, e.texto, centralizar=True)
    largura = int(380 * _entra(p, 0.15, 0.25))
    if largura > 0:
        draw.rounded_rectangle((540 - largura // 2, y + 24, 540 + largura // 2, y + 36), radius=6, fill=e.destaque)
    _apoio(draw, e, cena, y + 70, p)


def _layout_cta(draw, img, cena, p, e: Estilo):
    _fundo_de_impacto(draw, p, e, 700)
    t = _entra(p, 0.04, 0.20)
    f, linhas = ajustar(cena["titulo"], True, (80, 72, 64, 58, 52), 900, 4)
    y0 = 640 - len(linhas) * altura_linha(f) // 2 + int((1 - t) * 50)
    y = desenhar_linhas(draw, 540, y0, linhas, f, e.texto, centralizar=True)
    _apoio(draw, e, cena, y + 30, p)
    escala = 1.0 + math.sin(p * math.tau * 2) * 0.025
    largura, altura = int(900 * escala), int(130 * escala)
    x, ytopo = 540 - largura // 2, 1220 + (130 - altura) // 2
    if _entra(p, 0.30, 0.20) > 0:
        img.paste(_gradiente(largura, altura, tuple(e.destaque), tuple(e.destaque2)), (x, ytopo), _mascara(largura, altura, 28))
        fb, l = ajustar(cena["botao"], True, (46, 42, 38, 34), 820, 1)
        draw.text((540, ytopo + altura // 2), l[0] if l else "", font=fb, fill=cor_sobre(misturar(e.destaque, e.destaque2, 0.5)), anchor="mm")


LAYOUTS_COM_TITULO_NO_TOPO = ("lista", "numero", "comparacao")
DESENHOS = {"titulo": _layout_titulo, "lista": _layout_lista, "numero": _layout_numero,
            "comparacao": _layout_comparacao, "cta": _layout_cta}


def fator_fade(quadro: int, total: int) -> float:
    return max(0.0, min(1.0, quadro / FADE_QUADROS, (total - 1 - quadro) / FADE_QUADROS))


def desenhar_quadro(cena: dict, numero: int, total: int, p: float, e: Estilo, fade: float = 1.0) -> Image.Image:
    """Um quadro da cena no progresso p (0 a 1). `fade` < 1 escurece em direção ao fundo (transição entre cenas)."""
    img = Image.new("RGB", (LARGURA, ALTURA), e.fundo)
    draw = ImageDraw.Draw(img)
    _particulas(draw, p, e)
    _cabecalho(draw, img, e, numero, total, cena.get("tag", ""))
    if cena["layout"] in LAYOUTS_COM_TITULO_NO_TOPO:
        _titulo_padrao(draw, e, cena)
    DESENHOS[cena["layout"]](draw, img, cena, p, e)
    _legenda(draw, e, cena["fala"], p)
    if fade < 1.0:
        img = Image.blend(Image.new("RGB", img.size, e.fundo), img, max(0.0, fade))
    return img


def quadro_de_previa(cena: dict, numero: int, total: int, e: Estilo, largura: int = 360) -> Image.Image:
    """Miniatura da cena já com tudo na tela (p=0,9), para a tela de edição."""
    img = desenhar_quadro(cena, numero, total, 0.9, e)
    return img.resize((largura, int(largura * ALTURA / LARGURA)), Image.Resampling.LANCZOS)


# ==============================================================================
# ÁUDIO, FFMPEG E MONTAGEM
# ==============================================================================
async def _sintetizar(texto: str, caminho: str, voz: str):
    import edge_tts
    await edge_tts.Communicate(texto, voz).save(caminho)


def duracao_do_audio(caminho: str, ffmpeg: str) -> float:
    proc = subprocess.run([ffmpeg, "-i", caminho], capture_output=True, text=True, errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise FalhaRenderizacao("não consegui medir a duração da locução gerada")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def _comando_segmento(ffmpeg: str, audio: str | None, duracao: float, saida: str) -> list[str]:
    entrada_audio = ["-i", audio, "-af", "apad"] if audio else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    return [ffmpeg, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{LARGURA}x{ALTURA}", "-framerate", str(FPS), "-i", "-",
            *entrada_audio, "-t", f"{duracao:.4f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100", saida]


def _gravar_segmento(cena: dict, numero: int, total: int, duracao: float, audio: str | None, e: Estilo, saida: str, ffmpeg: str):
    quadros = max(1, round(duracao * FPS))
    with tempfile.TemporaryFile() as log:
        try:
            proc = subprocess.Popen(_comando_segmento(ffmpeg, audio, quadros / FPS, saida), stdin=subprocess.PIPE, stderr=log)
        except OSError as erro:
            raise FalhaRenderizacao(f"não consegui executar o ffmpeg ({erro})") from erro
        try:
            for k in range(quadros):
                img = desenhar_quadro(cena, numero, total, k / max(1, quadros - 1), e, fator_fade(k, quadros))
                proc.stdin.write(img.tobytes())
        except OSError:
            pass                                            # o ffmpeg fechou o pipe: o motivo está no log, lido abaixo
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass
            codigo = proc.wait()
        if codigo != 0:
            log.seek(0)
            raise FalhaRenderizacao(f"o ffmpeg falhou na cena {numero}: {log.read().decode(errors='ignore')[-400:]}")


def nome_de_arquivo(titulo: str) -> str:
    """Título vira nome de arquivo: sem acento, sem símbolo, cortado na palavra inteira mais próxima de 40."""
    base = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()
    if len(texto) > 40:
        texto = texto[:40].rsplit("_", 1)[0] if "_" in texto[:40] else texto[:40]
    return (texto.strip("_") or "video") + ".mp4"


def renderizar_video(plano: dict, tema: Tema, *, voz: str | None = "pt-BR-AntonioNeural", marca: str = "", logo=None,
                     nome_arquivo: str = "video.mp4", pasta_saida=None, progresso=None,
                     duracao_minima: float = DURACAO_MINIMA_CENA) -> dict:
    """
    Renderiza o plano (dict com "cenas") em `pasta_saida/nome_arquivo`. `voz=None` gera um vídeo mudo (a duração de cada
    cena é estimada pelo tamanho da fala). Devolve {"caminho", "duracao_segundos", "duracoes"}.
    """
    cenas = plano["cenas"]
    if not cenas:
        raise FalhaRenderizacao("o plano não tem nenhuma cena")
    pasta_saida = Path(pasta_saida or PASTA_SAIDA)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    e, ffmpeg = criar_estilo(tema, marca, logo), localizar_ffmpeg()
    destino = pasta_saida / (nome_arquivo if nome_arquivo.endswith(".mp4") else nome_arquivo + ".mp4")
    total, duracoes = len(cenas), []

    with tempfile.TemporaryDirectory(prefix="reel_") as tmp:
        tmp = Path(tmp)
        segmentos = []
        for i, cena in enumerate(cenas, 1):
            if progresso:
                progresso((i - 1) / total, f"Cena {i}/{total}: {'gravando a locução e ' if voz else ''}desenhando os quadros...")
            audio = None
            if voz:
                audio = str(tmp / f"audio_{i}.mp3")
                try:
                    asyncio.run(_sintetizar(limpar_para_tela(cena["fala"]), audio, voz))
                except Exception as erro:
                    raise FalhaRenderizacao(f"não consegui gerar a locução da cena {i} (precisa de internet): {erro}. "
                                            "Desmarque a voz para gerar o vídeo mudo.") from erro
                duracao = duracao_do_audio(audio, ffmpeg) + PAUSA_FINAL_CENA
            else:
                duracao = estimar_duracao_fala(cena["fala"])
            duracao = max(duracao, duracao_minima)
            segmento = str(tmp / f"segmento_{i}.mp4")
            _gravar_segmento(cena, i, total, duracao, audio, e, segmento, ffmpeg)
            segmentos.append(segmento)
            duracoes.append(round(duracao, 2))

        if progresso:
            progresso(0.97, "Juntando as cenas...")
        lista = tmp / "lista.txt"
        lista.write_text("".join(f"file '{Path(s).as_posix()}'\n" for s in segmentos), encoding="utf-8")
        proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
                               "-movflags", "+faststart", str(destino)], capture_output=True, text=True, errors="ignore")
        if proc.returncode != 0:
            raise FalhaRenderizacao(f"o ffmpeg falhou ao juntar as cenas: {proc.stderr[-400:]}")
    if progresso:
        progresso(1.0, "Vídeo pronto!")
    return {"caminho": str(destino), "duracao_segundos": round(sum(duracoes), 1), "duracoes": duracoes}
