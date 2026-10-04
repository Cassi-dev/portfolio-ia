"""
Dividir o alvo de setor em quatro assuntos derruba o ruído?

O alvo único ("food service" OR "bares e restaurantes") trouxe 54 manchetes com 61% de ruído, e os 21 itens
úteis se organizavam em quatro assuntos. Esta é a divisão testada.

A medição é parcial de propósito: das manchetes que voltam, as que já estão rotuladas vêm com gabarito; as
novas ficam listadas para conferência à mão. A sobreposição é impressa para ninguém confundir isto com a taxa
medida nas 80 originais.

Resultado: a taxa cai (60% -> 36-43% em três dos quatro), mas o volume vai de 54 para 213 manchetes, quase
tudo regional. Não adotado; ver o README desta pasta. Este script usa a rede (Google News RSS).
"""
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "projeto_02_analisador_acoes"))
ROTULOS = RAIZ / "projeto_02_analisador_acoes/dados_medicao/rotulos_80_manchetes.json"

from coleta_noticias import coletar_por_termos  # noqa: E402
from deteccao import normalizar  # noqa: E402

SETOR = ["bares e restaurantes", "food service"]
ANTIGO = ("setor-food-service (o de hoje)", SETOR, "(Brasil)")
NOVOS_ALVOS = [
    ("setor-regulacao", SETOR,
     '(tributação OR imposto OR "reforma tributária" OR trabalhista OR fiscalização OR sanitária)'),
    ("setor-desempenho", SETOR, "(vendas OR faturamento OR movimento OR lucro OR consumo OR Abrasel)"),
    ("setor-eventos", SETOR, "(feira OR congresso OR expo OR encontro OR summit)"),
    ("setor-mercado", SETOR,
     '(franquia OR franchising OR delivery OR tendência OR "chega ao Brasil" OR inaugura)'),
]


def avaliar(nome, termos, tema, gabarito):
    manchetes = coletar_por_termos(termos, tema, 30, "BR")
    conhecidas = [gabarito[normalizar(m["titulo"])] for m in manchetes if normalizar(m["titulo"]) in gabarito]
    uteis = sum(1 for r in conhecidas if r["relevante"])
    novas = [m for m in manchetes if normalizar(m["titulo"]) not in gabarito]
    return {"nome": nome, "total": len(manchetes), "com_gabarito": len(conhecidas), "uteis": uteis,
            "ruido": len(conhecidas) - uteis, "novas": novas,
            "ruido_no_conhecido": round((len(conhecidas) - uteis) / len(conhecidas), 3) if conhecidas else None}


def main():
    gabarito = {normalizar(m["titulo"]): m
                for m in json.loads(ROTULOS.read_text(encoding="utf-8"))["manchetes"]}
    print("Coletando...\n")
    resultados = [avaliar(*ANTIGO, gabarito)] + [avaliar(*alvo, gabarito) for alvo in NOVOS_ALVOS]

    print(f"\n{'alvo':<34}{'voltaram':>9}{'com gabarito':>14}{'úteis':>7}{'ruído':>7}{'ruído no conhecido':>20}")
    print("-" * 92)
    for r in resultados:
        taxa = f"{r['ruido_no_conhecido']:.0%}" if r["ruido_no_conhecido"] is not None else "n/d"
        print(f"{r['nome']:<34}{r['total']:>9}{r['com_gabarito']:>14}{r['uteis']:>7}{r['ruido']:>7}{taxa:>20}")

    ineditas = {}
    for r in resultados[1:]:
        for m in r["novas"]:
            ineditas.setdefault(normalizar(m["titulo"]), (m, r["nome"]))
    print(f"\nOs quatro juntos: {sum(r['total'] for r in resultados[1:])} manchetes "
          f"({sum(r['com_gabarito'] for r in resultados[1:])} com gabarito, "
          f"{sum(r['uteis'] for r in resultados[1:])} úteis) + {len(ineditas)} inéditas para conferir.")
    print("\n=== manchetes inéditas (sem gabarito), para conferir a olho ===")
    for m, alvo in list(ineditas.values())[:40]:
        print(f"  [{alvo.replace('setor-', ''):<11}] {m['titulo'][:84]}")


if __name__ == "__main__":
    main()
