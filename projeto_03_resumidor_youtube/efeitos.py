"""
Direção de arte do vídeo: cor, textura, zoom e transição — o que o CapCut chama de filtros e efeitos.

Tudo aqui é filtro do ffmpeg montado como texto (funções puras, testadas sem rodar nada). Nada é desenhado
quadro a quadro em Python: um filtro de cor custa quase nada a mais na renderização que já acontece.

Os valores dos filtros foram escolhidos olhando uma folha de contato com o mesmo quadro em cada um, em dois
vídeos reais (anime claro e anime escuro). "Cinema" e "Dramático" pesam em cena já escura; por isso nenhum
filtro vem ligado por padrão.

Custo medido (12 s de um clipe 1080p a 50 quadros/s; só o vídeo, sem nada aplicado, leva 3,7 s):
- granulação (`noise`) somava 33 a 41 s — triplicava a montagem. Ficou de fora.
- "Cinema" com `colorbalance` no vídeo de origem somava 11 s. Trocado por curvas por canal (uma tabela, não
  uma conta por pixel), aplicadas DEPOIS de reduzir o vídeo: a frente tem 1080x607, um terço dos pixels do
  original, e o fundo desfocado 270x480.
- vinheta com o filtro `vignette` somava 5 s; virou um PNG desenhado uma vez e sobreposto, como a moldura.
- o vídeo passa à taxa da saída (24 quadros/s) no começo do filtro, e não só na saída: com fonte a 50, cada
  filtro processava mais da metade de quadros que iam ser jogados fora.

O que ficou de fora, e por quê:
- zoom lento contínuo (Ken Burns): o `zoompan` do ffmpeg treme, porque arredonda a posição para o pixel
  inteiro a cada quadro; o `scale` com expressão por quadro desliza para um lado, porque o `crop` seguinte
  calcula o centro uma vez só. Os dois foram testados. Sobrou o zoom de ênfase, que muda de uma vez — e é
  o que os editores de vídeo curto usam nas trocas de frase.
- granulação (custo, acima) e música.

Tremida, câmera lenta, quadro de impacto, flash e separação RGB entraram depois, com as receitas por
situação (abaixo): em vez de um ritmo fixo, eles caem nos golpes que momentos.py acha no próprio clipe.
"""
from dataclasses import dataclass

# Nome na tela e o filtro. "original" é o padrão: sem filtro nenhum.
LOOKS = {
    "original": ("Original", ""),
    "vivido": ("Vívido", "eq=contrast=1.06:saturation=1.35"),
    "neon": ("Neon (cores saturadas)", "eq=contrast=1.12:saturation=1.6:gamma=0.95"),
    # sombra puxada para o azul, luz para o laranja
    "cinema": ("Cinema (azul e laranja)",
               "curves=r='0/0 0.25/0.21 0.75/0.80 1/1':b='0/0 0.25/0.30 0.75/0.70 1/1',eq=contrast=1.10"),
    "quente": ("Quente", "curves=r='0/0 0.5/0.56 1/1':b='0/0 0.5/0.44 1/1',eq=saturation=1.1"),
    "frio": ("Frio", "curves=r='0/0 0.5/0.45 1/1':b='0/0 0.5/0.57 1/1'"),
    "dramatico": ("Dramático", "eq=contrast=1.25:brightness=-0.03:saturation=0.85"),
    "vintage": ("Vintage", "curves=preset=vintage,eq=saturation=0.9"),
    "pb": ("Preto e branco", "hue=s=0,eq=contrast=1.15"),
    # das receitas: aura (escuro, contraste alto, puxado para o vermelho) e emoção (lavado, frio, preto aberto)
    "sombrio": ("Sombrio (vermelho)", "eq=contrast=1.28:brightness=-0.05:saturation=0.75,"
                                      "curves=r='0/0 0.5/0.56 1/1':g='0/0 0.5/0.45 1/1':b='0/0 0.5/0.45 1/1'"),
    "melancolico": ("Melancólico (frio e lavado)", "eq=saturation=0.55:contrast=0.92:brightness=0.02,"
                                                   "curves=r='0/0.05 0.5/0.47 1/0.95':b='0/0.10 0.5/0.56 1/1'"),
}

# Zoom de ênfase: a imagem "pula" para mais perto numa troca de frase e volta na seguinte.
ZOOMS = {"nenhum": ("Sem zoom", 1.0), "sutil": ("Zoom sutil nas trocas de frase", 1.08),
         "forte": ("Zoom forte nas trocas de frase", 1.18)}
