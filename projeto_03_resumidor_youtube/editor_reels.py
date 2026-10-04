"""
Monta um Reels pronto para postar a partir de um corte do YouTube.

O corte cru sai 16:9, sem título, sem legenda e sem marca. Aqui ele vira uma peça 9:16 fechada:

    cartão de capa (gancho)  ->  clipe reenquadrado  ->  cartão de chamada final

No meio, o clipe ganha fundo desfocado do próprio vídeo, a legenda queimada (montada em legendas.py) e,
se quiserem, título, etiqueta, marca e barra de progresso.

Decisão de projeto: os elementos que não mudam a cada quadro são desenhados **uma vez** com o Pillow e entram
no ffmpeg como PNG transparente. Desenhar quadro a quadro, como fazem os cartões, custaria ~9 MB por quadro de
RGBA no cano — minutos a mais para o mesmo resultado. Só a barra de progresso é animada, e sai de graça numa
expressão do próprio ffmpeg.

A legenda entra como uma **faixa**: cada estado dela (um bloco, ou o bloco com a palavra N em destaque) é um
PNG, e uma lista do demuxer `concat` diz quanto tempo cada um fica na tela. Para o ffmpeg isso é um vídeo só,
com um overlay só. Antes, cada bloco era uma entrada e um overlay próprios — funciona para 15 blocos, mas a
legenda com a palavra em destaque tem um estado por palavra (150 num minuto), e 150 overlays encadeados
processariam o quadro inteiro 150 vezes.
"""
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import audio_estudio as ae
import efeitos as ef
import legendas as lg
import marca_dagua as md
import momentos as mo
import renderizador_generico as rg
from core.midia import localizar_ffmpeg
from esquemas_reels import MAX_TITULO, cortar
from temas_video import Tema


LARGURA, ALTURA, FPS = rg.LARGURA, rg.ALTURA, rg.FPS
# Onde o vídeo é encaixado; o resto do quadro é fundo desfocado. Sem nada escrito em cima, ele sobe e ocupa a
# largura inteira — num 16:9 isso são 1080x607 em vez de 1000x562, ou seja, 8% a mais de imagem e de resolução.
CAIXA_CLIPE = (0, 540, 1080, 1340)           # com título ou etiqueta no topo
CAIXA_CLIPE_LIMPA = (0, 300, 1080, 1440)     # só imagem e legenda (o padrão)
# A legenda termina em 1500, e a barra logo abaixo: no celular, o Instagram e o TikTok desenham a conta, a
# legenda do post e os botões por cima do último quinto do vídeo (a partir de ~1536). Ali ninguém leria.
Y_TITULO, BASE_LEGENDA, Y_BARRA = 260, 1500, 1520
CONTORNO_LEGENDA = 7          # espessura da borda das letras quando a legenda vai direto sobre a imagem
PASTA_SAIDA = rg.DIRETORIO / "videos_gerados" / "reels_prontos"

# Como o vídeo 16:9 entra no quadro 9:16. "inteiro" é o padrão: o vídeo aparece por completo sobre um fundo
# desfocado tirado dele mesmo, e a imagem é REDUZIDA, não esticada — fica nítida. "preencher" ocupa a tela
# toda, mas de um 16:9 sobra só o terço central, esticado 1,78x: custa definição.
INTEIRO, PREENCHER, ACAO = "inteiro", "preencher", "acao"
ENQUADRAMENTOS = {
    INTEIRO: "Vídeo inteiro, fundo desfocado (mais nítido)",
    PREENCHER: "Tela cheia (corta as laterais)",
    ACAO: "Tela cheia inteligente (segue a ação por corte)",
}

# Como a legenda aparece. "classica" é o bloco inteiro de uma vez; as outras duas acompanham a fala palavra
# a palavra, que é o estilo dos vídeos curtos editados no CapCut.
CLASSICA, DESTAQUE, IMPACTO = "classica", "destaque", "impacto"
ESTILOS_LEGENDA = {CLASSICA: "Clássica (a frase inteira)", DESTAQUE: "Palavra em destaque (karaokê)",
                   IMPACTO: "Impacto (poucas palavras, caixa alta)"}
# A faixa de legenda só cobre a parte de baixo do quadro: PNG menor, codificado e lido mais rápido.
FAIXA_Y0, FAIXA_Y1 = 960, 1560
QUADRO_MINIMO = 1.0 / FPS     # estado de legenda mais curto que um quadro nem chegaria a aparecer


class FalhaNaEdicao(RuntimeError):
    """Não deu para montar o vídeo tratado; a mensagem diz o motivo em português."""


# ==============================================================================
# LEITURA DO CLIPE
# ==============================================================================
def ler_propriedades(saida_ffmpeg: str) -> dict:
    """Tamanho, duração e se há faixa de áudio, lidos do que o ffmpeg imprime no `-i` (não exige ffprobe)."""
    largura = altura = None
    for linha in saida_ffmpeg.splitlines():
        if "Video:" in linha and largura is None:
            achado = re.search(r"[\s,](\d{2,5})x(\d{2,5})", linha.split("Video:", 1)[1])
            if achado:
                largura, altura = int(achado.group(1)), int(achado.group(2))
    tempo = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", saida_ffmpeg)
    duracao = int(tempo.group(1)) * 3600 + int(tempo.group(2)) * 60 + float(tempo.group(3)) if tempo else 0.0
    return {"largura": largura, "altura": altura, "duracao": duracao, "tem_audio": "Audio:" in saida_ffmpeg}


def sondar_clipe(caminho, ffmpeg: str) -> dict:
    proc = subprocess.run([ffmpeg, "-i", str(caminho)], capture_output=True, text=True, errors="ignore")
    props = ler_propriedades(proc.stderr)
    if not props["largura"] or not props["duracao"]:
        raise FalhaNaEdicao(f"não consegui ler o clipe {Path(caminho).name}: {proc.stderr.strip()[-200:]}")
    return props


def tamanho_do_clipe(caminho, ffmpeg=None) -> tuple:
    """(largura, altura) do arquivo — a caixa da marca d'água depende disso e só dá para saber com o clipe."""
    props = sondar_clipe(caminho, ffmpeg or localizar_ffmpeg())
    return props["largura"], props["altura"]


