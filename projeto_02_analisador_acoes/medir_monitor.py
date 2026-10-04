"""
Mede quanto do que o monitor mostraria é ruído, e ajuda a rotular o que ainda não tem rótulo.

    python projeto_02_analisador_acoes/medir_monitor.py                          # as métricas
    python projeto_02_analisador_acoes/medir_monitor.py --exportar para_rotular.json --cliente x
    python projeto_02_analisador_acoes/medir_monitor.py --importar para_rotular.json

O arquivo exportado traz uma linha por item com "relevante": null. Troque por 1 (vale mostrar ao cliente) ou
0 (ruído), opcionalmente escreva o motivo, e importe de volta. Quem não for preenchido é ignorado.

Rotular é trabalho humano e é o único jeito de saber se o serviço incomoda quem paga por ele.
"""
import argparse
import json
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from base_eventos import BaseEventos
from medicao import leitura, medir


def exportar(base, cliente_id: str, destino: Path, limite: int) -> int:
    pendentes = base.sem_rotulo(cliente_id, limite)
    if not pendentes:
        print(f"Nada sem rótulo para '{cliente_id}'.")
        return 0
    conteudo = [{"id": e["id"], "alvo": e["alvo_id"], "data": e["data"], "fonte": e["fonte"],
                 "titulo": e["titulo"], "relevante": None, "motivo": ""} for e in pendentes]
    destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(conteudo)} item(ns) em {destino}.")
    print('Preencha "relevante" com 1 (vale mostrar) ou 0 (ruído) e rode --importar.')
    return 0


def importar(base, origem: Path) -> int:
    try:
        itens = json.loads(origem.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erro:
        print(f"não consegui ler {origem}: {erro}")
        return 1
    pares = [(i["id"], int(i["relevante"]), i.get("motivo", ""), "manual")
             for i in itens if i.get("relevante") in (0, 1, "0", "1", True, False)]
    ignorados = len(itens) - len(pares)
    base.rotular(pares)
    print(f"{len(pares)} rótulo(s) gravado(s)." + (f" {ignorados} sem 'relevante' preenchido, ignorado(s)." if ignorados else ""))
    return 0


def imprimir(metricas: dict) -> None:
    de_quem = f" · {metricas['cliente']}" if metricas["cliente"] else " (todos os clientes)"
    print(f"\n=== Medição{de_quem}")
    print(f"Eventos na base: {metricas['eventos_na_base']} | rotulados: {metricas['rotulados']}"
          f" ({(metricas['cobertura_da_rotulagem'] or 0):.0%} da base) | origem: {metricas['por_origem'] or '-'}")
    if metricas["rotulados"]:
        taxa = f"{metricas['taxa_de_ruido']:.1%}" if metricas["taxa_de_ruido"] is not None else "n/d"
        print(f"Úteis: {metricas['uteis']} | ruído: {metricas['ruido']} | TAXA DE RUÍDO: {taxa}")

        if metricas["por_alvo"]:
            print("\nPor alvo:")
            for alvo in metricas["por_alvo"]:
                print(f"  {alvo['alvo_id']:<24} {alvo['ruido']:>3} ruído de {alvo['rotulados']:>3}"
                      f"   {(alvo['taxa_de_ruido'] or 0):.0%}")
        if metricas["por_motivo"]:
            print("\nPor que foi descartado:")
            for motivo in metricas["por_motivo"]:
                print(f"  {motivo['motivo'][:30]:<32} {motivo['quantos']:>3}  ({(motivo['fatia_do_ruido'] or 0):.0%} do ruído)")
        piores = [f for f in metricas["por_fonte"] if f["ruido"]][:8]
        if piores:
            print("\nFontes que mais trouxeram ruído:")
            for fonte in piores:
                print(f"  {fonte['fonte'][:38]:<40} {fonte['ruido']:>3} de {fonte['rotulados']:>3}")

    print("\nLeitura:")
    for linha in leitura(metricas):
        print(f"  - {linha}")


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Mede a taxa de ruído do monitor a partir de rótulos humanos.")
    parser.add_argument("--cliente", help="limita a um cliente")
    parser.add_argument("--banco", default=None)
    parser.add_argument("--exportar", help="grava os itens sem rótulo num JSON para você preencher")
    parser.add_argument("--importar", help="lê um JSON preenchido e grava os rótulos")
    parser.add_argument("--limite", type=int, default=100, help="quantos itens exportar (padrão 100)")
    parser.add_argument("--json", action="store_true", help="imprime as métricas em JSON")
    args = parser.parse_args(argumentos)

    with BaseEventos(args.banco) as base:
        if args.exportar:
            if not args.cliente:
                parser.error("--exportar precisa de --cliente")
            return exportar(base, args.cliente, Path(args.exportar), args.limite)
        if args.importar:
            return importar(base, Path(args.importar))
        metricas = medir(base, args.cliente)
        print(json.dumps(metricas, ensure_ascii=False, indent=2) if args.json else "", end="")
        if not args.json:
            imprimir(metricas)
    return 0


if __name__ == "__main__":
    sys.exit(main())
