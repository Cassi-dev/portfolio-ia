"""
Uma regra sem IA que pegue "notícia de outra região" pagaria a pena?

Nos 80 rótulos, 9 descartes foram "regional_irrelevante". A regra: se o título nomeia um lugar brasileiro,
é candidato a ruído. A medida é quantos dos 9 ela pega e quantos itens ÚTEIS derruba junto (o erro caro).

Resultado: 6 dos 9, ao custo de 5 dos 33 úteis — e os 5 são os melhores itens do Radar ("Outback chega ao
Shopping Uberaba", "Papa Johns estreia em São Paulo"). Não adotado; ver o README desta pasta.
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "projeto_02_analisador_acoes"))
ROTULOS = RAIZ / "projeto_02_analisador_acoes/dados_medicao/rotulos_80_manchetes.json"

from deteccao import normalizar  # noqa: E402

# Lista escrita à mão, não partida por espaço: na primeira versão eu usei .split(), e "rio de janeiro" virou
# as palavras soltas "de" e "do", enquanto "Pará" virou a preposição "para". A regra marcava 23 dos 33 úteis.
# Fora também os nomes ambíguos sozinhos ("rio", "santos", "natal", "vitoria", "palmas", "belem").
LUGARES = [
    "acre", "alagoas", "amapa", "amazonas", "bahia", "baiano", "baiana", "baianos", "ceara", "cearense",
    "distrito federal", "espirito santo", "goias", "maranhao", "mato grosso", "minas gerais", "mineiro",
    "paraiba", "parana", "paranaense", "pernambuco", "piaui", "rio de janeiro", "do rio", "no rio",
    "rio grande do norte", "rio grande do sul", "gaucho", "gaucha", "gauchos", "rondonia", "roraima",
    "santa catarina", "catarinense", "sao paulo", "paulista", "paulistano", "sergipe", "tocantins",
    "recife", "salvador", "fortaleza", "manaus", "curitiba", "porto alegre", "florianopolis",
    "joao pessoa", "maceio", "aracaju", "teresina", "macapa", "boa vista", "cuiaba", "campo grande",
    "goiania", "belo horizonte", "brasilia", "uberaba", "uberlandia", "guarapuava", "divinopolis",
    "laguna", "inhapim", "pinhais", "londrina", "maringa", "campinas", "niteroi", "fluminense",
    "pampulha", "ibirapuera",
]


def cita_lugar(titulo):
    palavras = f" {normalizar(titulo)} "
    return next((lugar for lugar in LUGARES if f" {lugar} " in palavras), None)


def main():
    rotulos = json.loads(ROTULOS.read_text(encoding="utf-8"))["manchetes"]
    pegos_regionais, pegos_outro_ruido, uteis_derrubados = [], [], []
    for m in rotulos:
        lugar = cita_lugar(m["titulo"])
        if not lugar:
            continue
        if m["relevante"]:
            uteis_derrubados.append((m["titulo"], lugar))
        elif m["motivo"] == "regional_irrelevante":
            pegos_regionais.append((m["titulo"], lugar))
        else:
            pegos_outro_ruido.append((m["titulo"], lugar))

    regionais = [m for m in rotulos if m["motivo"] == "regional_irrelevante"]
    uteis = sum(1 for m in rotulos if m["relevante"])
    print(f"Regra: o título nomeia um lugar do Brasil ({len(LUGARES)} nomes na lista)\n")
    print(f"  regionais pegos       : {len(pegos_regionais)} de {len(regionais)}")
    print(f"  outro ruído pego junto: {len(pegos_outro_ruido)} (bônus)")
    print(f"  ÚTEIS derrubados      : {len(uteis_derrubados)} de {uteis}  <- o erro caro")

    for titulo, itens in (("regionais que a regra pegou", pegos_regionais),
                          ("ÚTEIS que a regra derrubaria (falso positivo)", uteis_derrubados)):
        print(f"\n-- {titulo}:")
        for texto, lugar in itens:
            print(f"   ({lugar}) {texto[:72]}")
    print("\n-- regionais que ESCAPARAM:")
    for m in regionais:
        if not cita_lugar(m["titulo"]):
            print(f"        {m['titulo'][:72]}")


if __name__ == "__main__":
    main()