A_CADA_SEM_LEGENDA = 3.0       # sem legenda para saber onde a frase troca, o zoom alterna nesse ritmo

# Transições do xfade do ffmpeg entre os trechos da edição.
TRANSICOES = {"corte": "Corte seco", "fade": "Esmaecer", "fadewhite": "Flash branco", "fadeblack": "Piscar no preto",
              "slideleft": "Deslizar", "zoomin": "Zoom para dentro", "circleopen": "Abrir em círculo",
              "hblur": "Desfoque"}
DURACAO_TRANSICAO = 0.35       # curta: transição longa em vídeo de 60 s parece apresentação de slides
TRECHO_MINIMO_PARA_TRANSICAO = 1.0


@dataclass(frozen=True)
class DirecaoDeArte:
    look: str = "original"
    vinheta: bool = False
    zoom: str = "nenhum"
    transicao: str = "corte"
    # --- efeitos que caem nos golpes (momentos.py acha onde) ---
    golpes_por_minuto: int = 0          # 0 = não procura golpe nenhum
    quadro_de_impacto: str = ""         # "", "negativo", "vermelho" ou "manga"
    flash: bool = False
    tremida: int = 0                    # amplitude em pixels; 0 = sem tremida
    separacao_rgb: bool = False
    zoom_no_golpe: float = 1.0          # aproximação no instante do golpe (1.0 = nenhuma)
    duracao_do_golpe: float = 0.35      # quanto tempo tremida, zoom e separação RGB duram depois do golpe
    camera_lenta: bool = False          # o golpe mais forte em meia velocidade
    speed_ramping: bool = False         # velocity multi-golpe: acelera antes (1,5x) e freia no impacto (0,5x)
    rastro_movimento: bool = False      # motion blur (tblend) nos golpes e curvas rápidas
    glitch: bool = False                # falha digital / deslocamento cromático intenso nos golpes
    # --- acabamento ---
    brilho: bool = False                # bloom: as luzes ganham halo
    cinemascope: bool = False           # o vídeo vira faixa 2,39:1 (só no enquadramento inteiro)
    estilo_legenda: str = ""            # o estilo que a receita sugere para a legenda
    receita: str = "personalizada"

    @property
    def fator_zoom(self) -> float:
        return ZOOMS.get(self.zoom, ZOOMS["nenhum"])[1]

    @property
    def usa_golpes(self) -> bool:
        return self.golpes_por_minuto > 0 and (
            bool(self.quadro_de_impacto) or self.flash or self.tremida > 0
            or self.separacao_rgb or self.zoom_no_golpe > 1.0 or self.camera_lenta
            or self.speed_ramping or self.rastro_movimento or self.glitch
        )


SEM_ARTE = DirecaoDeArte()


# ==============================================================================
# RECEITAS POR SITUAÇÃO
# ==============================================================================
# Cada receita é o que um editor faria naquele tipo de cena, montado com as peças acima. Referências (setembro
# de 2026): guias de ritmo de vídeo curto (TikTok com troca a cada 1,5-3 s, Reels 2,5-4 s, gancho nos 3
# primeiros segundos), tutoriais de edição de anime no CapCut (velocity, flash, shake, separação RGB, borrão
# de movimento) e o glossário de sakuga sobre "impact frames" — o quadro invertido ou monocromático de uma
# fração de segundo que o próprio anime usa no auge do golpe. Os números (golpes por minuto, amplitude,
# duração) foram acertados olhando o resultado nos clipes reais, não tirados das referências.
RECEITAS = {
    "luta": ("Luta", "Golpe marcado: quadro invertido no impacto, flash branco, tremida com separação RGB e "
             "aproximação; o golpe mais forte em câmera lenta. Legenda de impacto, transição com flash.",
             DirecaoDeArte(look="vivido", golpes_por_minuto=18, quadro_de_impacto="negativo", flash=True, tremida=26,
                           separacao_rgb=True, zoom_no_golpe=1.10, camera_lenta=True, transicao="fadewhite",
                           estilo_legenda="impacto", receita="luta")),
    "aura": ("Aura / entrada de personagem", "Peso em vez de pressa: imagem escura puxada para o vermelho, halo "
             "nas luzes, faixa de cinema e vinheta, poucos golpes com quadro vermelho e tremida curta, câmera "
             "lenta no mais forte, zoom sutil nas falas.",
             DirecaoDeArte(look="sombrio", vinheta=True, zoom="sutil", golpes_por_minuto=5, quadro_de_impacto="vermelho",
                           tremida=16, zoom_no_golpe=1.08, camera_lenta=True, brilho=True, cinemascope=True,
                           transicao="fadeblack", estilo_legenda="impacto", receita="aura")),
    "emocao": ("Emoção / despedida", "Nada que distraia: cor lavada e fria, halo suave, faixa de cinema e "
               "vinheta; sem golpe, sem tremida, sem zoom. Legenda clássica, transição esmaecendo.",
               DirecaoDeArte(look="melancolico", vinheta=True, brilho=True, cinemascope=True, transicao="fade",
                             estilo_legenda="classica", receita="emocao")),
    "comedia": ("Comédia / reação", "O zoom na cara de quem reage: aproximação forte e rápida nos picos de som, "
                "tremida leve, cores saturadas. Legenda de impacto, transição com zoom.",
                DirecaoDeArte(look="neon", golpes_por_minuto=10, tremida=8, zoom_no_golpe=1.22, duracao_do_golpe=0.8,
                              transicao="zoomin", estilo_legenda="impacto", receita="comedia")),
    "dialogo": ("Diálogo / fala marcante", "A fala é o conteúdo: cor viva, zoom sutil a cada frase, a palavra "
                "dita em destaque na legenda. Sem efeito de golpe.",
                DirecaoDeArte(look="vivido", zoom="sutil", estilo_legenda="destaque", receita="dialogo")),
}


