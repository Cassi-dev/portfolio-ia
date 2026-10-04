"""
Motor de Renderização de Vídeo Animado em Alta Definição (Reels/TikTok 9:16)
Identidade Visual Oficial da TACTO Studio (Brandboard Oficial)
Paleta: Obsidian Dark (#0D1117), Graphite Surface (#161B22), Hyper Cyan (#00F0FF), Electric Mint (#10F984)
Cenas com animações de cliques de botões, barras de carregamento, contadores financeiros e caso de exemplo (Casa Exemplo).

v2.0 — Revisão de Qualidade:
  - FPS 24 (broadcast quality)
  - Fade-in/fade-out por cena (0.5s)
  - Easing curves (ease_out cubic)
  - Fix texto cortado / tofu Unicode
  - Demonstração no mockup PWA
  - Cursor pointer triangular + ripple effect
  - Cards com reveal staggered (slide-up)
  - Glow effect nos labels cyan
  - Gradiente horizontal no CTA
  - Partículas decorativas flutuantes
  - Pilares com animação escalonada
  - Encoding H.264 High Profile 8Mbps estéreo
"""

import os
import sys
import asyncio
import subprocess
import re
import math
import shutil
import sqlite3
from PIL import Image, ImageDraw, ImageFont
import edge_tts

from core.midia import localizar_ffmpeg

sys.stdout.reconfigure(encoding='utf-8')

DIRETORIO_ATUAL = os.path.dirname(os.path.abspath(__file__))
FFMPEG_PATH = localizar_ffmpeg()

PASTA_OUTPUT = os.path.join(DIRETORIO_ATUAL, "videos_gerados")
PASTA_ASSETS = os.path.join(DIRETORIO_ATUAL, "assets_tacto")
PASTA_STORYBOARD = os.path.join(PASTA_ASSETS, "storyboard")
os.makedirs(PASTA_OUTPUT, exist_ok=True)
os.makedirs(PASTA_ASSETS, exist_ok=True)
os.makedirs(PASTA_STORYBOARD, exist_ok=True)

# Fontes padrão do Windows
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf" if os.path.exists("C:/Windows/Fonts/segoeuib.ttf") else "arialbd.ttf"
FONT_REGULAR = "C:/Windows/Fonts/segoeui.ttf" if os.path.exists("C:/Windows/Fonts/segoeui.ttf") else "arial.ttf"

# Cores Oficiais do Brandboard da TACTO Studio
COLOR_BG = (13, 17, 23)        # #0D1117 Obsidian Dark
COLOR_SURFACE = (22, 27, 34)   # #161B22 Graphite Surface
COLOR_BORDER = (48, 54, 61)    # #30363D Border
COLOR_CYAN = (0, 240, 255)     # #00F0FF Hyper Cyan
COLOR_MINT = (16, 249, 132)    # #10F984 Electric Mint
COLOR_WHITE = (240, 246, 252)  # #F0F6FC Pure Light
COLOR_GRAY = (139, 148, 158)   # #8B949E Slate Gray
COLOR_RED = (234, 29, 44)      # #EA1D2C iFood Red / Alert
COLOR_RED_BG = (45, 18, 22)

# Configuração global de renderização
FPS = 24
FADE_FRAMES = int(0.5 * FPS)  # 12 frames = 0.5s de fade

# ==============================================================================
# FUNÇÕES UTILITÁRIAS
# ==============================================================================

