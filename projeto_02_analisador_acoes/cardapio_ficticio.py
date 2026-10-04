"""
Gera dois cardápios fictícios em PNG (duas semanas do mesmo bar) e o gabarito do que mudou entre eles.

Serve para testar a leitura por foto com uma chave de verdade sem precisar de cardápio de ninguém, e para
conferir o que a IA leu contra a verdade conhecida:

    python projeto_02_analisador_acoes/cardapio_ficticio.py
    GEMINI_API_KEY=... python projeto_02_analisador_acoes/adicionar_cardapio.py --so-ler cardapios_ficticios/semana_1.png --cliente x --alvo y

São imagens limpas, geradas por computador: um cardápio real, fotografado torto e com pouca luz, é bem mais difícil.
Acertar aqui é o piso, não a prova de que funciona no mundo.
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cardapio import preco_de

BASE = Path(__file__).resolve().parent
PASTA = BASE / "cardapios_ficticios"
LARGURA, ALTURA = 1240, 1754            # A4 em 150 dpi
FONTES = ["C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/arialbd.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf", "arialbd.ttf"]

SEMANA_1 = [
    ("Entradas", "Bolinho de bacalhau (6 un.)", "R$ 38,00"),
    ("Entradas", "Pastel de queijo coalho", "R$ 29,90"),
    ("Entradas", "Porção de batata rústica", "R$ 34,00"),
    ("Lanches", "X-Salada da casa", "R$ 42,00"),
    ("Lanches", "Burger Artesanal 180g", "R$ 48,90"),
    ("Lanches", "Burger Artesanal 250g", "R$ 58,90"),
    ("Lanches", "Sanduíche de pernil", "R$ 39,00"),
    ("Pratos", "Filé à parmegiana", "R$ 89,00"),
    ("Pratos", "Picanha na chapa (2 pessoas)", "R$ 148,00"),
    ("Pratos", "Risoto de camarão", "R$ 76,50"),
    ("Bebidas", "Chope Pilsen 300ml", "R$ 12,00"),
    ("Bebidas", "Refrigerante lata", "R$ 8,00"),
    ("Bebidas", "Suco natural", "R$ 14,00"),
    ("Sobremesas", "Pudim da casa", "R$ 18,00"),
    ("Sobremesas", "Petit gateau", "sob consulta"),
]

# O que muda na semana 2: aumento, queda, item que sai e item que entra.
MUDANCAS = {
    "Bolinho de bacalhau (6 un.)": "R$ 42,00",       # +10,5%
    "Burger Artesanal 180g": "R$ 52,90",             # +8,2%
    "Filé à parmegiana": "R$ 98,00",                 # +10,1%
    "Chope Pilsen 300ml": "R$ 13,50",                # +12,5%
    "Refrigerante lata": "R$ 7,00",                  # -12,5%
    "Petit gateau": "R$ 26,00",                      # sai de "sob consulta": não é alta, é preço que faltava
}
REMOVIDOS = ["Risoto de camarão"]
NOVOS = [("Pratos", "Ravioli de cordeiro", "R$ 84,00"), ("Sobremesas", "Cheesecake de frutas", "R$ 24,00")]


def fonte(tamanho):
    for caminho in FONTES:
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(size=tamanho)


def semana_2():
    itens = [(c, n, MUDANCAS.get(n, p)) for c, n, p in SEMANA_1 if n not in REMOVIDOS]
    for categoria, nome, preco in NOVOS:                       # entra logo após o último item da mesma categoria
        posicao = max(i for i, (c, _, _) in enumerate(itens) if c == categoria) + 1
        itens.insert(posicao, (categoria, nome, preco))
    return itens


def desenhar(itens, caminho: Path, subtitulo: str) -> Path:
    img = Image.new("RGB", (LARGURA, ALTURA), (252, 250, 245))
    draw = ImageDraw.Draw(img)
    f_titulo, f_sub, f_cat, f_item, f_preco = fonte(58), fonte(24), fonte(34), fonte(28), fonte(28)

    draw.text((LARGURA // 2, 110), "BAR DO ZÉ", font=f_titulo, fill=(40, 30, 25), anchor="mm")
    draw.text((LARGURA // 2, 165), subtitulo, font=f_sub, fill=(120, 105, 95), anchor="mm")
    draw.line([(160, 205), (LARGURA - 160, 205)], fill=(180, 160, 140), width=3)

    y, categoria_atual = 265, None
    for categoria, nome, preco in itens:
        if categoria != categoria_atual:
            categoria_atual = categoria
            y += 30
            draw.text((140, y), categoria.upper(), font=f_cat, fill=(150, 90, 40))
            y += 58
        largura_preco = draw.textlength(preco, font=f_preco)
        draw.text((160, y), nome, font=f_item, fill=(45, 40, 38))
        draw.text((LARGURA - 160 - largura_preco, y), preco, font=f_preco, fill=(45, 40, 38))
        inicio = 160 + draw.textlength(nome, font=f_item) + 14
        draw.line([(inicio, y + 22), (LARGURA - 174 - largura_preco, y + 22)], fill=(205, 195, 185), width=2)
        y += 52

    draw.text((LARGURA // 2, ALTURA - 90), "Estabelecimento fictício, criado para testar a leitura de cardápios.",
              font=f_sub, fill=(160, 150, 140), anchor="mm")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    img.save(caminho)
    return caminho


def gabarito(itens_1, itens_2) -> dict:
    """
    A verdade conhecida das duas semanas, para comparar com o que a IA leu. As mudanças são DERIVADAS dos
    preços, não escritas à mão: na primeira versão eu classifiquei uma queda como alta, e só a conferência pegou.
    """
    precos_1 = {n: p for _, n, p in itens_1}
    esperadas = {"subiram": [], "baixaram": [], "sem_comparacao": [],
                 "novos": [n for _, n, _ in NOVOS], "sumiram": list(REMOVIDOS)}
    for _, nome, preco in itens_2:
        if nome not in precos_1:
            continue
        antes, depois = preco_de(precos_1[nome]), preco_de(preco)
        if antes is None or depois is None:
            esperadas["sem_comparacao"].append(nome)
        elif depois > antes:
            esperadas["subiram"].append(nome)
        elif depois < antes:
            esperadas["baixaram"].append(nome)
    for chave in esperadas:
        esperadas[chave].sort()
    return {
        "semana_1": [{"categoria": c, "nome": n, "preco_texto": p} for c, n, p in itens_1],
        "semana_2": [{"categoria": c, "nome": n, "preco_texto": p} for c, n, p in itens_2],
        "mudancas_esperadas": esperadas,
    }


def main() -> int:
    itens_2 = semana_2()
    um = desenhar(SEMANA_1, PASTA / "semana_1.png", "Cardápio - semana de 8 a 14 de setembro")
    dois = desenhar(itens_2, PASTA / "semana_2.png", "Cardápio - semana de 15 a 21 de setembro")
    verdade = PASTA / "gabarito.json"
    conteudo = gabarito(SEMANA_1, itens_2)
    verdade.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    esperadas = conteudo["mudancas_esperadas"]
    print(f"{um}\n{dois}\n{verdade}")
    print(f"\nSemana 1: {len(SEMANA_1)} itens | semana 2: {len(itens_2)} itens")
    print(f"Esperado entre as duas: {len(esperadas['subiram'])} altas, {len(esperadas['baixaram'])} queda(s), "
          f"{len(esperadas['novos'])} novos, {len(esperadas['sumiram'])} removido(s), "
          f"{len(esperadas['sem_comparacao'])} sem comparação (preço ilegível numa das semanas)")
    return 0


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