def receita(nome: str) -> DirecaoDeArte:
    return RECEITAS[nome][2] if nome in RECEITAS else SEM_ARTE


# ==============================================================================
# EFEITOS NOS GOLPES
# ==============================================================================
QUADRO = 1 / 24                     # um quadro na taxa de saída
QUADROS_DE_IMPACTO = 2              # o impact frame do anime dura um ou dois quadros
VERMELHO = "colorchannelmixer=rr=0.55:rg=0.55:rb=0.2:gr=0.05:gg=0.08:gb=0.02:br=0.05:bg=0.08:bb=0.02"
MANGA_PB = "eq=saturation=0:contrast=3.0:brightness=0.05"
# Flash em três degraus (0,45 -> 0,25 -> 0,1): cada degrau é um `eq` fixo, ligado só nos seus quadros. Uma
# expressão por quadro (eval=frame) faria o mesmo desbotar contínuo, mas recalculava a tabela do eq em todo
# quadro do vídeo, e somou 3,7 s em 12 s de clipe na medição.
DEGRAUS_DO_FLASH = ((0.45, 1), (0.25, 2), (0.10, 2))


def _quando(janelas) -> str:
    return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in janelas)


def filtro_rgb(golpes_escolhidos, arte: DirecaoDeArte) -> str:
    """Separação RGB enquanto treme. Desloca os canais 14 px — e cria uma borda colorida na beira do quadro."""
    if not golpes_escolhidos or not arte.separacao_rgb:
        return ""
    janelas = ((g["t"], g["t"] + arte.duracao_do_golpe * 0.7) for g in golpes_escolhidos)
    return f"rgbashift=rh=-14:bh=14:enable='{_quando(janelas)}'"


def filtros_dos_golpes(golpes_escolhidos, arte: DirecaoDeArte, com_rgb: bool = True) -> str:
    """
    Cadeia de filtros para o quadro 9:16 montado: quadro de impacto no golpe, flash logo depois, separação
    RGB enquanto treme, rastro de movimento (motion blur) e glitch digital. Cada filtro só trabalha nos
    quadros em que está ligado (`enable`); fora deles, o ffmpeg passa o quadro adiante sem mexer.
    """
    if not golpes_escolhidos:
        return ""
    tempos = [g["t"] for g in golpes_escolhidos]
    partes = []
    impacto = QUADROS_DE_IMPACTO * QUADRO if arte.quadro_de_impacto else 0.0
    if arte.quadro_de_impacto:
        if arte.quadro_de_impacto == "negativo":
            filtro = "negate"
        elif arte.quadro_de_impacto == "manga":
            filtro = MANGA_PB
        else:
            filtro = VERMELHO
        partes.append(f"{filtro}:enable='{_quando((t, t + impacto) for t in tempos)}'" if "=" in filtro
                      else f"{filtro}=enable='{_quando((t, t + impacto) for t in tempos)}'")
    if arte.flash:
        inicio = impacto
        for brilho, quadros in DEGRAUS_DO_FLASH:
            fim = inicio + quadros * QUADRO
            partes.append(f"eq=brightness={brilho}:enable='{_quando((t + inicio, t + fim) for t in tempos)}'")
            inicio = fim
    if com_rgb and arte.separacao_rgb:
        partes.append(filtro_rgb(golpes_escolhidos, arte))
    if arte.glitch:
        janelas_glitch = ((t, t + arte.duracao_do_golpe * 0.55) for t in tempos)
        partes.append(f"rgbashift=rh=22:bh=-22:rv=10:bv=-10:edge=wrap:enable='{_quando(janelas_glitch)}'")
    if arte.rastro_movimento:
        janelas_blur = ((t, t + arte.duracao_do_golpe) for t in tempos)
        partes.append(f"tblend=all_mode=average:enable='{_quando(janelas_blur)}'")
    return ",".join(partes)