def moeda_br(valor):
    """1234.5 -> '1.234,50' (o padrão :,.2f do Python sai no formato americano)."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def metricas_pwa(caminho=None):
    """Total, nº de pedidos e ticket médio do canal PWA TACTO na base de demonstração, ou None se ela não existir."""
    caminho = caminho or os.path.join(DIRETORIO_ATUAL, "..", "projeto_05_gerador_sql", "tacto_negocios.db")
    if not os.path.exists(caminho):
        return None
    try:
        conn = sqlite3.connect(f"file:{os.path.abspath(caminho)}?mode=ro", uri=True)
        try:
            pedidos, total = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(valor_total), 0) FROM pedidos WHERE canal_venda = 'PWA TACTO' AND status = 'Concluído'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return {"pedidos": pedidos, "total": total, "ticket": total / pedidos if pedidos else 0.0}

def ease_out(t):
    """Curva de easing cúbico out: desacelera suavemente."""
    return 1 - (1 - min(1.0, max(0.0, t))) ** 3

def ease_in_out(t):
    """Curva de easing cúbico in-out."""
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        return 4 * t * t * t
    else:
        return 1 - (-2 * t + 2) ** 3 / 2

def lerp_color(c1, c2, t):
    """Interpola linearmente entre duas cores RGB."""
    t = min(1.0, max(0.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))

def aplicar_fade(img, idx, total_frames):
    """Aplica fade-in nos primeiros FADE_FRAMES e fade-out nos últimos FADE_FRAMES."""
    if idx < FADE_FRAMES:
        alpha = idx / FADE_FRAMES
    elif idx >= total_frames - FADE_FRAMES:
        alpha = (total_frames - 1 - idx) / FADE_FRAMES
    else:
        return img

    alpha = max(0.0, min(1.0, alpha))
    black = Image.new("RGB", img.size, COLOR_BG)
    return Image.blend(black, img, alpha)

def quebrar_texto(texto, draw, font, max_largura):
    """Quebra texto em múltiplas linhas para não estourar a largura limite."""
    palavras = texto.split()
    linhas = []
    linha_atual = []

    for palavra in palavras:
        linha_teste = " ".join(linha_atual + [palavra])
        bbox = draw.textbbox((0, 0), linha_teste, font=font)
        largura = bbox[2] - bbox[0]
        if largura <= max_largura:
            linha_atual.append(palavra)
        else:
            if linha_atual:
                linhas.append(" ".join(linha_atual))
            linha_atual = [palavra]
    if linha_atual:
        linhas.append(" ".join(linha_atual))
    return linhas

def desenhar_cartao(draw, xy, fill, outline=None, width=2, radius=18):
    """Desenha retângulo com cantos arredondados suave."""
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

def desenhar_texto_glow(draw, pos, texto, font, cor_principal, cor_glow=None, offset=2):
    """Desenha texto com efeito de glow sutil (dupla renderização com offset)."""
    if cor_glow is None:
        cor_glow = tuple(list(cor_principal[:3]) + []) if len(cor_principal) == 3 else cor_principal
        # Criar versão mais escura/translúcida
        cor_glow = tuple(max(0, c - 80) for c in cor_principal[:3])
    x, y = pos
    # Glow: desenhar 4 vezes com offset em cada direção
    for dx, dy in [(-offset, 0), (offset, 0), (0, -offset), (0, offset)]:
        draw.text((x + dx, y + dy), texto, font=font, fill=cor_glow)
    # Principal
    draw.text(pos, texto, font=font, fill=cor_principal)

def desenhar_gradiente_horizontal(draw, xy, cor_esquerda, cor_direita, radius=22):
    """Desenha um retângulo com gradiente horizontal usando faixas de 1px."""
    x1, y1, x2, y2 = xy
    largura = x2 - x1
    for i in range(largura):
        t = i / max(1, largura - 1)
        cor = lerp_color(cor_esquerda, cor_direita, t)
        draw.line([(x1 + i, y1 + radius), (x1 + i, y2 - radius)], fill=cor)
    # Redesenhar contorno arredondado por cima para manter os cantos
    desenhar_cartao(draw, xy, fill=None, outline=lerp_color(cor_esquerda, cor_direita, 0.5), width=2, radius=radius)

def desenhar_cursor_pointer(draw, cx, cy, tamanho=28):
    """Desenha um cursor ponteiro triangular realista."""
    # Triângulo principal (branco)
    pontos = [
        (cx, cy),                          # Ponta superior
        (cx, cy + tamanho),                # Inferior esquerda
        (cx + tamanho * 0.35, cy + tamanho * 0.72),  # Cotovelo
        (cx + tamanho * 0.65, cy + tamanho * 0.95),  # Ponta inferior do dedo
        (cx + tamanho * 0.8, cy + tamanho * 0.8),    # Lateral do dedo
        (cx + tamanho * 0.45, cy + tamanho * 0.58),  # Junção
        (cx + tamanho * 0.7, cy + tamanho * 0.3),    # Ponta direita
    ]
    # Sombra
    pontos_sombra = [(x + 3, y + 3) for x, y in pontos]
    draw.polygon(pontos_sombra, fill=(30, 30, 30))
    # Cursor branco com borda preta
    draw.polygon(pontos, fill=(255, 255, 255), outline=(20, 20, 20))

def desenhar_ripple(draw, cx, cy, progresso, raio_max=80):
    """Desenha um ripple effect circular expandindo do ponto de clique."""
    if progresso <= 0 or progresso > 1:
        return
    raio = int(raio_max * progresso)
    # Alpha simulado: grossura do anel diminui com o progresso
    grossura = max(1, int(4 * (1 - progresso)))
    cor_r = lerp_color(COLOR_CYAN, COLOR_BG, progresso)
    draw.ellipse(
        (cx - raio, cy - raio, cx + raio, cy + raio),
        outline=cor_r, width=grossura
    )

def desenhar_particulas(draw, p, largura=1080, altura=1920, n=10, seed_offset=0):
    """Desenha partículas decorativas flutuantes com movimento senoidal."""
    import random
    rng = random.Random(42 + seed_offset)
    for i in range(n):
        base_x = rng.randint(60, largura - 60)
        base_y = rng.randint(200, altura - 200)
        raio = rng.randint(2, 4)
        # Movimento senoidal lento
        dx = int(math.sin(p * math.pi * 2 + i * 0.7) * 15)
        dy = int(math.cos(p * math.pi * 2 + i * 1.1) * 10)
        cor = COLOR_CYAN if i % 2 == 0 else COLOR_MINT
        # Alpha simulado: cor mais escura
        cor_alpha = tuple(max(0, c - 140) for c in cor)
        draw.ellipse(
            (base_x + dx - raio, base_y + dy - raio,
             base_x + dx + raio, base_y + dy + raio),
            fill=cor_alpha
        )

def extrair_duracao_audio(caminho_audio):
    """Usa ffmpeg para medir a duração exata do áudio em segundos."""
    cmd = [FFMPEG_PATH, "-i", caminho_audio]
    proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True, errors="ignore")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if m:
        h, mins, s = m.groups()
        return int(h) * 3600 + int(mins) * 60 + float(s)
    return 4.0

async def sintetizar_audio_cena(texto, caminho_saida, voz="pt-BR-AntonioNeural"):
    """Sintetiza áudio neural via edge-tts."""
    com = edge_tts.Communicate(texto, voz)
    await com.save(caminho_saida)

# ==============================================================================
# CABEÇALHO E RODAPÉ PADRÃO
# ==============================================================================

def desenhar_cabecalho_oficial(draw, img, cena_num, total_cenas, tag_texto, cor_tag=COLOR_RED):
    """Desenha o cabeçalho padronizado da TACTO Studio com logo e indicador de cena."""
    # Top Bar
    desenhar_cartao(draw, (60, 60, 1020, 150), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=16)

    # Logo TACTO Studio
    caminho_logo = os.path.join(PASTA_ASSETS, "logo_tacto.png")
    if os.path.exists(caminho_logo):
        try:
            logo_img = Image.open(caminho_logo).convert("RGBA")
            w_orig, h_orig = logo_img.size
            ratio = 44.0 / h_orig
            logo_img = logo_img.resize((int(w_orig * ratio), 44), Image.Resampling.LANCZOS)
            img.paste(logo_img, (85, 83), logo_img)
        except Exception:
            f_logo = ImageFont.truetype(FONT_BOLD, 30)
            draw.text((90, 88), "TACTO STUDIO", font=f_logo, fill=COLOR_CYAN)
    else:
        f_logo = ImageFont.truetype(FONT_BOLD, 30)
        draw.text((90, 88), "TACTO STUDIO", font=f_logo, fill=COLOR_CYAN)

    f_meta = ImageFont.truetype(FONT_BOLD, 26)
    draw.text((730, 90), f"CENA {cena_num}/{total_cenas}  |  9:16", font=f_meta, fill=COLOR_GRAY)

    # Tag Badge
    f_tag = ImageFont.truetype(FONT_BOLD, 30)
    bbox_tag = draw.textbbox((0, 0), tag_texto, font=f_tag)
    w_tag = bbox_tag[2] - bbox_tag[0] + 50
    desenhar_cartao(draw, (60, 180, 60 + w_tag, 245), fill=cor_tag, radius=12)
    draw.text((85, 195), tag_texto, font=f_tag, fill=(255, 255, 255))

def desenhar_legenda_inferior(draw, texto_narracao):
    """Desenha a caixa inferior com a transcrição da locução para vídeos mudos."""
    f_leg_head = ImageFont.truetype(FONT_BOLD, 24)
    f_leg = ImageFont.truetype(FONT_BOLD, 34)

    desenhar_cartao(draw, (60, 1540, 1020, 1850), fill=COLOR_SURFACE, outline=COLOR_CYAN, width=3, radius=20)
    draw.text((90, 1565), "LOCUCAO E LEGENDA SINCRONIZADA:", font=f_leg_head, fill=COLOR_CYAN)

    linhas = quebrar_texto(f'"{texto_narracao}"', draw, f_leg, max_largura=860)
    y = 1615
    for l in linhas[:4]:
        draw.text((90, y), l, font=f_leg, fill=COLOR_WHITE)
        y += 48

# ==============================================================================
# CENA 1: ANIMAÇÃO DE DRENO FINANCEIRO (iFood 27%)
# ==============================================================================
def renderizar_frames_cena1(duracao_seg, pasta_saida, cena_data):
    total_frames = int(duracao_seg * FPS)
    f_tit = ImageFont.truetype(FONT_BOLD, 48)
    f_card_t = ImageFont.truetype(FONT_BOLD, 34)
    f_card_sub = ImageFont.truetype(FONT_REGULAR, 26)
    f_counter = ImageFont.truetype(FONT_BOLD, 56)  # Reduzido de 72 para caber

    for idx in range(total_frames):
        p = idx / max(1, total_frames - 1)
        img = Image.new("RGB", (1080, 1920), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        desenhar_cabecalho_oficial(draw, img, 1, 4, "ALERTA DE MARGEM", COLOR_RED)

        # Título
        draw.text((60, 275), "Voce ja calculou quanto perde", font=f_tit, fill=COLOR_WHITE)
        draw.text((60, 335), "no iFood todo santo mes?", font=f_tit, fill=COLOR_WHITE)

        # Contador animado de perda de taxa (0% até 27%)
        taxa_anim = min(27, int(p * 35))
        faturamento_base = 50000
        perda_mensal = int(faturamento_base * (taxa_anim / 100.0))
        perda_anual = perda_mensal * 12

        # Card Central de Impacto
        desenhar_cartao(draw, (60, 420, 1020, 780), fill=COLOR_RED_BG, outline=COLOR_RED, width=3, radius=22)
        draw.text((95, 445), "TAXA DO MARKETPLACE POR PEDIDO:", font=f_card_sub, fill=COLOR_GRAY)
        draw.text((95, 485), f"- {taxa_anim}% DO SEU", font=f_counter, fill=(255, 77, 77))
        draw.text((95, 555), f"  FATURAMENTO", font=f_counter, fill=(255, 77, 77))

        # Barra de drenagem
        largura_barra_max = 840
        largura_atual = int((taxa_anim / 27.0) * largura_barra_max)
        desenhar_cartao(draw, (95, 640, 95 + largura_barra_max, 670), fill=(20, 20, 25), radius=10)
        if largura_atual > 10:
            desenhar_cartao(draw, (95, 640, 95 + largura_atual, 670), fill=COLOR_RED, radius=10)

        draw.text((95, 695), f"Faturamento de R$ 50.000/mes >>", font=f_card_sub, fill=COLOR_WHITE)
        draw.text((95, 730), f"Prejuizo mensal: R$ {moeda_br(perda_mensal)}", font=f_card_t, fill=(255, 120, 120))

        # Cards Secundários com slide-in animado
        # Card 1: slide-in começa em p=0.15
        t_card1 = ease_out(max(0, (p - 0.15) / 0.15))
        offset_x1 = int((1 - t_card1) * 400)  # Slide da direita
        if t_card1 > 0:
            desenhar_cartao(draw, (60 + offset_x1, 810, 1020 + offset_x1, 940), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=18)
            draw.ellipse((95 + offset_x1, 845, 135 + offset_x1, 885), fill=COLOR_RED)
            draw.text((108 + offset_x1, 850), "X", font=f_card_t, fill=(255, 255, 255))
            draw.text((155 + offset_x1, 840), "Seus clientes nao sao seus", font=f_card_t, fill=COLOR_WHITE)
            draw.text((155 + offset_x1, 885), "A plataforma esconde os contatos.", font=f_card_sub, fill=COLOR_GRAY)

        # Card 2: slide-in começa em p=0.25
        t_card2 = ease_out(max(0, (p - 0.25) / 0.15))
        offset_x2 = int((1 - t_card2) * 400)
        if t_card2 > 0:
            desenhar_cartao(draw, (60 + offset_x2, 970, 1020 + offset_x2, 1100), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=18)
            draw.ellipse((95 + offset_x2, 1005, 135 + offset_x2, 1045), fill=COLOR_RED)
            draw.text((108 + offset_x2, 1010), "X", font=f_card_t, fill=(255, 255, 255))
            draw.text((155 + offset_x2, 1000), "Repasse atrasado em ate 30 dias", font=f_card_t, fill=COLOR_WHITE)
            draw.text((155 + offset_x2, 1045), "Seu capital fica bloqueado.", font=f_card_sub, fill=COLOR_GRAY)

        # Card 3 (NOVO): slide-in começa em p=0.35
        t_card3 = ease_out(max(0, (p - 0.35) / 0.15))
        offset_x3 = int((1 - t_card3) * 400)
        if t_card3 > 0:
            desenhar_cartao(draw, (60 + offset_x3, 1130, 1020 + offset_x3, 1260), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=18)
            draw.ellipse((95 + offset_x3, 1165, 135 + offset_x3, 1205), fill=COLOR_RED)
            draw.text((108 + offset_x3, 1170), "X", font=f_card_t, fill=(255, 255, 255))
            draw.text((155 + offset_x3, 1160), "Voce nao controla seu cardapio", font=f_card_t, fill=COLOR_WHITE)
            draw.text((155 + offset_x3, 1205), "O marketplace decide as regras do jogo.", font=f_card_sub, fill=COLOR_GRAY)

        # Sangria anual (aparece depois dos 3 cards)
        if p > 0.50:
            t_sangria = ease_out(min(1, (p - 0.50) / 0.10))
            alpha_y = int(30 * (1 - t_sangria))
            desenhar_cartao(draw, (60, 1300 + alpha_y, 1020, 1400 + alpha_y), fill=(50, 15, 15), outline=COLOR_RED, width=2, radius=14)
            f_sangria = ImageFont.truetype(FONT_BOLD, 30)
            draw.text((95, 1330 + alpha_y), f"Sangria anual acumulada: R$ {moeda_br(perda_anual)}", font=f_sangria, fill=(255, 100, 100))
            draw.text((95, 1365 + alpha_y), "DINHEIRO DEIXADO NA MESA!", font=f_card_sub, fill=COLOR_GRAY)

        desenhar_legenda_inferior(draw, cena_data["fala"])

        # Aplicar fade-in/fade-out
        img = aplicar_fade(img, idx, total_frames)

        frame_path = os.path.join(pasta_saida, f"c1_frame_{idx:04d}.png")
        img.save(frame_path)
    return total_frames

# ==============================================================================
# CENA 2: ANIMAÇÃO DE INTERAÇÃO DO PWA (Caso Real Casa Exemplo & Clique de Botão)
# ==============================================================================
def renderizar_frames_cena2(duracao_seg, pasta_saida, cena_data):
    total_frames = int(duracao_seg * FPS)
    f_tit = ImageFont.truetype(FONT_BOLD, 48)
    f_mockup_t = ImageFont.truetype(FONT_BOLD, 32)
    f_mockup_sub = ImageFont.truetype(FONT_REGULAR, 24)
    f_btn = ImageFont.truetype(FONT_BOLD, 32)
    f_stat = ImageFont.truetype(FONT_BOLD, 36)

    for idx in range(total_frames):
        p = idx / max(1, total_frames - 1)
        img = Image.new("RGB", (1080, 1920), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        desenhar_cabecalho_oficial(draw, img, 2, 4, "CANAL PROPRIO (CAC ZERO)", COLOR_MINT)

        # Título
        draw.text((60, 275), "PWA de Velocidade Extrema:", font=f_tit, fill=COLOR_WHITE)
        draw.text((60, 335), "0.3s para Abrir e Pedido Direto", font=f_tit, fill=COLOR_CYAN)

        # MOCKUP DE CELULAR / PWA EM AÇÃO
        desenhar_cartao(draw, (90, 420, 990, 1480), fill=(18, 22, 30), outline=COLOR_CYAN, width=3, radius=28)

        # Barra do PWA (URL & Status)
        desenhar_cartao(draw, (120, 450, 960, 510), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=1, radius=12)
        draw.ellipse((140, 473, 154, 487), fill=COLOR_MINT)
        draw.text((170, 467), "https://exemplo.app/casa-exemplo  (PWA Instalado)", font=f_mockup_sub, fill=COLOR_GRAY)
        draw.text((850, 467), "0.28s", font=f_mockup_t, fill=COLOR_MINT)

        # Bloco neutro com o texto "Imagem de exemplo" (sem usar arquivo de imagem)
        desenhar_cartao(draw, (120, 530, 960, 890), fill=(30, 35, 45), radius=16)
        txt_ex = "Imagem de exemplo"
        bbox_ex = draw.textbbox((0, 0), txt_ex, font=f_mockup_sub)
        w_ex = bbox_ex[2] - bbox_ex[0]
        h_ex = bbox_ex[3] - bbox_ex[1]
        draw.text((540 - w_ex // 2, 710 - h_ex // 2), txt_ex, font=f_mockup_sub, fill=COLOR_GRAY)

        # Informações do Produto Fictício
        draw.text((120, 915), "Hambúrguer Autoral (exemplo)", font=f_mockup_t, fill=COLOR_WHITE)
        draw.text((120, 960), "Casa Exemplo", font=f_mockup_sub, fill=COLOR_GRAY)
        draw.text((120, 1010), "R$ 48,90", font=f_stat, fill=COLOR_MINT)

        # ANIMAÇÃO DO CLIQUE NO BOTÃO
        foi_clicado = p >= 0.55
        esta_pressionando = 0.50 <= p < 0.55

        btn_fill = COLOR_MINT if foi_clicado else (COLOR_CYAN if not esta_pressionando else (0, 180, 200))
        btn_texto = "[ OK ] PEDIDO ENVIADO AO WHATSAPP!" if foi_clicado else ">> PEDIR NO WHATSAPP COM 1 TOQUE <<"

        # Efeito de escala ao pressionar
        scale = 0.96 if esta_pressionando else 1.0
        bw = int(840 * scale)
        bh = int(105 * scale)
        bx = 540 - bw // 2
        by = 1090 + int((105 - bh) / 2)

        desenhar_cartao(draw, (bx, by, bx + bw, by + bh), fill=btn_fill, radius=18)
        bbox_btxt = draw.textbbox((0, 0), btn_texto, font=f_btn)
        w_btxt = bbox_btxt[2] - bbox_btxt[0]
        draw.text((bx + (bw - w_btxt) // 2, by + 32), btn_texto, font=f_btn, fill=COLOR_BG)

        # Ripple effect no momento do clique
        if 0.50 <= p <= 0.65:
            ripple_prog = (p - 0.50) / 0.15
            desenhar_ripple(draw, 540, 1142, ripple_prog, raio_max=100)

        # Badge de Retenção
        desenhar_cartao(draw, (120, 1230, 960, 1430), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=16)
        draw.text((150, 1260), ">> 0% de comissao para marketplaces", font=f_mockup_t, fill=COLOR_WHITE)
        draw.text((150, 1315), ">> Pagamento via Pix direto no caixa", font=f_mockup_t, fill=COLOR_MINT)
        draw.text((150, 1370), ">> O cliente entra no seu CRM proprio", font=f_mockup_t, fill=COLOR_WHITE)

        # Cursor pointer triangular se movendo até o botão
        if p < 0.70:
            cur_p = min(1.0, p / 0.50)
            cur_x = int(300 + cur_p * 240)
            cur_y = int(1350 - cur_p * 220)
            desenhar_cursor_pointer(draw, cur_x, cur_y, tamanho=30)

        desenhar_legenda_inferior(draw, cena_data["fala"])

        # Aplicar fade
        img = aplicar_fade(img, idx, total_frames)

        frame_path = os.path.join(pasta_saida, f"c2_frame_{idx:04d}.png")
        img.save(frame_path)
    return total_frames

# ==============================================================================
# CENA 3: ANIMAÇÃO DE INTELIGÊNCIA ARTIFICIAL & TEXT-TO-SQL
# ==============================================================================
def renderizar_frames_cena3(duracao_seg, pasta_saida, cena_data):
    total_frames = int(duracao_seg * FPS)
    f_tit = ImageFont.truetype(FONT_BOLD, 48)
    f_sql_t = ImageFont.truetype(FONT_BOLD, 30)
    f_sql_sub = ImageFont.truetype(FONT_REGULAR, 24)
    f_metric_n = ImageFont.truetype(FONT_BOLD, 54)
    f_metric_lbl = ImageFont.truetype(FONT_BOLD, 26)

    prompt_completo = "Quanto faturamos via PWA proprio?"
    metricas = metricas_pwa()

    for idx in range(total_frames):
        p = idx / max(1, total_frames - 1)
        img = Image.new("RGB", (1080, 1920), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        desenhar_cabecalho_oficial(draw, img, 3, 4, "IA & DADOS EM TEMPO REAL", (129, 140, 248))

        # Título
        draw.text((60, 275), "As 4 Tecnologias da TACTO Studio", font=f_tit, fill=COLOR_WHITE)
        draw.text((60, 335), "Trabalhando Pelo Seu Negocio", font=f_tit, fill=COLOR_CYAN)

        # 1. Simulação do Prompt Text-to-SQL (Digitando em tempo real)
        letras_digitadas = int(min(1.0, p * 2.2) * len(prompt_completo))
        texto_atual = prompt_completo[:letras_digitadas] + ("_" if (idx % 6 < 3) else "")

        desenhar_cartao(draw, (60, 420, 1020, 560), fill=COLOR_SURFACE, outline=COLOR_CYAN, width=2, radius=18)
        draw.text((95, 445), "PERGUNTA DO GESTOR NO WHATSAPP COM IA:", font=f_sql_sub, fill=COLOR_GRAY)
        draw.text((95, 485), f'> "{texto_atual}"', font=f_sql_t, fill=COLOR_WHITE)

        # 2. Resposta da IA com Métricas Reais do Banco
        ja_respondeu = p >= 0.40
        if ja_respondeu:
            t_resp = ease_out(min(1, (p - 0.40) / 0.10))
            offset_y_resp = int(30 * (1 - t_resp))

            desenhar_cartao(draw, (60, 590 + offset_y_resp, 1020, 920 + offset_y_resp), fill=(20, 32, 45), outline=COLOR_MINT, width=2, radius=20)
            draw.text((95, 620 + offset_y_resp), "RESULTADO (TEXT-TO-SQL) - DADOS DE DEMONSTRACAO:", font=f_sql_sub, fill=COLOR_MINT)

            # Animar valor monetário subindo (números vêm da base de demonstração, não são fixos)
            prog_v = min(1.0, (p - 0.40) / 0.30)
            if metricas:
                draw.text((95, 665 + offset_y_resp), f"R$ {moeda_br(prog_v * metricas['total'])}", font=f_metric_n, fill=COLOR_WHITE)
                draw.text((95, 745 + offset_y_resp), f">> {int(prog_v * metricas['pedidos'])} pedidos concluidos pelo PWA", font=f_sql_t, fill=COLOR_WHITE)
                draw.text((95, 795 + offset_y_resp), f">> Margem de lucro: 100% no seu caixa", font=f_sql_sub, fill=COLOR_MINT)
                draw.text((95, 840 + offset_y_resp), f">> Ticket medio: R$ {moeda_br(metricas['ticket'])}", font=f_sql_sub, fill=COLOR_CYAN)
            else:
                draw.text((95, 700 + offset_y_resp), "Base de demonstracao indisponivel", font=f_sql_t, fill=COLOR_GRAY)

        # 3. As 4 Funcionalidades em Grade Visual (slide-up staggered)
        cards_data = [
            {"pos": (60, 950, 520, 1200), "lbl": "01. PWA SUB-0.5s", "l1": "Sem download em lojas.", "l2": "Abre instantaneo no 4G.", "l3": "Retencao maxima.", "start": 0.35},
            {"pos": (560, 950, 1020, 1200), "lbl": "02. ATENDENTE RAG", "l1": "IA no WhatsApp 24/7.", "l2": "Tira duvidas de pratos.", "l3": "Upsell automatico.", "start": 0.42},
            {"pos": (60, 1230, 520, 1480), "lbl": "03. CARTA SENSORIAL", "l1": "Fotos e videos em loop.", "l2": "Storytelling envolvente.", "l3": "Eleva o ticket medio.", "start": 0.49},
            {"pos": (560, 1230, 1020, 1480), "lbl": "04. TEXT-TO-SQL", "l1": "Relatorios imediatos.", "l2": "Pergunte em portugues.", "l3": "Controle absoluto.", "start": 0.56},
        ]

        for cd in cards_data:
            t_card = ease_out(max(0, (p - cd["start"]) / 0.12))
            if t_card <= 0:
                continue
            offset_y = int(40 * (1 - t_card))
            x1, y1, x2, y2 = cd["pos"]
            y1 += offset_y
            y2 += offset_y

            desenhar_cartao(draw, (x1, y1, x2, y2), fill=COLOR_SURFACE, outline=COLOR_BORDER, width=2, radius=16)
            # Label com glow
            desenhar_texto_glow(draw, (x1 + 30, y1 + 30), cd["lbl"], f_metric_lbl, COLOR_CYAN, offset=1)
            draw.text((x1 + 30, y1 + 80), cd["l1"], font=f_sql_sub, fill=COLOR_WHITE)
            draw.text((x1 + 30, y1 + 120), cd["l2"], font=f_sql_sub, fill=COLOR_GRAY)
            draw.text((x1 + 30, y1 + 160), cd["l3"], font=f_sql_sub, fill=COLOR_MINT)

        desenhar_legenda_inferior(draw, cena_data["fala"])

        # Aplicar fade
        img = aplicar_fade(img, idx, total_frames)

        frame_path = os.path.join(pasta_saida, f"c3_frame_{idx:04d}.png")
        img.save(frame_path)
    return total_frames

# ==============================================================================
# CENA 4: ANIMAÇÃO DE ENCERRAMENTO & CTA COM LOGO OFICIAL
# ==============================================================================
def renderizar_frames_cena4(duracao_seg, pasta_saida, cena_data):
    total_frames = int(duracao_seg * FPS)
    f_tit = ImageFont.truetype(FONT_BOLD, 50)
    f_sub = ImageFont.truetype(FONT_REGULAR, 30)
    f_btn = ImageFont.truetype(FONT_BOLD, 34)
    f_manifesto = ImageFont.truetype(FONT_REGULAR, 26)

    # Carregar logo oficial da TACTO
    caminho_logo = os.path.join(PASTA_ASSETS, "logo_tacto.png")
    logo_img = None
    if os.path.exists(caminho_logo):
        try:
            l_raw = Image.open(caminho_logo).convert("RGBA")
            w_orig, h_orig = l_raw.size
            ratio = 100.0 / h_orig
            logo_img = l_raw.resize((int(w_orig * ratio), 100), Image.Resampling.LANCZOS)
        except Exception:
            pass

    for idx in range(total_frames):
        p = idx / max(1, total_frames - 1)
        img = Image.new("RGB", (1080, 1920), color=COLOR_BG)
        draw = ImageDraw.Draw(img)

        # Partículas decorativas no background
        desenhar_particulas(draw, p, seed_offset=0)

        desenhar_cabecalho_oficial(draw, img, 4, 4, "PROXIMO PASSO", COLOR_MINT)

        # Card Central do Logo Oficial
        desenhar_cartao(draw, (60, 290, 1020, 890), fill=COLOR_SURFACE, outline=COLOR_CYAN, width=3, radius=24)

        if logo_img:
            lw, lh = logo_img.size
            img.paste(logo_img, (540 - lw // 2, 330), logo_img)
        else:
            f_l = ImageFont.truetype(FONT_BOLD, 60)
            draw.text((300, 340), "TACTO STUDIO", font=f_l, fill=COLOR_CYAN)

        # Tagline Oficial com glow
        desenhar_texto_glow(
            draw, (130, 470),
            '"Conexao direta. Zero intermediarios. Maxima conversao."',
            f_manifesto, COLOR_MINT, offset=1
        )

        # Três pilares com animação escalonada
        pilares = [
            ("[ OK ]  0% de comissao nas suas vendas", 0.15),
            ("[ OK ]  PWA sub-0.5s + Atendente com IA", 0.25),
            ("[ OK ]  Base de clientes 100% sua no WhatsApp", 0.35),
        ]

        for i, (texto_pilar, start_p) in enumerate(pilares):
            t_pilar = ease_out(max(0, (p - start_p) / 0.12))
            if t_pilar <= 0:
                continue
            offset_x = int(300 * (1 - t_pilar))
            y_base = 540 + i * 100
            desenhar_cartao(draw, (100 + offset_x, y_base, 980, y_base + 80), fill=(28, 35, 46), radius=12)
            draw.text((140 + offset_x, y_base + 25), texto_pilar, font=f_sub, fill=COLOR_WHITE)

        # Título de Fechamento
        draw.text((60, 940), "Assuma o Controle Total", font=f_tit, fill=COLOR_WHITE)
        draw.text((60, 1000), "do Seu Faturamento.", font=f_tit, fill=COLOR_MINT)

        # Botão de Ação com Gradiente + Pulso
        pulso = math.sin(p * math.pi * 4) * 0.03
        scale_btn = 1.0 + pulso
        bw = int(880 * scale_btn)
        bh = int(115 * scale_btn)
        bx = 540 - bw // 2
        by = 1110 + int((115 - bh) / 2)

        # Gradiente horizontal no botão (Cyan → Mint)
        desenhar_gradiente_horizontal(draw, (bx, by, bx + bw, by + bh), COLOR_CYAN, COLOR_MINT, radius=22)
        # Preencher cantos com retângulo arredondado semitransparente
        # Redesenhar o fundo do botão para cobrir as falhas do gradiente nos cantos
        # Solução: desenhar cartão com a cor média por baixo, depois o gradiente por cima
        # Na prática, o visual já funciona bem com as faixas + contorno

        txt_cta = ">> TOQUE NO LINK DA BIO: @TACTOSTUDIO <<"
        bbox_c = draw.textbbox((0, 0), txt_cta, font=f_btn)
        w_c = bbox_c[2] - bbox_c[0]
        draw.text((bx + (bw - w_c) // 2, by + 36), txt_cta, font=f_btn, fill=COLOR_BG)

        draw.text((180, 1290), "Solicite uma demonstracao ao vivo para o seu negocio", font=f_manifesto, fill=COLOR_GRAY)
        desenhar_texto_glow(draw, (280, 1335), "WhatsApp Direto com os Fundadores", f_manifesto, COLOR_CYAN, offset=1)

        desenhar_legenda_inferior(draw, cena_data["fala"])

        # Aplicar fade
        img = aplicar_fade(img, idx, total_frames)

        frame_path = os.path.join(pasta_saida, f"c4_frame_{idx:04d}.png")
        img.save(frame_path)
    return total_frames

# ==============================================================================
# MOTOR PRINCIPAL DE COMPILAÇÃO
# ==============================================================================
def renderizar_video_tacto_animado_completo(roteiro_cenas, nome_arquivo_saida="reels_tacto_animado_oficial.mp4", voz="pt-BR-AntonioNeural", progresso_callback=None):
    """
    Renderiza o vídeo animado completo (24 FPS por cena) com áudio neural sincronizado
    e compilação final via FFmpeg (H.264 High Profile, estéreo 44.1kHz).
    """
    pasta_temp = os.path.join(PASTA_OUTPUT, "temp_motion_render")
    os.makedirs(pasta_temp, exist_ok=True)

    segmentos_videos = []
    total = len(roteiro_cenas)

    for i, cena in enumerate(roteiro_cenas, 1):
        if progresso_callback:
            progresso_callback(i * 0.2, f"Gravando locucao neural da Cena {i}/{total}...")

        # 1. Sintetizar áudio da cena
        aud_cena = os.path.join(pasta_temp, f"audio_{i}.mp3")
        asyncio.run(sintetizar_audio_cena(cena["fala"], aud_cena, voz=voz))

        # 2. Medir duração
        dur = extrair_duracao_audio(aud_cena)
        dur_total = dur + 0.3

        if progresso_callback:
            progresso_callback(i * 0.22, f"Gerando frames animados da Cena {i}/{total} ({dur_total:.1f}s, {FPS}fps)...")

        # 3. Gerar frames animados específicos de cada cena
        n_cena = min(i, 4)
        renderizador = {1: renderizar_frames_cena1, 2: renderizar_frames_cena2, 3: renderizar_frames_cena3}.get(i, renderizar_frames_cena4)
        total_frames = renderizador(dur_total, pasta_temp, cena)
        pattern = os.path.join(pasta_temp, f"c{n_cena}_frame_%04d.png")

        # Miniatura da cena (60% da animação) para o storyboard da interface
        frame_ref = os.path.join(pasta_temp, f"c{n_cena}_frame_{int(total_frames * 0.6):04d}.png")
        if os.path.exists(frame_ref):
            shutil.copy(frame_ref, os.path.join(PASTA_STORYBOARD, f"cena_{i}.png"))

        # 4. Compilar clipe MP4 com ffmpeg (H.264 High Profile, estéreo 44.1kHz)
        seg_mp4 = os.path.join(pasta_temp, f"segmento_{i}.mp4")
        cmd_segmento = [
            FFMPEG_PATH,
            "-y",
            "-framerate", str(FPS),
            "-i", pattern,
            "-i", aud_cena,
            "-c:v", "libx264",
            "-profile:v", "high",
            "-level", "4.1",
            "-b:v", "8M",
            "-maxrate", "10M",
            "-bufsize", "20M",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-shortest",
            seg_mp4
        ]
        proc = subprocess.run(cmd_segmento, capture_output=True, text=True, errors="ignore")
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg falhou ao compilar a cena {i}: {proc.stderr[-400:]}")
        segmentos_videos.append(seg_mp4)

    # 5. Concatenar segmentos em arquivo final
    if progresso_callback:
        progresso_callback(0.95, "Concatenando video final em alta definicao...")

    concat_txt = os.path.join(pasta_temp, "concat_list.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for seg in segmentos_videos:
            seg_formatado = seg.replace("\\", "/")
            f.write(f"file '{seg_formatado}'\n")

    caminho_final = os.path.join(PASTA_OUTPUT, nome_arquivo_saida)
    cmd_concat = [
        FFMPEG_PATH,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt,
        "-c", "copy",
        caminho_final
    ]
    proc = subprocess.run(cmd_concat, capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falhou ao concatenar o vídeo final: {proc.stderr[-400:]}")

    shutil.rmtree(pasta_temp, ignore_errors=True)
    return caminho_final

# ==============================================================================
# ROTEIRO OFICIAL DE MARKETING
# ==============================================================================
ROTEIRO_PUBLICITARIO_TACTO = [
    {
        "tag": "ALERTA DE MARGEM",
        "titulo": "Voce ja calculou quanto perde no iFood todo mes?",
        "fala": "Se voce e dono de restaurante ou bar, pare tudo agora. Voce ja calculou quanto dinheiro deixa na mesa todo santo mes em comissoes de delivery?"
    },
    {
        "tag": "CANAL PROPRIO (CAC ZERO)",
        "titulo": "PWA de Velocidade Extrema e Pedidos Diretos",
        "fala": "Enquanto os marketplaces cobram quase trinta por cento e escondem os seus clientes, o PWA da TACTO Studio abre em menos de meio segundo e fecha pedidos direto no seu WhatsApp."
    },
    {
        "tag": "IA & DADOS EM TEMPO REAL",
        "titulo": "As 4 Tecnologias da TACTO Trabalhando Pelo Seu Negocio",
        "fala": "A TACTO Studio entrega uma esteira completa: PWA que abre em zero virgula tres segundos, atendente com inteligencia artificial, cardapio sensorial e dashboard de vendas."
    },
    {
        "tag": "PROXIMO PASSO",
        "titulo": "Assuma o Controle Total do Seu Faturamento",
        "fala": "Chega de queimar a sua margem de lucro com intermediarios. Clique agora no link da bio da TACTO Studio e agende uma demonstracao ao vivo para a sua operacao!"
    }
]

if __name__ == "__main__":
    print(f"Renderizando Reels ANIMADO oficial da TACTO Studio (1080x1920 9:16, {FPS}fps)...")
    vid = renderizar_video_tacto_animado_completo(ROTEIRO_PUBLICITARIO_TACTO, "reels_tacto_animado_oficial.mp4")
    print(f"Video animado renderizado com sucesso: {vid}")
