"""
O filtro de relevância derruba o ruído sem jogar fora notícia boa? Mede contra os rótulos humanos.

    GEMINI_API_KEY=... python projeto_02_analisador_acoes/avaliar_relevancia.py --cliente rede-exemplo

Compara o julgamento da IA com o que uma pessoa decidiu em cada manchete já rotulada. Custa 1 chamada a cada
25 manchetes (centavos). O resultado vai para resultados/avaliacao_relevancia.json.

Duas leituras, e a segunda é a justa: a IA vê uma manchete por vez e não tem como saber que ela repete outra
já guardada. Descontar as duplicatas mostra o que o filtro realmente consegue fazer; quem cuida de repetição
é a deduplicação por embedding, que já está no ar.

Se o filtro se provar aqui, o passo seguinte é ligá-lo na revisão — desmarcando o provável ruído para você
confirmar, nunca descartando sozinho.
"""
import argparse
import json
import os
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import monitorados
from base_eventos import BaseEventos
from core.llm import FalhaLLM, criar_cliente, estatisticas
from relevancia import efeito, julgar

MOTIVO_DUPLICATA = "duplicata"


def avaliar(base, cliente, client_llm, lote: int) -> dict:
    rotulados = base.rotulos(cliente.id)
    if not rotulados:
        raise SystemExit(f"nenhum item rotulado para '{cliente.id}'. Rotule antes "
                         "(medir_monitor.py --exportar/--importar) ou revise um Radar.")

    por_alvo, papeis = {}, {a.id: a.papel for a in cliente.alvos}
    nomes = {a.id: a.nome for a in cliente.alvos}
    for rotulo in rotulados:
        por_alvo.setdefault(rotulo["alvo_id"], []).append(rotulo)

    julgamentos, degradacoes = {}, []
    for alvo_id, itens in por_alvo.items():
        print(f"  julgando {len(itens)} manchete(s) de {nomes.get(alvo_id, alvo_id)}...")
        resultado = julgar(client_llm, [{"id": i["evento_id"], "titulo": i["titulo"], "fonte": i["fonte"]} for i in itens],
                           nomes.get(alvo_id, alvo_id), cliente.descricao, papeis.get(alvo_id, "concorrente"), lote)
        julgamentos.update(resultado["julgamentos"])
        if resultado["degradado"]:
            degradacoes.append(f"{alvo_id}: {resultado['motivo_degradado']}")

    humanos = {r["evento_id"]: bool(r["relevante"]) for r in rotulados}
    sem_duplicata = {i: v for i, v in humanos.items()
                     if v or next((r["motivo"] for r in rotulados if r["evento_id"] == i), "") != MOTIVO_DUPLICATA}

    discordancias = []
    for rotulo in rotulados:
        ia = julgamentos.get(rotulo["evento_id"])
        if ia is not None and ia["relevante"] != bool(rotulo["relevante"]):
            discordancias.append({
                "titulo": rotulo["titulo"], "alvo": rotulo["alvo_id"],
                "humano": "útil" if rotulo["relevante"] else f"ruído ({rotulo['motivo']})",
                "ia": "útil" if ia["relevante"] else "ruído", "motivo_da_ia": ia["motivo"],
            })

    return {
        "cliente": cliente.id,
        "julgados": len(julgamentos),
        "rotulados": len(rotulados),
        "degradacoes": degradacoes,
        "tudo": efeito(julgamentos, humanos),
        "sem_duplicatas": efeito(julgamentos, sem_duplicata),
        "discordancias": discordancias,
        "uso_llm": estatisticas(),
    }


def imprimir_efeito(titulo: str, dados: dict) -> None:
    print(f"\n--- {titulo}")
    if not dados.get("comparados"):
        print("  nada para comparar.")
        return
    print(f"  {dados['comparados']} manchetes | ruído antes: {dados['ruido_antes']} "
          f"({dados['taxa_de_ruido_antes']:.1%})")
    print(f"  A IA cortaria {dados['cortou_ruido'] + dados['cortou_util']}: "
          f"{dados['cortou_ruido']} de ruído (acerto) e {dados['cortou_util']} de útil (erro caro)")
    depois = f"{dados['taxa_de_ruido_depois']:.1%}" if dados["taxa_de_ruido_depois"] is not None else "n/d"
    print(f"  Sobrariam {dados['sobraram']} manchetes, com {dados['deixou_passar_ruido']} de ruído -> {depois}")
    if dados["ruido_pego"] is not None:
        print(f"  Pegou {dados['ruido_pego']:.0%} do ruído | perdeu {(dados['uteis_perdidos'] or 0):.0%} do que era útil")


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Mede o filtro de relevância contra os rótulos humanos.")
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--cadastro", default=None)
    parser.add_argument("--banco", default=None)
    parser.add_argument("--lote", type=int, default=25, help="manchetes por chamada da IA")
    args = parser.parse_args(argumentos)

    chave = os.environ.get("GEMINI_API_KEY", "")
    if not chave.strip():
        print("Defina GEMINI_API_KEY: julgar relevância precisa da IA (não há versão local disto).")
        return 1
    try:
        cliente = monitorados.carregar(args.cadastro).por_id(args.cliente)
    except (FileNotFoundError, KeyError) as erro:
        print(erro)
        return 1
    try:
        client_llm = criar_cliente(chave)
    except FalhaLLM as erro:
        print(f"não consegui iniciar o Gemini: {erro}")
        return 1

    if not cliente.descricao:
        print(f"Aviso: o cliente '{cliente.id}' não tem 'descricao' no cadastro. O filtro julga melhor sabendo "
              'o que ele é e onde atua (ex.: "hamburgueria em Curitiba").')

    with BaseEventos(args.banco) as base:
        resultado = avaliar(base, cliente, client_llm, args.lote)

    imprimir_efeito("Todas as manchetes rotuladas", resultado["tudo"])
    imprimir_efeito("Sem as duplicatas (a leitura justa: a IA vê uma manchete por vez)", resultado["sem_duplicatas"])
    for degradacao in resultado["degradacoes"]:
        print(f"\n  ! {degradacao}")
    if resultado["discordancias"]:
        print(f"\n--- Onde a IA e você discordaram ({len(resultado['discordancias'])}):")
        for d in resultado["discordancias"][:15]:
            print(f"  [{d['alvo']}] {d['titulo'][:70]}")
            print(f"      você: {d['humano']} | IA: {d['ia']} ({d['motivo_da_ia']})")
    uso = resultado["uso_llm"]
    print(f"\nIA: {uso['chamadas_api']} chamadas, {uso['tokens_entrada']} tokens de entrada / "
          f"{uso['tokens_saida']} de saída")

    destino = BASE / "resultados"
    destino.mkdir(exist_ok=True)
    (destino / "avaliacao_relevancia.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    print(f"Salvo em {destino / 'avaliacao_relevancia.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