def janelas_dos_golpes(golpes_escolhidos, arte: DirecaoDeArte, duracao: float) -> list:
    """Intervalos em que o quadro treme e/ou aproxima, um por golpe."""
    if not golpes_escolhidos or (arte.tremida <= 0 and arte.zoom_no_golpe <= 1.0):
        return []
    return [(round(g["t"], 3), round(min(duracao, g["t"] + arte.duracao_do_golpe), 3)) for g in golpes_escolhidos]


def expressao_da_tremida(janelas, amplitude: int, eixo: str) -> str:
    """
    Deslocamento em pixels que decai até zero no fim de cada janela: forte no impacto, parando em seguida.
    Frequências diferentes em x e y, para não virar um vaivém numa linha só.
    """
    if not janelas or amplitude <= 0:
        return "0"
    onda = "sin(2*PI*13*t)" if eixo == "x" else "cos(2*PI*9*t)"
    decaimento = "+".join(f"between(t,{a:.3f},{b:.3f})*(1-(t-{a:.3f})/{max(0.01, b - a):.3f})" for a, b in janelas)
    return f"{amplitude}*{onda}*({decaimento})"


# ==============================================================================
# CÂMERA LENTA E SPEED RAMPING (o "velocity" dos editores de anime)
# ==============================================================================
FATOR_LENTO = 0.5                   # metade da velocidade
FATOR_RAPIDO = 1.5                  # aceleração antes do impacto no speed ramping
ANTES_DO_GOLPE, DEPOIS_DO_GOLPE = 0.5, 0.7
ANTES_VELOCITY, DEPOIS_VELOCITY = 0.35, 0.45


def trecho_lento(golpes_escolhidos, duracao: float) -> tuple | None:
    """O intervalo em volta do golpe mais forte; None se não couber inteiro no clipe."""
    if not golpes_escolhidos:
        return None
    t = max(golpes_escolhidos, key=lambda g: g["forca"])["t"]
    a, b = max(0.0, t - ANTES_DO_GOLPE), min(float(duracao), t + DEPOIS_DO_GOLPE)
    return (round(a, 3), round(b, 3)) if b - a >= 0.6 else None


def trechos_velocity(golpes_escolhidos, duracao: float, max_golpes: int = 3) -> list | None:
    """
    Speed Ramping multi-golpe: nos golpes mais fortes (até `max_golpes`), acelera na preparação (1,5x por
    0,35 s antes do impacto) e freia brusco em câmera lenta no impacto (0,5x por 0,45 s depois).
    Devolve lista ordenada de segmentos `[(ini, fim, fator), ...]` sem sobreposição, ou None.
    """
    if not golpes_escolhidos or duracao < 1.0:
        return None
    candidatos = sorted(golpes_escolhidos, key=lambda g: g["forca"], reverse=True)[:max_golpes]
    candidatos.sort(key=lambda g: g["t"])
    segmentos = []
    cursor = 0.0
    for g in candidatos:
        t = float(g["t"])
        ini_rapido = round(max(cursor, t - ANTES_VELOCITY), 3)
        fim_rapido = round(min(float(duracao), t), 3)
        ini_lento = fim_rapido
        fim_lento = round(min(float(duracao), t + DEPOIS_VELOCITY), 3)
        if fim_lento - ini_rapido < 0.4:
            continue
        if fim_rapido - ini_rapido >= 0.12:
            segmentos.append((ini_rapido, fim_rapido, FATOR_RAPIDO))
        if fim_lento - ini_lento >= 0.15:
            segmentos.append((ini_lento, fim_lento, FATOR_LENTO))
        cursor = fim_lento + 0.05
    return segmentos or None


