"""Temas visuais dos vídeos gerados. A TACTO Studio é só mais um (kit de marca com logo), não o único."""
from dataclasses import dataclass

Cor = tuple[int, int, int]


@dataclass(frozen=True)
class Tema:
    nome: str
    fundo: Cor
    superficie: Cor
    borda: Cor
    destaque: Cor
    destaque2: Cor
    texto: Cor
    texto_suave: Cor
    alerta: Cor
    marca: str = ""              # texto do canto do cabeçalho (o usuário pode trocar na tela)
    logo: str | None = None      # arquivo dentro de assets_tacto/, usado no lugar do texto da marca


def misturar(a: Cor, b: Cor, t: float) -> Cor:
    t = min(1.0, max(0.0, t))
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def luminancia(cor: Cor) -> float:
    """Luminância relativa (0 preto, 1 branco), para escolher texto legível sobre uma cor."""
    def canal(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(c) for c in cor)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def cor_sobre(cor: Cor) -> Cor:
    """Texto escuro sobre cor clara e branco sobre cor escura."""
    return (13, 17, 23) if luminancia(cor) > 0.35 else (255, 255, 255)


PRESETS: dict[str, Tema] = {t.nome: t for t in (
    Tema("Escuro: ciano e menta", fundo=(13, 17, 23), superficie=(22, 27, 34), borda=(48, 54, 61), destaque=(0, 240, 255),
         destaque2=(16, 249, 132), texto=(240, 246, 252), texto_suave=(139, 148, 158), alerta=(234, 29, 44)),
    Tema("Claro: azul e laranja", fundo=(247, 248, 250), superficie=(255, 255, 255), borda=(214, 219, 226), destaque=(37, 99, 235),
         destaque2=(234, 110, 0), texto=(17, 24, 39), texto_suave=(95, 106, 122), alerta=(214, 40, 40)),
    Tema("Quente: laranja e coral", fundo=(28, 16, 18), superficie=(44, 27, 30), borda=(78, 50, 54), destaque=(255, 153, 51),
         destaque2=(255, 99, 110), texto=(255, 244, 235), texto_suave=(184, 158, 152), alerta=(255, 84, 84)),
    Tema("Natureza: verde e areia", fundo=(17, 28, 22), superficie=(26, 42, 33), borda=(48, 72, 57), destaque=(110, 231, 120),
         destaque2=(240, 200, 110), texto=(238, 247, 238), texto_suave=(150, 173, 155), alerta=(240, 110, 90)),
    Tema("TACTO Studio (marca oficial)", fundo=(13, 17, 23), superficie=(22, 27, 34), borda=(48, 54, 61), destaque=(0, 240, 255),
         destaque2=(16, 249, 132), texto=(240, 246, 252), texto_suave=(139, 148, 158), alerta=(234, 29, 44),
         marca="TACTO STUDIO", logo="logo_tacto.png"),
    Tema("@corte.otakubr (Tokyo Archive)", fundo=(10, 10, 12), superficie=(18, 18, 23), borda=(34, 34, 43),
         destaque=(255, 42, 58), destaque2=(255, 230, 0), texto=(245, 245, 240), texto_suave=(142, 142, 152),
         alerta=(255, 42, 58), marca="@corte.otakubr // ARCHIVE"),
)}
TEMA_PADRAO = "Escuro: ciano e menta"