def geometria_do_clipe(largura: int, altura: int, caixa=CAIXA_CLIPE) -> tuple:
    """Maior tamanho par que cabe na caixa mantendo a proporção, centralizado nela. Devolve (w, h, x, y)."""
    x1, y1, x2, y2 = caixa
    disponivel_l, disponivel_a = x2 - x1, y2 - y1
    escala = min(disponivel_l / largura, disponivel_a / altura)
    w = max(2, int(largura * escala) // 2 * 2)
    h = max(2, int(altura * escala) // 2 * 2)
    return w, h, x1 + (disponivel_l - w) // 2, y1 + (disponivel_a - h) // 2


# ==============================================================================
# AS ARTES (PNG transparente, desenhadas uma vez)
# ==============================================================================
def _rgba(cor, alfa: int) -> tuple:
    return (*tuple(cor), alfa)


def _nova_camada() -> tuple:
    img = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def desenhar_moldura(estilo, titulo: str, etiqueta: str = "") -> Image.Image:
    """
    Cabeçalho com a marca, etiqueta e título: fica na tela o clipe inteiro. Cada peça só aparece se tiver
    conteúdo — sem marca, etiqueta nem título, a camada sai vazia e nem entra no vídeo.

    Não há contorno em volta do vídeo: quem separa a imagem do fundo é o próprio desfoque, que já sai
    escurecido. Uma borda colorida só marcaria a peça como template.
    """
    img, draw = _nova_camada()
    if estilo.logo is not None or estilo.marca:
        rg.desenhar_cartao(draw, (60, 60, 1020, 150), _rgba(estilo.superficie, 230), _rgba(estilo.borda, 255), 2, 16)
    if estilo.logo is not None:
        img.paste(estilo.logo, (85, 105 - estilo.logo.height // 2), estilo.logo)
    elif estilo.marca:
        f, linhas = rg.ajustar(estilo.marca.upper(), True, (30, 26, 22), 600, 1)
        draw.text((90, 105), linhas[0], font=f, fill=_rgba(estilo.destaque, 255), anchor="lm")

    etiqueta = rg.limpar_para_tela(etiqueta).upper()
    if etiqueta:
        f = rg.fonte(True, 28)
        largura = int(f.getlength(etiqueta)) + 50
        rg.desenhar_cartao(draw, (60, 180, 60 + largura, 240), _rgba(estilo.destaque, 245), radius=12)
        draw.text((60 + largura // 2, 210), etiqueta, font=f, fill=rg.cor_sobre(estilo.destaque), anchor="mm")

    titulo = rg.limpar_para_tela(titulo)
    if titulo:
        f, linhas = rg.ajustar(titulo, True, (54, 48, 44, 40, 36), 880, 3)
        alto = len(linhas) * rg.altura_linha(f)
        rg.desenhar_cartao(draw, (60, Y_TITULO, 1020, Y_TITULO + alto + 56), _rgba(estilo.superficie, 232),
                           _rgba(estilo.borda, 255), 2, 20)
        rg.desenhar_linhas(draw, 540, Y_TITULO + 28, linhas, f, _rgba(estilo.texto, 255), centralizar=True)

    return img


def desenhar_vinheta(forca: int = 170) -> Image.Image:
    """
    Bordas escurecidas, desenhadas uma vez. O filtro `vignette` do ffmpeg calcula isso a cada quadro e somava
    5 s a cada 12 s de vídeo; como imagem sobreposta, é o custo de um overlay. A conta é feita em 1/8 do
    tamanho e ampliada — um degradê não perde nada com isso.
    """
    alt, larg = ALTURA // 8, LARGURA // 8
    y, x = np.mgrid[0:alt, 0:larg]
    distancia = np.hypot((x - larg / 2) / (larg / 2), (y - alt / 2) / (alt / 2)) / np.sqrt(2)   # 0 no centro, 1 no canto
    alfa = (np.clip((distancia - 0.45) / 0.55, 0, 1) ** 1.6 * forca).astype(np.uint8)
    camada = np.zeros((alt, larg, 4), np.uint8)
    camada[..., 3] = alfa
    return Image.fromarray(camada, "RGBA").resize((LARGURA, ALTURA), Image.BILINEAR)


CAMINHO_PRODUTOS_ML = rg.DIRETORIO.parent / "corte_otakubr" / "dados_produtos.json"
DURACAO_CARD_ML = 3.5


def carregar_produtos_ml(caminho=None) -> list[dict]:
    """Lê o catálogo de produtos afiliados do Mercado Livre da `@corte.otakubr`."""
    alvo = Path(caminho or CAMINHO_PRODUTOS_ML)
    if not alvo.exists():
        return []
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
        return [p for p in dados if isinstance(p, dict) and p.get("nome")]
    except Exception:
        return []


_SINONIMOS_ANIME = {
    "jujutsu kaisen": ("jujutsu", "gojo", "satoru", "sukuna", "itadori", "megumi", "toji", "mahoraga", "shibuya"),
    "shingeki no kyojin": ("shingeki", "attack on titan", "eren", "jaeger", "levi", "mikasa", "tita", "titã"),
    "one piece": ("one piece", "luffy", "zoro", "roronoa", "sanji", "wano", "katana", "enma", "gear 5"),
    "berserk": ("berserk", "guts", "griffith", "casca", "eclipse", "dragonslayer"),
    "chainsaw man": ("chainsaw", "denji", "makima", "pochita", "aki", "power"),
    "naruto shippuden": ("naruto", "shippuden", "akatsuki", "sasuke", "itachi", "madara", "pain", "kakashi", "uchiha", "sharingan"),
    "neon genesis evangelion": ("evangelion", "shinji", "asuka", "rei", "eva-01", "unit-01", "nerv"),
}
_PALAVRAS_GENERICAS_PROD = {
    "action", "figure", "edicao", "especial", "form", "original", "box", "manga", "mangá",
    "deluxe", "edition", "capa", "dura", "vol", "colecionador", "completo", "moletom",
    "oversized", "bordado", "minimal", "camiseta", "heavyweight", "graphic", "decorativa", "aco",
}


def sugerir_produto_ml(texto_contexto: str, produtos: list[dict] | None = None,
                       usar_destaque_padrao: bool = False) -> dict | None:
    """
    Escolhe automaticamente o produto afiliado do Mercado Livre mais alinhado ao contexto do vídeo
    (título, transcrição, nome do anime ou personagem mencionado).
    """
    catalogo = produtos if produtos is not None else carregar_produtos_ml()
    if not catalogo:
        return None
    contexto = str(texto_contexto or "").lower()
    melhor_prod, melhor_pontos = None, 0

    for prod in catalogo:
        pontos = 0
        anime = str(prod.get("anime", "")).lower().strip()
        nome = str(prod.get("nome", "")).lower()
        if anime and anime in contexto:
            pontos += 12
        for chave_anime, termos in _SINONIMOS_ANIME.items():
            if chave_anime in anime or anime in chave_anime:
                for termo in termos:
                    if re.search(rf"\b{re.escape(termo)}\b", contexto):
                        pontos += 6
        for palavra in re.findall(r"[a-zA-ZÀ-ÿ0-9]{4,}", nome):
            if palavra in _PALAVRAS_GENERICAS_PROD:
                continue
            if re.search(rf"\b{re.escape(palavra)}\b", contexto):
                pontos += 5
        if pontos > 0 and prod.get("destaque"):
            pontos += 1
        if pontos > melhor_pontos:
            melhor_pontos = pontos
            melhor_prod = prod

    if melhor_prod is not None:
        return melhor_prod
    if usar_destaque_padrao:
        destaques = [p for p in catalogo if p.get("destaque")]
        return destaques[0] if destaques else catalogo[0]
    return None


def desenhar_card_produto_ml(produto: dict, estilo=None) -> Image.Image:
    """
    Card flutuante de afiliado Mercado Livre na estética Tokyo Streetwear & Manga Archive (`@corte.otakubr`).
    Desenhado uma única vez como camada 1080x1920 RGBA e animado com slide-up via overlay do ffmpeg nos
    segundos finais do vídeo, sem interromper o clipe.
    """
    img, draw = _nova_camada()
    carbono = (12, 12, 16, 246)
    superficie_box = (22, 22, 30, 255)
    amarelo_ml = (255, 230, 0, 255)
    carmim = (255, 42, 58, 255)
    offwhite = (245, 245, 240, 255)
    cinza = (160, 160, 172, 255)

    x1, y1, x2, y2 = 60, 1270, 1020, 1510
    # Sombra dura brutalista deslocada e cartão principal
    rg.desenhar_cartao(draw, (x1 + 8, y1 + 8, x2 + 8, y2 + 8), (0, 0, 0, 190), radius=16)
    rg.desenhar_cartao(draw, (x1, y1, x2, y2), carbono, amarelo_ml, 3, 16)
    # Faixa lateral carmim Tokyo Archive
    rg.desenhar_cartao(draw, (x1, y1, x1 + 16, y2), carmim, radius=8)

    # Emblema lateral do item (código + selo mangá) — 100% offline e instantâneo
    bx1, by1, bx2, by2 = x1 + 34, y1 + 24, x1 + 204, y2 - 24
    rg.desenhar_cartao(draw, (bx1, by1, bx2, by2), superficie_box, (55, 55, 70, 255), 2, 12)
    codigo = rg.limpar_para_tela(str(produto.get("codigo", "ARC-01"))).upper()
    categoria = rg.limpar_para_tela(str(produto.get("categoria", "DROP"))).upper()
    f_cod = rg.fonte(True, 24)
    f_cat = rg.fonte(True, 20)
    draw.text(((bx1 + bx2) // 2, by1 + 48), "TOKYO", font=f_cat, fill=carmim, anchor="mm")
    draw.text(((bx1 + bx2) // 2, (by1 + by2) // 2 + 4), codigo, font=f_cod, fill=offwhite, anchor="mm")
    rg.desenhar_cartao(draw, (bx1 + 16, by2 - 46, bx2 - 16, by2 - 14), amarelo_ml, radius=6)
    draw.text(((bx1 + bx2) // 2, by2 - 30), categoria[:10], font=rg.fonte(True, 18), fill=(10, 10, 12, 255), anchor="mm")

    # Linha superior de badges: MERCADO LIVRE + Entrega Full + Anime
    tx = bx2 + 24
    entrega = rg.limpar_para_tela(str(produto.get("entrega", "FULL 24H"))).upper()
    selo_ml = f"MERCADO LIVRE • {entrega}"
    f_selo = rg.fonte(True, 21)
    larg_selo = int(f_selo.getlength(selo_ml)) + 28
    rg.desenhar_cartao(draw, (tx, y1 + 22, tx + larg_selo, y1 + 58), amarelo_ml, radius=8)
    draw.text((tx + larg_selo // 2, y1 + 40), selo_ml, font=f_selo, fill=(10, 10, 12, 255), anchor="mm")

    anime = rg.limpar_para_tela(str(produto.get("anime", ""))).upper()
    if anime:
        ax = tx + larg_selo + 12
        larg_anime = min(260, int(f_selo.getlength(anime)) + 26)
        if ax + larg_anime < x2 - 20:
            rg.desenhar_cartao(draw, (ax, y1 + 22, ax + larg_anime, y1 + 58), carmim, radius=8)
            draw.text((ax + larg_anime // 2, y1 + 40), cortar(anime, 18), font=f_selo, fill=offwhite, anchor="mm")

    # Nome do produto (1 a 2 linhas)
    nome = rg.limpar_para_tela(str(produto.get("nome", "Produto Oficial Anime")))
    f_nome, linhas_nome = rg.ajustar(nome, True, (32, 28, 25), x2 - tx - 28, 2)
    y_texto = y1 + 70
    for linha in linhas_nome:
        draw.text((tx, y_texto), linha, font=f_nome, fill=offwhite, anchor="la")
        y_texto += rg.altura_linha(f_nome)

    # Rodapé do card: Preço + CTA Link na Bio
    preco = float(produto.get("preco", 0.0))
    preco_str = f"R$ {preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    f_preco = rg.fonte(True, 38)
    draw.text((tx, y2 - 42), preco_str, font=f_preco, fill=amarelo_ml, anchor="lm")

    cta_txt = "LINK NA BIO: @corte.otakubr"
    f_cta = rg.fonte(True, 22)
    larg_cta = int(f_cta.getlength(cta_txt)) + 36
    cx1 = max(tx + int(f_preco.getlength(preco_str)) + 20, x2 - larg_cta - 24)
    rg.desenhar_cartao(draw, (cx1, y2 - 64, x2 - 24, y2 - 20), carmim, amarelo_ml, 2, 10)
    draw.text(((cx1 + x2 - 24) // 2, y2 - 42), cta_txt, font=f_cta, fill=offwhite, anchor="mm")

    return img



NAO_TERMINA_LINHA = lg.NAO_TERMINA          # as mesmas regras que partem a frase em blocos (legendas.py)


def quebrar_legenda(texto: str, f, largura: int) -> list | None:
    """
    Uma ou duas linhas que cabem em `largura`, ou None se nem em duas couber. Entre as quebras possíveis,
    fica a de menor custo: linhas de tamanho parecido, e pena para quebra que o guia proíbe.
    Antes era "encher a linha até não caber" — "Ah, mas eu tenho certeza absoluta que / você consegue."
    """
    palavras = texto.split()
    if f.getlength(texto) <= largura:
        return [texto]
    melhor, custo_melhor = None, float("inf")
    for i in range(1, len(palavras)):
        l1, l2 = " ".join(palavras[:i]), " ".join(palavras[i:])
        w1, w2 = f.getlength(l1), f.getlength(l2)
        if w1 > largura or w2 > largura:
            continue
        # o equilíbrio desempata; quem manda é a gramática — com peso maior no equilíbrio, "certeza absoluta"
        # foi partida ao meio só para as duas linhas ficarem do mesmo tamanho
        custo = abs(w1 - w2) / largura * 40 + lg.custo_de_quebra(palavras[i - 1], palavras[i])
        if custo < custo_melhor:
            melhor, custo_melhor = [l1, l2], custo
    return melhor


def ajustar_legenda(texto: str, tamanhos: tuple, largura: int):
    """Maior fonte em que a legenda cabe em até 2 linhas; em último caso, a quebra antiga em 3."""
    texto = rg.limpar_para_tela(texto)
    for t in tamanhos:
        f = rg.fonte(True, t)
        linhas = quebrar_legenda(texto, f, largura)
        if linhas:
            return f, linhas
    return rg.ajustar(texto, True, tamanhos, largura, 3)


def _linhas_com_destaque(draw, linhas, f, y, cor, cor_destaque, destaque, contorno, cor_contorno):
    """Desenha palavra por palavra, centralizando cada linha, para poder pintar só a palavra da vez."""
    espaco, n = f.getlength(" "), 0
    for linha in linhas:
        palavras = linha.split()
        x = 540 - f.getlength(linha) / 2
        for palavra in palavras:
            draw.text((x, y), palavra, font=f, fill=cor_destaque if n == destaque else cor, anchor="la",
                      stroke_width=contorno, stroke_fill=cor_contorno)
            x += f.getlength(palavra) + espaco
            n += 1
        y += rg.altura_linha(f)


def desenhar_legenda(estilo, texto: str, com_caixa: bool = False, destaque: int | None = None,
                     impacto: bool = False) -> Image.Image:
    """
    Um bloco de legenda, ancorado embaixo. Por padrão o texto fica direto sobre a imagem, com contorno nas
    letras — é o que mantém a leitura sobre qualquer fundo sem uma caixa cobrindo o vídeo. `com_caixa` traz
    de volta o cartão, para quem preferir.

    `destaque` é o índice da palavra que está sendo dita: ela sai na cor de destaque do tema. `impacto` é o
    estilo de poucas palavras grandes, em caixa alta.
    """
    img, draw = _nova_camada()
    if impacto:
        f, linhas = ajustar_legenda(str(texto).upper(), (96, 88, 80, 72), 940)
    else:
        f, linhas = ajustar_legenda(texto, (52, 48, 44, 40), 900)
    topo = BASE_LEGENDA - (len(linhas) * rg.altura_linha(f) + 56)
    cor, cor_destaque = _rgba(estilo.texto, 255), _rgba(estilo.destaque, 255)
    if com_caixa:
        rg.desenhar_cartao(draw, (60, topo, 1020, BASE_LEGENDA), _rgba(estilo.superficie, 235),
                           _rgba(estilo.destaque, 255), 3, 20)
        contorno, cor_contorno = 0, None
    else:
        contorno = CONTORNO_LEGENDA + (2 if impacto else 0)
        cor_contorno = _rgba(rg.cor_sobre(estilo.texto), 235)
    if destaque is None:
        rg.desenhar_linhas(draw, 540, topo + 28, linhas, f, cor, centralizar=True, contorno=contorno,
                           cor_contorno=cor_contorno)
    else:
        _linhas_com_destaque(draw, linhas, f, topo + 28, cor, cor_destaque, destaque, contorno, cor_contorno)
    return img


# ==============================================================================
# A FAIXA DE LEGENDA (um PNG por estado, lidos em sequência como um vídeo só)
# ==============================================================================
def estados_da_legenda(legendas, estilo_legenda: str = CLASSICA) -> list:
    """
    O que fica na tela e quando: lista de {"inicio", "fim", "texto", "destaque", "impacto"}.

    Na clássica, um estado por bloco. Nas outras, um por palavra: o estado da palavra N vai do começo dela
    ao começo da seguinte, para o destaque andar sem piscar no intervalo entre as duas.
    """
    estados = []
    for bloco in legendas:
        # o que a fonte não desenha sai antes de contar palavras: o destaque tem que cair na palavra certa
        bloco = {**bloco, "texto": rg.limpar_para_tela(bloco["texto"])}
        if not bloco["texto"]:
            continue
        if estilo_legenda == CLASSICA:
            estados.append({"inicio": bloco["inicio"], "fim": bloco["fim"], "texto": bloco["texto"],
                            "destaque": None, "impacto": False})
            continue
        unidades = lg.em_pedacos_curtos(bloco) if estilo_legenda == IMPACTO else [bloco]
        for unidade in unidades:
            palavras = lg.tempos_das_palavras(unidade)
            for k, palavra in enumerate(palavras):
                inicio = unidade["inicio"] if k == 0 else palavra["inicio"]
                fim = palavras[k + 1]["inicio"] if k + 1 < len(palavras) else unidade["fim"]
                estados.append({"inicio": inicio, "fim": fim, "texto": unidade["texto"], "destaque": k,
                                "impacto": estilo_legenda == IMPACTO})
    return estados


@dataclass(frozen=True)
class FaixaDeImagens:
    """Entrada do ffmpeg lida pelo demuxer concat (a faixa de legenda), e não como imagem solta."""
    lista: Path


def faixa_de_legendas(legendas, estilo, pasta, duracao: float, estilo_legenda: str = CLASSICA,
                      com_caixa: bool = False) -> FaixaDeImagens | None:
    """
    Grava os PNGs e a lista do concat. Os buracos entre blocos viram um PNG vazio; estados sobrepostos são
    aparados no começo do seguinte. Estado repetido (mesmo texto, mesma palavra) reaproveita o arquivo.
    """
    estados = estados_da_legenda(legendas, estilo_legenda)
    if not estados:
        return None
    pasta = Path(pasta)
    vazio = pasta / "legenda_vazia.png"
    Image.new("RGBA", (LARGURA, FAIXA_Y1 - FAIXA_Y0), (0, 0, 0, 0)).save(vazio, compress_level=1)
    arquivos, linhas, t = {}, ["ffconcat version 1.0"], 0.0

    def entrar(arquivo, segundos):
        linhas.extend([f"file '{Path(arquivo).as_posix()}'", f"duration {segundos:.3f}"])

    for estado in sorted(estados, key=lambda e: e["inicio"]):
        inicio, fim = max(float(estado["inicio"]), t), min(float(estado["fim"]), float(duracao))
        if fim - inicio < QUADRO_MINIMO:
            continue
        chave = (estado["texto"], estado["destaque"], estado["impacto"])
        if chave not in arquivos:
            arquivos[chave] = pasta / f"legenda_{len(arquivos) + 1:04d}.png"
            desenhar_legenda(estilo, estado["texto"], com_caixa, estado["destaque"], estado["impacto"]) \
                .crop((0, FAIXA_Y0, LARGURA, FAIXA_Y1)).save(arquivos[chave], compress_level=1)
        if inicio - t >= 0.001:
            entrar(vazio, inicio - t)
        entrar(arquivos[chave], fim - inicio)
        t = fim
    if not arquivos:
        return None
    entrar(vazio, max(0.1, float(duracao) - t))
    linhas.append(f"file '{vazio.as_posix()}'")          # o concat só respeita a duração do último se ele se repetir
    lista = pasta / "legendas.ffconcat"
    lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return FaixaDeImagens(lista)


# ==============================================================================
# COMPOSIÇÃO DO CLIPE (funções puras: o comando é montado e testado sem rodar nada)
# ==============================================================================
def cor_ffmpeg(cor, alfa: float = 1.0) -> str:
    return "0x%02X%02X%02X@%.2f" % (*tuple(cor), alfa)


_PREENCHER = (f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={LARGURA}:{ALTURA}")


def expressao_crop_acao(tomadas_acao: list[dict] | None) -> str:
    """
    Filtro scale+crop 9:16 que desloca o eixo horizontal (x) para o centro da ação a cada corte de cena.
    Evita cortar personagens que falam ou lutam nos cantos de um vídeo 16:9, sem tremer a câmera dentro da tomada.
    """
    if not tomadas_acao:
        return _PREENCHER
    expr = f"{float(tomadas_acao[-1].get('x_rel', 0.5)):.3f}"
    for tomada in reversed(tomadas_acao[:-1]):
        ini = float(tomada.get("inicio", 0.0))
        fim = float(tomada.get("fim", 0.0))
        x_rel = float(tomada.get("x_rel", 0.5))
        expr = f"if(between(t,{ini:.2f},{fim:.2f}),{x_rel:.3f},{expr})"
    return (f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={LARGURA}:{ALTURA}:x='(iw-ow)*({expr})':y=0")


# Na tela cheia, um vídeo 16:9 perde 68% da largura e o terço central é ampliado 1,78x — daí a imagem mole.
# Lanczos amplia melhor que o bicúbico padrão, e o unsharp devolve parte do contorno perdido na ampliação.
NITIDEZ = "unsharp=5:5:0.7:3:3:0.3"
# O desfoque é feito em 1/4 do tamanho e depois ampliado: o resultado é o mesmo borrão, e o clipe de 15 s
# passou de 23 s para 6 s de processamento. Borrar em 1080x1920 é jogar trabalho fora.
def _fundo(cor: str = "") -> str:
    """O fundo desfocado. A cor entra ainda em 270x480, antes de ampliar: custa 1/16 do que custaria em 1080x1920."""
    return (f"scale={LARGURA // 4}:{ALTURA // 4}:force_original_aspect_ratio=increase,crop={LARGURA // 4}:{ALTURA // 4},"
            f"boxblur=6:2,eq=brightness=-0.16:saturation=0.7{',' + cor if cor else ''},scale={LARGURA}:{ALTURA}")


_FUNDO = _fundo()


PROPORCAO_CINEMA = 2.39
OPACIDADE_BRILHO = 0.3


def _com_brilho(entrada: str, saida: str, largura: int, altura: int) -> list:
    """
    Bloom: uma cópia bem desfocada somada por cima em modo "tela" — o que é claro ganha halo, o escuro não
    muda. O desfoque é feito em 1/4 do tamanho, e a soma só na luminância: somar as três componentes em RGB
    (a primeira versão) deixou uma coluna roxa de 8 px na borda direita quando havia filtro de cor antes.
    """
    return [
        f"[{entrada}]format=yuv420p,split=2[{saida}_a][{saida}_b]",
        f"[{saida}_b]scale={max(2, largura // 4)}:{max(2, altura // 4)},gblur=sigma=4,scale={largura}:{altura}[{saida}_halo]",
        f"[{saida}_a][{saida}_halo]blend=c0_mode=screen:c0_opacity={OPACIDADE_BRILHO}"
        f":c1_mode=normal:c1_opacity=0:c2_mode=normal:c2_opacity=0[{saida}]",
    ]


def filtro_de_composicao(geometria, sobreposicoes: list, duracao: float, cor_barra: str,
                         nitidez: bool = False, com_barra: bool = False, delogo: str = "", cor: str = "",
                         zoom=None, tremida=None, efeitos: str = "", brilho: bool = False,
                         cinemascope: bool = False, entrada: str = "0:v", prefixo: str = "",
                         no_ramo_ampliado: str = "", tomadas_acao: list[dict] | None = None) -> str:
    """
    Sem geometria (enquadramento "preencher" ou "acao"), o clipe é ampliado até cobrir o quadro e as laterais são cortadas.
    Com geometria, ele entra inteiro na caixa e o fundo vira o próprio clipe desfocado e escurecido — o que
    preenche o 9:16 sem tarja preta. Depois vêm o zoom, os efeitos dos golpes, as artes e, por último, a barra.

    `cor` é o filtro de cor (efeitos.filtro_de_cor), `zoom` um par (janelas, fator) de efeitos.janelas_de_zoom,
    `tremida` um par (janelas, amplitude), `efeitos` a cadeia de efeitos.filtros_dos_golpes. `prefixo` é um
    pedaço de filtergraph que vem antes de tudo (a câmera lenta) e entrega o vídeo em `entrada`.
    """
    afiar = f",{NITIDEZ}" if nitidez else ""
    tingir = f",{cor}" if cor else ""
    # O delogo vem antes de tudo: apagar a marca no tamanho original é melhor do que depois de reduzir, e no
    # modo desfocado ela apareceria também no fundo. Logo depois, o vídeo cai para a taxa da saída (24
    # quadros/s): com fonte a 50, cada filtro seguinte processaria mais da metade de quadros que iam para o
    # lixo no `-r` da saída. A cor vem depois de reduzir (na frente e no fundo), onde há menos pixels.
    antes = f"{delogo}," if delogo else ""
    partes = [prefixo] if prefixo else []
    if geometria is None:
        recorte_cheio = expressao_crop_acao(tomadas_acao) if tomadas_acao else _PREENCHER
        partes.append(f"[{entrada}]{antes}fps={FPS},{recorte_cheio}{tingir}{afiar}[v0]")
        if brilho:
            partes[-1] = partes[-1][:-len("[v0]")] + "[v0_opaco]"
            partes += _com_brilho("v0_opaco", "v0", LARGURA, ALTURA)
    else:
        w, h, x, y = geometria
        # Faixa de cinema: a frente perde em cima e embaixo até 2,39:1 e desce para continuar centralizada.
        alto = min(h, int(round(w / PROPORCAO_CINEMA / 2)) * 2) if cinemascope else h
        recorte = f",crop={w}:{alto}" if alto < h else ""
        partes += [
            f"[{entrada}]{antes}fps={FPS},split=2[fundo_cru][frente_cru]",
            f"[fundo_cru]{_fundo(cor)}[fundo]",
            f"[frente_cru]scale={w}:{h}:flags=lanczos{tingir}{afiar}{recorte}[frente{'_opaca' if brilho else ''}]",
        ]
        if brilho:
            partes += _com_brilho("frente_opaca", "frente", w, alto)
        partes.append(f"[fundo][frente]overlay={x}:{y + (h - alto) // 2}[v0]")
    anterior = "v0"
    janelas, fator = zoom if zoom else ([], 1.0)
    tremidas, amplitude = tremida if tremida else ([], 0)
    if (janelas and fator > 1.0) or (tremidas and amplitude > 0):
        partes += ef.filtro_de_zoom(anterior, "vz", janelas if fator > 1.0 else [], fator, LARGURA, ALTURA,
                                    tremidas, amplitude, antes_do_recorte=no_ramo_ampliado)
        anterior = "vz"
    if efeitos:
        partes.append(f"[{anterior}]{efeitos}[vg]")
        anterior = "vg"
    for i, sobre in enumerate(sobreposicoes, start=1):
        if sobre.get("faixa"):
            # A faixa já tem o tempo de cada estado dentro dela; quando acaba, o vídeo segue sem ela.
            partes.append(f"[{sobre['entrada']}:v]format=rgba[faixa{i}]")
            partes.append(f"[{anterior}][faixa{i}]overlay=0:{sobre.get('y', 0)}:eof_action=pass[v{i}]")
        else:
            janela = ""
            if sobre.get("inicio") is not None:
                janela = f":enable='between(t,{sobre['inicio']:.2f},{sobre['fim']:.2f})'"
            y_pos = sobre.get("y_expr", "0")
            partes.append(f"[{anterior}][{sobre['entrada']}:v]overlay=0:{y_pos}{janela}[v{i}]")
        anterior = f"v{i}"
    # Recuada na mesma margem dos cartões: atravessando a tela inteira, ela lê como divisória, não como progresso.
    barra = (f"drawbox=x=60:y={Y_BARRA}:w='(iw-120)*t/{max(0.1, duracao):.3f}':h=10:color={cor_barra}:t=fill,"
             if com_barra else "")
    partes.append(f"[{anterior}]{barra}setsar=1,format=yuv420p[final]")
    return ";".join(partes)


def comando_de_composicao(ffmpeg: str, clipe, artes: list, filtro: str, duracao: float, saida, tem_audio: bool,
                          previa_em: float | None = None, audio_do_filtro: str | None = None) -> list:
    """
    O clipe é a entrada 0 e cada arte é uma entrada de imagem (ou a faixa de legenda, lida pelo concat);
    sem áudio no clipe, entra silêncio.

    `previa_em` troca o vídeo por um quadro só, em PNG, naquele segundo. O `-ss` vai depois do `-i` de
    propósito: o ffmpeg processa desde o começo e descarta, e assim o tempo que o filtro enxerga é o do
    clipe — legenda, zoom e barra aparecem na prévia exatamente como no vídeo.
    """
    comando = [ffmpeg, "-y", "-loglevel", "error", "-i", str(clipe)]
    for arte in artes:
        if isinstance(arte, FaixaDeImagens):
            comando += ["-f", "concat", "-safe", "0", "-i", str(arte.lista)]
        else:
            comando += ["-i", str(arte)]
    if previa_em is not None:
        return comando + ["-filter_complex", filtro, "-map", "[final]", "-ss", f"{max(0.0, previa_em):.3f}",
                          "-frames:v", "1", str(saida)]
    if tem_audio:
        mapa_audio = f"[{audio_do_filtro}]" if audio_do_filtro else "0:a:0"      # com câmera lenta, o som é esticado
    else:
        comando += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        mapa_audio = f"{len(artes) + 1}:a"
    return comando + [
        "-filter_complex", filtro, "-map", "[final]", "-map", mapa_audio,
        "-r", str(FPS), "-t", f"{duracao:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100", "-movflags", "+faststart", str(saida),
    ]


def ampliacao(props: dict, enquadramento: str, caixa=CAIXA_CLIPE_LIMPA) -> float:
    """Quanto o vídeo é esticado para caber no quadro. Acima de 1, a imagem perde definição."""
    if enquadramento in (PREENCHER, ACAO):
        return max(LARGURA / props["largura"], ALTURA / props["altura"])
    w, _, _, _ = geometria_do_clipe(props["largura"], props["altura"], caixa)
    return w / props["largura"]


_RITMOS = {}


def ritmo_do_clipe(clipe, ffmpeg: str) -> dict:
    """momentos.analisar, guardado por arquivo e data de modificação."""
    caminho = Path(clipe)
    chave = (str(caminho.resolve()), caminho.stat().st_mtime if caminho.exists() else 0)
    if chave not in _RITMOS:
        _RITMOS[chave] = mo.analisar(clipe, ffmpeg)
    return _RITMOS[chave]


def planejar_golpes(clipe, ffmpeg: str, props: dict, arte: ef.DirecaoDeArte) -> dict:
    """
    Onde os efeitos de golpe caem e qual trecho fica em câmera lenta ou speed ramping: {"golpes", "lento", "ritmo"}.
    A análise do som e dos cortes é guardada por arquivo (a prévia e a montagem do mesmo clipe não medem duas vezes).
    """
    if not arte.usa_golpes:
        return {"golpes": [], "lento": None, "ritmo": None}
    ritmo = ritmo_do_clipe(clipe, ffmpeg)
    escolhidos = mo.mais_fortes(ritmo["golpes"], arte.golpes_por_minuto, props["duracao"])
    if arte.speed_ramping:
        lento = ef.trechos_velocity(escolhidos, props["duracao"])
    elif arte.camera_lenta:
        lento = ef.trecho_lento(escolhidos, props["duracao"])
    else:
        lento = None
    return {"golpes": escolhidos, "lento": lento, "ritmo": ritmo}


def duracao_com_lento(duracao: float, lento) -> float:
    return ef.remapear(duracao, lento) if lento else duracao


def tratar_clipe(clipe, *, estilo, titulo: str, legendas=(), etiqueta: str = "", saida, ffmpeg: str,
                 pasta_arte, props: dict, enquadramento: str = INTEIRO, com_caixa_legenda: bool = False,
                 com_barra: bool = False, marca_dagua=None, arte: ef.DirecaoDeArte = ef.SEM_ARTE,
                 estilo_legenda: str = CLASSICA, previa_em: float | None = None, plano: dict | None = None,
                 produto_ml: dict | None = None,
                 config_audio: ae.ConfigAudio = ae.SEM_AUDIO_EXTRA) -> float:
    """
    Reenquadra o clipe em 9:16 com moldura e legendas queimadas. Devolve a duração final, em segundos — que
    muda quando há câmera lenta, speed ramping ou corte de silêncios. Com `previa_em`, grava em `saida` (um .png)
    só o quadro daquele segundo.

    `plano` é o de planejar_golpes; sem ele, o plano é feito aqui. Com câmera lenta ou speed ramping, tudo que
    tem tempo — a legenda, as palavras, os golpes, as janelas de zoom — é remapeado para a nova linha do tempo.
    """
    pasta_arte = Path(pasta_arte)
    artes, sobreposicoes = [], []
    if config_audio.cortar_silencios and previa_em is None and props.get("tem_audio"):
        clipe_cortado = pasta_arte / "clipe_sem_silencio.mp4"
        clipe, intervalos, nova_dur = ae.cortar_silencios_clipe(
            clipe, clipe_cortado, ffmpeg, props["duracao"], props["tem_audio"],
            limiar_db=config_audio.limiar_silencio_db, min_silencio=config_audio.min_silencio,
        )
        if nova_dur != props["duracao"]:
            props = {**props, "duracao": nova_dur}
            legendas = ae.remapear_legendas_cortes(legendas, intervalos)
            plano = None

    plano = plano or planejar_golpes(clipe, ffmpeg, props, arte)
    lento = plano["lento"]
    duracao = duracao_com_lento(props["duracao"], lento)
    legendas = ef.remapear_legendas(legendas, lento)
    golpes = [{**g, "t": ef.remapear(g["t"], lento)} for g in plano["golpes"]]

    # A vinheta vem antes da moldura e da legenda: escurece a imagem, não o texto.
    if arte.vinheta:
        vinheta = pasta_arte / "vinheta.png"
        desenhar_vinheta().save(vinheta)
        artes.append(vinheta)
        sobreposicoes.append({"entrada": len(artes), "inicio": None, "fim": None})

    # Camada vazia (sem marca, etiqueta nem título) não vira entrada do ffmpeg: seria um overlay à toa.
    moldura_img = desenhar_moldura(estilo, titulo, etiqueta)
    caixa = CAIXA_CLIPE if moldura_img.getbbox() else CAIXA_CLIPE_LIMPA
    geometria = None if enquadramento in (PREENCHER, ACAO) else geometria_do_clipe(props["largura"], props["altura"], caixa)
    tomadas_acao = None
    if enquadramento == ACAO:
        ritmo_acao = plano.get("ritmo") or ritmo_do_clipe(clipe, ffmpeg)
        brutas = (ritmo_acao or {}).get("tomadas_acao") or []
        tomadas_acao = [
            {"inicio": ef.remapear(t["inicio"], lento), "fim": ef.remapear(t["fim"], lento), "x_rel": t["x_rel"]}
            for t in brutas
        ]
    if moldura_img.getbbox():
        moldura = pasta_arte / "moldura.png"
        moldura_img.save(moldura)
        artes.append(moldura)
        sobreposicoes.append({"entrada": len(artes), "inicio": None, "fim": None})

    faixa = faixa_de_legendas(legendas, estilo, pasta_arte, duracao, estilo_legenda, com_caixa_legenda)
    if faixa:
        artes.append(faixa)
        sobreposicoes.append({"entrada": len(artes), "faixa": True, "y": FAIXA_Y0})

    inicio_card_ml = None
    if produto_ml:
        card_png = pasta_arte / "card_ml.png"
        desenhar_card_produto_ml(produto_ml, estilo).save(card_png)
        artes.append(card_png)
        janela_card = min(DURACAO_CARD_ML, max(1.2, duracao * 0.45))
        inicio_card_ml = round(max(0.0, duracao - janela_card), 2)
        sobreposicoes.append({
            "entrada": len(artes),
            "inicio": inicio_card_ml,
            "fim": round(duracao, 2),
            "y_expr": f"'max(0,(1-(t-{inicio_card_ml:.2f})/0.28)*320)'",
        })

    delogo = md.filtro_delogo(marca_dagua, (props["largura"], props["altura"])) if marca_dagua else ""
    tremidas = ef.janelas_dos_golpes(golpes, arte, duracao)
    janelas = ef.janelas_de_zoom(legendas, duracao) if arte.fator_zoom > 1.0 else []
    fator = max(arte.fator_zoom if janelas else 1.0, arte.zoom_no_golpe if tremidas else 1.0)
    filtro = filtro_de_composicao(
        geometria, sobreposicoes, duracao, cor_ffmpeg(estilo.destaque, 0.95),
        nitidez=ampliacao(props, enquadramento, caixa) > 1.05, com_barra=com_barra, delogo=delogo,
        cor=ef.filtro_de_cor(arte), zoom=(janelas + tremidas, fator) if fator > 1.0 else None,
        tremida=(tremidas, arte.tremida), brilho=arte.brilho,
        # com ramo ampliado (tremida ou zoom no golpe), a separação RGB vai nele, antes do recorte
        efeitos=ef.filtros_dos_golpes(golpes, arte, com_rgb=not tremidas),
        no_ramo_ampliado=ef.filtro_rgb(golpes, arte) if tremidas else "",
        cinemascope=arte.cinemascope,
        entrada="vel_v" if lento else "0:v",
        # a prévia não tem som: esticar o áudio nela deixaria uma saída do filtro sem destino, e o ffmpeg recusa
        prefixo=ef.filtro_de_velocidade(lento, props["duracao"], props["tem_audio"] and previa_em is None)
        if lento else "",
        tomadas_acao=tomadas_acao)
    comando = comando_de_composicao(ffmpeg, clipe, artes, filtro, duracao, saida, props["tem_audio"],
                                    previa_em=previa_em, audio_do_filtro="vel_a" if lento else None)
    proc = subprocess.run(comando, capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise FalhaNaEdicao(f"o ffmpeg falhou ao tratar o clipe: {proc.stderr.strip()[-300:]}")
    if previa_em is None and config_audio.usa_mixagem:
        ae.aplicar_audio_estudio(saida, saida, ffmpeg, config_audio, duracao=duracao, legendas=legendas,
                                 golpes=golpes, arte=arte, inicio_card_ml=inicio_card_ml)
    return duracao


def previa(clipe, *, tema: Tema, em: float, legendas=(), titulo: str = "", etiqueta: str = "", marca: str = "",
           logo=None, enquadramento: str = INTEIRO, com_caixa_legenda: bool = False, com_barra: bool = False,
           marca_dagua=None, arte: ef.DirecaoDeArte = ef.SEM_ARTE, estilo_legenda: str = CLASSICA,
           ffmpeg=None, plano: dict | None = None, produto_ml: dict | None = None) -> Image.Image:
    """
    Um quadro do vídeo final, com marca apagada, cor, zoom e legenda — em segundos, e não no minuto que leva a
    renderização inteira. Serve para acertar a direção de arte antes de montar.
    """
    executavel = ffmpeg or localizar_ffmpeg()
    props = sondar_clipe(clipe, executavel)
    plano = plano or planejar_golpes(clipe, executavel, props, arte)
    fim = duracao_com_lento(props["duracao"], plano["lento"])        # com câmera lenta, o vídeo fica mais longo
    with tempfile.TemporaryDirectory(prefix="previa_") as tmp:
        saida = Path(tmp) / "previa.png"
        tratar_clipe(clipe, estilo=rg.criar_estilo(tema, marca, logo), titulo=titulo, legendas=legendas,
                     etiqueta=etiqueta, saida=saida, ffmpeg=executavel, pasta_arte=tmp, props=props,
                     enquadramento=enquadramento, com_caixa_legenda=com_caixa_legenda, com_barra=com_barra,
                     marca_dagua=marca_dagua, arte=arte, estilo_legenda=estilo_legenda, plano=plano,
                     produto_ml=produto_ml, previa_em=min(max(0.0, em), max(0.0, fim - 0.1)))
        with Image.open(saida) as quadro:
            return quadro.convert("RGB")



# ==============================================================================
# LEGENDA EM ARQUIVO (.srt)
# ==============================================================================
def _tempo_srt(segundos: float) -> str:
    ms = max(0, int(round(float(segundos) * 1000)))
    horas, resto = divmod(ms, 3_600_000)
    minutos, resto = divmod(resto, 60_000)
    segundos, ms = divmod(resto, 1000)
    return f"{horas:02d}:{minutos:02d}:{segundos:02d},{ms:03d}"


def escrever_srt(legendas, caminho, deslocamento: float = 0.0):
    """
    Legenda em arquivo separado, para onde ela serve: YouTube e Facebook aceitam um .srt por idioma e escolhem
    sozinhos pelo idioma de quem assiste. Instagram e TikTok não — lá a legenda precisa estar queimada no vídeo.
    `deslocamento` é o tempo dos cartões que vêm antes do clipe no vídeo final.
    """
    blocos = []
    for i, bloco in enumerate(legendas, start=1):
        inicio, fim = _tempo_srt(bloco["inicio"] + deslocamento), _tempo_srt(bloco["fim"] + deslocamento)
        blocos.append(f"{i}\n{inicio} --> {fim}\n{bloco['texto']}\n")
    Path(caminho).write_text("\n".join(blocos), encoding="utf-8")
    return str(caminho)


# ==============================================================================
# CAPA, FECHO E MONTAGEM FINAL
# ==============================================================================
def primeira_frase(texto: str, limite: int = MAX_TITULO) -> str:
    """Primeira frase do texto, encurtada: serve de título quando só existe a fala do roteiro."""
    texto = " ".join(str(texto).split())
    corte = re.split(r"(?<=[.!?])\s", texto, maxsplit=1)[0] if texto else ""
    return cortar(corte or texto, limite)


def cenas_do_roteiro(roteiro: dict, titulo_corte: str = "") -> tuple:
    """
    Sugere a cena de capa e a de fecho a partir do roteiro gerado na aba (o usuário edita tudo na tela).
    Procura pelo bloco: "Gancho" vira a capa, "CTA"/"Chamada" vira o fecho; sem isso, a primeira e a última.

    Roteiro em modo degradado é ignorado de propósito. Nesse caso ele é o roteiro-modelo fixo da TACTO Studio,
    que não tem nenhuma relação com o vídeo analisado: na aba ele aparece como texto, com aviso, mas queimado
    dentro de um vídeo viraria propaganda de outra empresa em cima do conteúdo de quem publica. Sem roteiro,
    sobra o que de fato veio do vídeo — o título do corte —, e o resto o usuário escreve.
    """
    if roteiro.get("degradado"):
        roteiro = {}                                   # nada dele entra no vídeo: nem as cenas, nem os títulos
    cenas = [c for c in roteiro.get("cenas", []) if isinstance(c, dict)]

    def achar(palavras, padrao):
        for cena in cenas:
            if any(p in str(cena.get("bloco", "")).lower() for p in palavras):
                return cena
        return padrao
    vazia = {"fala": "", "bloco": ""}
    gancho = achar(("gancho", "hook"), cenas[0] if cenas else vazia)
    fecho = achar(("cta", "chamada", "ação", "acao"), cenas[-1] if cenas else vazia)
    titulos = [t for t in roteiro.get("titulos_capa", []) if str(t).strip()]

    capa = {"layout": "titulo", "tag": "", "titulo": cortar(titulos[0] if titulos else titulo_corte, MAX_TITULO),
            "fala": gancho.get("fala", ""), "itens": [], "rotulos": [], "destaque_valor": "",
            "destaque_rotulo": "", "botao": ""}
    final = {"layout": "cta", "tag": "", "titulo": primeira_frase(fecho.get("fala", "")),
             "fala": fecho.get("fala", ""), "itens": [], "rotulos": [], "destaque_valor": "",
             "destaque_rotulo": "", "botao": ""}
    return capa, final


def _renderizar_cartao(cena: dict, tema: Tema, *, voz, marca, logo, pasta, nome: str) -> tuple:
    """Renderiza um cartão de uma cena só com o renderizador do modo livre (mesmo codec, para juntar sem recodificar)."""
    dados = rg.renderizar_video({"cenas": [cena]}, tema, voz=voz, marca=marca, logo=logo,
                                nome_arquivo=nome, pasta_saida=pasta)
    return dados["caminho"], dados["duracao_segundos"]


def juntar(partes: list, saida, ffmpeg: str, pasta) -> None:
    """Junta sem recodificar (todas as partes saem do mesmo encoder); se os parâmetros não baterem, recodifica."""
    if len(partes) == 1:
        shutil.move(partes[0], saida)        # sem cartões, o clipe tratado já é o vídeo final
        return
    lista = Path(pasta) / "partes.txt"
    lista.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in partes), encoding="utf-8")
    base = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista)]
    proc = subprocess.run([*base, "-c", "copy", "-movflags", "+faststart", str(saida)],
                          capture_output=True, text=True, errors="ignore")
    if proc.returncode == 0:
        return
    proc = subprocess.run([*base, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(saida)],
                          capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise FalhaNaEdicao(f"o ffmpeg falhou ao juntar as partes: {proc.stderr.strip()[-300:]}")


def montar_reels(clipe, *, tema: Tema, titulo: str, legendas=(), etiqueta: str = "", marca: str = "", logo=None,
                 capa: dict | None = None, fecho: dict | None = None, voz: str | None = None,
                 enquadramento: str = INTEIRO, com_caixa_legenda: bool = False, com_barra: bool = False,
                 marca_dagua=None, arte: ef.DirecaoDeArte = ef.SEM_ARTE, estilo_legenda: str = CLASSICA,
                 produto_ml: dict | None = None, config_audio: ae.ConfigAudio = ae.SEM_AUDIO_EXTRA,
                 nome_arquivo: str = "reels.mp4", pasta_saida=None, ffmpeg=None, progresso=None) -> dict:
    """
    Devolve {"caminho", "duracao_segundos", "partes", "nomes_das_partes", "srt"} com o vídeo final 1080x1920.

    `capa` e `fecho` são cenas no formato do renderizador livre (podem ser None para gerar só o clipe tratado).
    `voz=None` deixa os cartões mudos — o áudio do clipe continua intacto de qualquer jeito.
    Havendo legendas, um .srt sai junto, já deslocado pelo tempo da capa.
    """
    if not Path(clipe).exists():
        raise FalhaNaEdicao("o clipe ainda não foi gerado; fatie o corte antes de montar o vídeo")
    try:
        executavel = ffmpeg or localizar_ffmpeg()
    except RuntimeError as erro:
        raise FalhaNaEdicao(str(erro)) from erro

    pasta_saida = Path(pasta_saida or PASTA_SAIDA)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / (nome_arquivo if nome_arquivo.endswith(".mp4") else nome_arquivo + ".mp4")
    estilo = rg.criar_estilo(tema, marca, logo)
    partes, duracoes, nomes = [], [], []

    with tempfile.TemporaryDirectory(prefix="reels_") as tmp:
        tmp = Path(tmp)
        if capa:
            if progresso:
                progresso(0.05, "Desenhando o cartão de capa...")
            caminho, duracao = _renderizar_cartao(capa, tema, voz=voz, marca=marca, logo=logo, pasta=tmp, nome="capa.mp4")
            partes.append(caminho)
            duracoes.append(duracao)
            nomes.append("capa")

        if progresso:
            progresso(0.40, "Reenquadrando o clipe em 9:16 e queimando a legenda...")
        props = sondar_clipe(clipe, executavel)
        plano = planejar_golpes(clipe, executavel, props, arte)
        tratado = tmp / "clipe_tratado.mp4"
        duracoes.append(tratar_clipe(clipe, estilo=estilo, titulo=titulo, legendas=legendas, etiqueta=etiqueta,
                                     saida=tratado, ffmpeg=executavel, pasta_arte=tmp, props=props,
                                     enquadramento=enquadramento, com_caixa_legenda=com_caixa_legenda,
                                     com_barra=com_barra, marca_dagua=marca_dagua, arte=arte,
                                     estilo_legenda=estilo_legenda, plano=plano,
                                     produto_ml=produto_ml, config_audio=config_audio))
        legendas = ef.remapear_legendas(legendas, plano["lento"])          # o .srt segue a câmera lenta
        partes.append(str(tratado))
        nomes.append("clipe")

        if fecho:
            if progresso:
                progresso(0.80, "Desenhando a chamada final...")
            caminho, duracao = _renderizar_cartao(fecho, tema, voz=voz, marca=marca, logo=logo, pasta=tmp, nome="fecho.mp4")
            partes.append(caminho)
            duracoes.append(duracao)
            nomes.append("chamada final")

        if progresso:
            progresso(0.92, "Juntando capa, clipe e fecho...")
        juntar(partes, destino, executavel, tmp)

    if progresso:
        progresso(1.0, "Vídeo pronto!")
    srt = escrever_srt(legendas, destino.with_suffix(".srt"), deslocamento=duracoes[0] if capa else 0.0) if legendas else None
    return {"caminho": str(destino), "duracao_segundos": round(sum(duracoes), 1),
            "partes": [round(d, 1) for d in duracoes], "nomes_das_partes": nomes, "srt": srt}


# ==============================================================================
# EDIÇÃO MULTI-TRECHO (vários pedaços do vídeo numa peça só)
# ==============================================================================
def juntar_com_transicao(partes: list, duracoes: list, transicao: str, saida, ffmpeg: str) -> None:
    """Emenda com xfade: recodifica a peça inteira uma vez a mais — por isso só quando pedem transição."""
    comando = [ffmpeg, "-y", "-loglevel", "error"]
    for parte in partes:
        comando += ["-i", str(parte)]
    comando += ["-filter_complex", ef.filtro_de_transicoes(duracoes, transicao, fps=FPS),
                "-map", "[vfinal]", "-map", "[afinal]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", "44100", "-movflags", "+faststart", str(saida)]
    proc = subprocess.run(comando, capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise FalhaNaEdicao(f"o ffmpeg falhou ao emendar com transição: {proc.stderr.strip()[-300:]}")


def montar_edicao(trechos: list, *, tema: Tema, marca: str = "", logo=None, enquadramento: str = INTEIRO,
                  com_caixa_legenda: bool = False, com_barra: bool = False, marca_dagua=None,
                  arte: ef.DirecaoDeArte = ef.SEM_ARTE, estilo_legenda: str = CLASSICA,
                  produto_ml: dict | None = None, config_audio: ae.ConfigAudio = ae.SEM_AUDIO_EXTRA,
                  nome_arquivo: str = "edicao.mp4", pasta_saida=None, ffmpeg=None, progresso=None) -> dict:
    """
    Trata cada trecho como o `montar_reels` trata um clipe e emenda todos numa peça só.

    `trechos` é uma lista de {"clipe": caminho, "legendas": [...], "titulo": str, "etiqueta": str}, e cada um
    pode trazer a própria "marca_dagua" (caixa em píxeis) — senão vale a geral. Cada trecho é reenquadrado e
    legendado por conta própria, e o .srt final soma os deslocamentos: a legenda do terceiro trecho tem que
    contar o tempo dos dois primeiros. Com transição, cada emenda sobrepõe um pedaço do trecho anterior, e o
    deslocamento desconta isso.
    """
    if not trechos:
        raise FalhaNaEdicao("a edição não tem nenhum trecho")
    faltando = [t["clipe"] for t in trechos if not Path(t["clipe"]).exists()]
    if faltando:
        raise FalhaNaEdicao(f"faltou gerar {len(faltando)} trecho(s) antes de montar a edição")
    try:
        executavel = ffmpeg or localizar_ffmpeg()
    except RuntimeError as erro:
        raise FalhaNaEdicao(str(erro)) from erro

    pasta_saida = Path(pasta_saida or PASTA_SAIDA)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / (nome_arquivo if nome_arquivo.endswith(".mp4") else nome_arquivo + ".mp4")
    estilo = rg.criar_estilo(tema, marca, logo)
    partes, duracoes, legendas_dos_trechos = [], [], []

    with tempfile.TemporaryDirectory(prefix="edicao_") as tmp:
        tmp = Path(tmp)
        for i, trecho in enumerate(trechos, start=1):
            if progresso:
                progresso(0.05 + 0.80 * (i - 1) / len(trechos), f"Tratando o trecho {i} de {len(trechos)}...")
            pasta_arte = tmp / f"arte_{i}"
            pasta_arte.mkdir()
            props = sondar_clipe(trecho["clipe"], executavel)
            plano = planejar_golpes(trecho["clipe"], executavel, props, arte)
            tratado = tmp / f"trecho_{i:02d}.mp4"
            card_deste_trecho = produto_ml if i == len(trechos) else None
            duracao = tratar_clipe(trecho["clipe"], estilo=estilo, titulo=trecho.get("titulo", ""),
                                   legendas=trecho.get("legendas", ()), etiqueta=trecho.get("etiqueta", ""),
                                   saida=tratado, ffmpeg=executavel, pasta_arte=pasta_arte, props=props,
                                   enquadramento=enquadramento, com_caixa_legenda=com_caixa_legenda,
                                   com_barra=com_barra, marca_dagua=trecho.get("marca_dagua", marca_dagua),
                                   arte=arte, estilo_legenda=estilo_legenda, plano=plano,
                                   produto_ml=card_deste_trecho, config_audio=config_audio)
            partes.append(str(tratado))
            duracoes.append(duracao)
            legendas_dos_trechos.append(ef.remapear_legendas(trecho.get("legendas", ()), plano["lento"]))

        com_transicao = ef.usa_transicao(arte, duracoes)
        if com_transicao:
            if progresso:
                progresso(0.88, f"Emendando os {len(partes)} trechos com transição...")
            juntar_com_transicao(partes, duracoes, arte.transicao, destino, executavel)
            inicios = ef.inicios_com_transicao(duracoes)
            total = sum(duracoes) - ef.DURACAO_TRANSICAO * (len(duracoes) - 1)
        else:
            if progresso:
                progresso(0.92, f"Emendando os {len(partes)} trechos...")
            juntar(partes, destino, executavel, tmp)
            inicios = [sum(duracoes[:i]) for i in range(len(duracoes))]
            total = sum(duracoes)

    legendas_inteiras = [{**b, "inicio": b["inicio"] + inicio, "fim": b["fim"] + inicio}
                         for blocos, inicio in zip(legendas_dos_trechos, inicios) for b in blocos]
    if progresso:
        progresso(1.0, "Edição pronta!")
    srt = escrever_srt(legendas_inteiras, destino.with_suffix(".srt")) if legendas_inteiras else None
    return {"caminho": str(destino), "duracao_segundos": round(total, 1),
            "partes": [round(d, 1) for d in duracoes],
            "nomes_das_partes": [f"trecho {i}" for i in range(1, len(partes) + 1)], "srt": srt,
            "transicao": arte.transicao if com_transicao else "corte"}