def _normalizar_segmentos(lento, fator: float = FATOR_LENTO) -> list:
    """Aceita tanto o par legado `(a, b)` quanto uma lista de segmentos `[(ini, fim, f), ...]`."""
    if not lento:
        return []
    if isinstance(lento, tuple) and len(lento) == 2 and isinstance(lento[0], (int, float)):
        return [(float(lento[0]), float(lento[1]), float(fator))]
    return [(float(ini), float(fim), float(f)) for ini, fim, f in lento]


def remapear(t: float, lento, fator: float = FATOR_LENTO) -> float:
    """Onde o instante `t` do clipe original cai depois de o(s) trecho(s) de velocidade serem aplicados."""
    segmentos = _normalizar_segmentos(lento, fator)
    if not segmentos:
        return t
    deslocamento = 0.0
    for a, b, f in segmentos:
        if t <= a:
            break
        if t <= b:
            return a + deslocamento + (t - a) / f
        deslocamento += (b - a) * (1.0 / f - 1.0)
    return t + deslocamento


def remapear_legendas(legendas, lento, fator: float = FATOR_LENTO) -> list:
    if not lento:
        return list(legendas)
    saida = []
    for bloco in legendas:
        novo = {**bloco, "inicio": remapear(bloco["inicio"], lento, fator), "fim": remapear(bloco["fim"], lento, fator)}
        if bloco.get("palavras"):
            novo["palavras"] = [{**p, "inicio": remapear(p["inicio"], lento, fator),
                                 "fim": remapear(p["fim"], lento, fator)} for p in bloco["palavras"]]
        saida.append(novo)
    return saida


def filtro_de_velocidade(lento, duracao: float, tem_audio: bool, fator: float = FATOR_LENTO) -> str:
    """
    Parte o clipe nos trechos normais e com velocidade alterada (câmera lenta ou speed ramping) e emenda de
    novo. Sai [vel_v] e, havendo som, [vel_a]. O som passa por `atempo`, que altera a velocidade sem mudar o tom.
    """
    segmentos = _normalizar_segmentos(lento, fator)
    pedacos = []
    cursor = 0.0
    for ini, fim, f in segmentos:
        if ini - cursor > 0.01:
            pedacos.append((cursor, ini, 1.0))
        if fim - ini > 0.01:
            pedacos.append((ini, fim, f))
        cursor = fim
    if float(duracao) - cursor > 0.01:
        pedacos.append((cursor, float(duracao), 1.0))
    n = len(pedacos)
    partes = [f"[0:v]split={n}" + "".join(f"[vp{i}]" for i in range(n))]
    for i, (ini, fim, f) in enumerate(pedacos):
        esticar = f"{1 / f:g}*" if f != 1.0 else ""
        partes.append(f"[vp{i}]trim={ini:.3f}:{fim:.3f},setpts={esticar}(PTS-STARTPTS)[vs{i}]")
    if tem_audio:
        partes.append("[0:a]asplit=" + f"{n}" + "".join(f"[ap{i}]" for i in range(n)))
        for i, (ini, fim, f) in enumerate(pedacos):
            tempo = f",atempo={f:g}" if f != 1.0 else ""
            partes.append(f"[ap{i}]atrim={ini:.3f}:{fim:.3f},asetpts=PTS-STARTPTS{tempo}[as{i}]")
        entradas = "".join(f"[vs{i}][as{i}]" for i in range(n))
        partes.append(f"{entradas}concat=n={n}:v=1:a=1[vel_v][vel_a]")
    else:
        partes.append("".join(f"[vs{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vel_v]")
    return ";".join(partes)



def filtro_de_cor(arte: DirecaoDeArte) -> str:
    """Correção de cor. Vai na frente e no fundo desfocado, cada um já no tamanho reduzido."""
    return LOOKS.get(arte.look, LOOKS["original"])[1]


def janelas_de_zoom(legendas, duracao: float, a_cada: float = A_CADA_SEM_LEGENDA) -> list:
    """
    Intervalos em que a imagem fica ampliada: um bloco de legenda sim, outro não — a troca acontece junto
    com a troca de frase, que é onde o olho já espera mudança. Cada janela vai do início de um bloco até o
    início do seguinte, para o zoom não mudar no meio de uma palavra.
    """
    duracao = float(duracao)
    if legendas:
        inicios = [float(b["inicio"]) for b in legendas]
        limites = inicios[1:] + [duracao]
        return [(round(a, 2), round(min(b, duracao), 2)) for i, (a, b) in enumerate(zip(inicios, limites))
                if i % 2 == 1 and b > a]
    janelas, t, ligado = [], 0.0, False
    while t < duracao:
        fim = min(duracao, t + a_cada)
        if ligado:
            janelas.append((round(t, 2), round(fim, 2)))
        t, ligado = fim, not ligado
    return janelas


def filtro_de_zoom(entrada: str, saida: str, janelas, fator: float, largura: int, altura: int,
                   tremidas=(), amplitude: int = 0, antes_do_recorte: str = "") -> list:
    """
    Partes do filtergraph que ampliam `entrada` pelo centro nas janelas dadas. A versão ampliada é feita uma
    vez e posta por cima só quando a janela está ligada — é o jeito de ter corte seco de zoom sem o tremor
    do zoompan.

    A tremida anda no mesmo ramo: a janela do recorte se desloca de um lado para o outro dentro da imagem
    ampliada, então nunca aparece borda preta. Para caber, a ampliação é no mínimo a que dá folga para a
    amplitude pedida.

    `antes_do_recorte` é um filtro aplicado na imagem ampliada antes de recortar — a separação RGB vai aqui:
    a borda colorida que ela cria na beira do quadro fica fora do recorte. Aplicada no quadro final, ela
    deixava um fio azul na borda direita.
    """
    tremidas = list(tremidas) if amplitude > 0 else []
    janelas = list(dict.fromkeys(list(janelas or []) + tremidas))      # sem repetir a mesma janela
    if tremidas:
        fator = max(fator, 1 + 2.4 * amplitude / largura)
    if fator <= 1.0 or not janelas:
        return [f"[{entrada}]null[{saida}]"]
    quando = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in janelas)
    x = f"(iw-iw/{fator:g})/2"
    y = f"(ih-ih/{fator:g})/2"
    if tremidas:
        x = f"'{x}+{expressao_da_tremida(tremidas, amplitude, 'x')}'"
        y = f"'{y}+{expressao_da_tremida(tremidas, amplitude, 'y')}'"
    return [
        f"[{entrada}]split=2[{saida}_base][{saida}_perto]",
        f"[{saida}_perto]{antes_do_recorte + ',' if antes_do_recorte else ''}crop=iw/{fator:g}:ih/{fator:g}:{x}:{y},"
        f"scale={largura}:{altura}:flags=lanczos[{saida}_ampliado]",
        f"[{saida}_base][{saida}_ampliado]overlay=0:0:enable='{quando}'[{saida}]",
    ]


def usa_transicao(arte: DirecaoDeArte, duracoes) -> bool:
    """Transição só com mais de um trecho, e com todos longos o bastante para ceder o tempo da passagem."""
    return (arte.transicao in TRANSICOES and arte.transicao != "corte" and len(duracoes) > 1
            and min(duracoes) > max(TRECHO_MINIMO_PARA_TRANSICAO, 2 * DURACAO_TRANSICAO))


def inicios_com_transicao(duracoes, d: float = DURACAO_TRANSICAO) -> list:
    """Onde cada trecho começa no vídeo final: cada transição sobrepõe `d` segundos do trecho anterior."""
    inicios, t = [], 0.0
    for duracao in duracoes:
        inicios.append(round(t, 3))
        t += duracao - d
    return inicios


def filtro_de_transicoes(duracoes, transicao: str, d: float = DURACAO_TRANSICAO, fps: int = 24) -> str:
    """
    Emenda os trechos (entradas 0..n-1, todas com áudio) com xfade no vídeo e acrossfade no som. O `offset`
    de cada xfade é o início do trecho seguinte no vídeo final, menos nada: é quando a passagem começa.
    """
    # o xfade exige a mesma base de tempo e a mesma taxa nas duas entradas
    partes = [f"[{i}:v]settb=AVTB,fps={fps},format=yuv420p[v{i}]" for i in range(len(duracoes))]
    inicios = inicios_com_transicao(duracoes, d)
    anterior_v, anterior_a = "v0", "0:a"
    for i in range(1, len(duracoes)):
        offset = inicios[i]
        saida_v, saida_a = f"x{i}", f"a{i}"
        partes.append(f"[{anterior_v}][v{i}]xfade=transition={transicao}:duration={d:.3f}:offset={offset:.3f}[{saida_v}]")
        partes.append(f"[{anterior_a}][{i}:a]acrossfade=d={d:.3f}[{saida_a}]")
        anterior_v, anterior_a = saida_v, saida_a
    partes.append(f"[{anterior_v}]null[vfinal]")
    partes.append(f"[{anterior_a}]anull[afinal]")
    return ";".join(partes)
