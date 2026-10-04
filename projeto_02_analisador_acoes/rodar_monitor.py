"""
Roda um ciclo do monitor para cada cliente do cadastro. É este comando que o agendador chama.

    python projeto_02_analisador_acoes/rodar_monitor.py --criar-exemplo   # gera monitorados.json para editar
    python projeto_02_analisador_acoes/rodar_monitor.py --listar          # o que está cadastrado
    python projeto_02_analisador_acoes/rodar_monitor.py                   # roda todos os clientes
    python projeto_02_analisador_acoes/rodar_monitor.py --cliente bar-do-ze
    python projeto_02_analisador_acoes/rodar_monitor.py --historico       # os últimos ciclos

Com GEMINI_API_KEY no ambiente, o sentimento sai da IA; sem ela, do léxico local (e a saída avisa).
O relatório para o cliente é o próximo passo: aqui o ciclo só coleta, guarda e detecta.
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
from base_eventos import CAMINHO_PADRAO, BaseEventos
from ciclo import rodar_ciclo
from core.llm import FalhaLLM, criar_cliente


def cliente_llm(sem_ia: bool):
    chave = "" if sem_ia else os.environ.get("GEMINI_API_KEY", "")
    if not chave.strip():
        print("IA: desligada (sem GEMINI_API_KEY) — sentimento pelo léxico local, que erra ironia e contexto.")
        return None
    try:
        print("IA: Gemini ligado.")
        return criar_cliente(chave)
    except FalhaLLM as erro:
        print(f"IA: falhou ao iniciar ({erro}). Seguindo com o léxico local.")
        return None


def imprimir_resumo(resumo: dict) -> None:
    print(f"\n=== {resumo['cliente_nome']} (ciclo {resumo['ciclo_id']}, referência {resumo['referencia']})")
    print(f"Coletados: {resumo['coletados']} | novos: {resumo['novos']} | pontuados agora: {resumo['pontuados']}"
          f" | motores: {resumo['motores'] or '-'}")
    if resumo["primeira_coleta"]:
        print("  i PRIMEIRA COLETA: tudo aqui é histórico, não novidade. Sem alerta de pico ou virada — o RSS traz")
        print("    muito mais notícia recente do que antiga, então esta foto não serve de linha de base.")
    for motivo in resumo["motivos_degradado"]:
        print(f"  ! modo degradado: {motivo}")
    for erro in resumo["erros"]:
        print(f"  ! erro de coleta: {erro}")

    for alvo in resumo["por_alvo"]:
        sinal = f"{alvo['sinal']:+.2f}" if alvo["sinal"] is not None else "n/d"
        marca = "*** ALERTA" if alvo["alerta"] else ""
        print(f"\n  [{alvo['papel']}] {alvo['nome']}: {alvo['novos']} novos de {alvo['total_na_base']} "
              f"na janela | sinal {sinal} {marca}")
        pico, virada = alvo["pico"], alvo["virada"]
        if pico["e_pico"]:
            razao = f"{pico['razao']}x a média" if pico["razao"] is not None else "sem histórico para comparar"
            print(f"      pico de volume: {pico['n_recente']} em 7 dias ({razao})")
        elif not pico["comparavel"] and pico["n_recente"]:
            print(f"      volume: {pico['n_recente']} em 7 dias (ainda sem observação suficiente para dizer se é pico)")
        if virada["virou"]:
            print(f"      virada de sentimento: {virada['anterior']:+.2f} -> {virada['atual']:+.2f} "
                  f"(delta {virada['delta']:+.2f})")
        cardapio = alvo.get("cardapio")
        if cardapio and (cardapio["subiram"] or cardapio["baixaram"] or cardapio["novos"] or cardapio["sumiram"]):
            media = f", média {cardapio['variacao_media_pct']:+.1f}%" if cardapio["variacao_media_pct"] is not None else ""
            print(f"      cardápio ({cardapio['de']} -> {cardapio['para']}): {len(cardapio['subiram'])} subiram, "
                  f"{len(cardapio['baixaram'])} baixaram, {len(cardapio['novos'])} novos, "
                  f"{len(cardapio['sumiram'])} saíram{media}")
            for m in cardapio["subiram"][:3]:
                print(f"          {m['nome'][:50]}: R$ {m['preco_antes']:.2f} -> R$ {m['preco_depois']:.2f}")
            for aviso in cardapio["avisos"]:
                print(f"          ! {aviso}")
        for evento in alvo["gatilhos"]:
            print(f"      gatilho '{evento['gatilho']}': [{evento['data']}] {evento['titulo']}")
        for evento in alvo["novidades"][:5]:
            score = f"{evento['score']:+.2f}" if evento.get("score") is not None else " n/d "
            print(f"      novo {score} [{evento['data']}] {evento['titulo'][:90]} ({evento['fonte']})")
        if len(alvo["novidades"]) > 5:
            print(f"      ... e mais {len(alvo['novidades']) - 5} novidades")


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Ciclo do monitor de notícias por cliente.")
    parser.add_argument("--cliente", help="roda só este cliente (id do cadastro)")
    parser.add_argument("--cadastro", default=None, help="caminho do monitorados.json")
    parser.add_argument("--banco", default=None, help=f"caminho do SQLite (padrão: {CAMINHO_PADRAO.name})")
    parser.add_argument("--sem-ia", action="store_true", help="força o léxico local mesmo com chave no ambiente")
    parser.add_argument("--dedup", default="embedding", choices=["embedding", "tokens"],
                        help="como reconhecer 'a mesma notícia de novo' (padrão: embedding; ver deduplicacao.py)")
    parser.add_argument("--criar-exemplo", action="store_true", help="grava um cadastro de exemplo e sai")
    parser.add_argument("--listar", action="store_true", help="mostra o cadastro e sai")
    parser.add_argument("--historico", action="store_true", help="mostra os últimos ciclos e sai")
    parser.add_argument("--json", action="store_true", help="imprime o resumo em JSON (para encadear com outro script)")
    args = parser.parse_args(argumentos)

    caminho_cadastro = Path(args.cadastro) if args.cadastro else monitorados.CAMINHO_PADRAO
    if args.criar_exemplo:
        if caminho_cadastro.exists():
            print(f"{caminho_cadastro} já existe; não vou sobrescrever. Apague ou edite o arquivo.")
            return 1
        monitorados.salvar(monitorados.cadastro_de_exemplo(), caminho_cadastro)
        print(f"Cadastro de exemplo criado em {caminho_cadastro}. Edite os nomes e termos antes de rodar.")
        return 0

    if args.historico:
        with BaseEventos(args.banco) as base:
            for c in base.ciclos(args.cliente):
                print(f"[{c['id']}] {c['cliente_id']} {c['inicio']} -> {c['fim'] or 'em aberto'} | "
                      f"coletados {c['coletados']} novos {c['novos']} pontuados {c['pontuados']} {c['erros']}")
            print(f"\nEventos guardados: {base.contagem(args.cliente)}")
        return 0

    try:
        cadastro = monitorados.carregar(caminho_cadastro)
    except FileNotFoundError as erro:
        print(erro)
        return 1

    clientes = [cadastro.por_id(args.cliente)] if args.cliente else cadastro.clientes
    if args.listar:
        for c in clientes:
            print(f"{c.id} ({c.perfil}, janela {c.janela_dias}d, {len(c.gatilhos)} gatilhos): {c.nome}")
            for a in c.alvos:
                print(f"    [{a.papel}] {a.id}: {', '.join(a.termos)} {a.tema} ({a.regiao})")
        return 0

    llm = cliente_llm(args.sem_ia)
    from deduplicacao import escolher

    dedup = escolher(args.dedup)
    if dedup.modo != args.dedup:
        print(f"Deduplicação: '{args.dedup}' indisponível (falta sentence-transformers); usando '{dedup.modo}'.")
    else:
        print(f"Deduplicação: {dedup.modo} (limiar {dedup.limiar}).")

    resumos = []
    with BaseEventos(args.banco) as base:
        for cliente in clientes:
            resumo = rodar_ciclo(cliente, base, client_llm=llm, deduplicador=dedup)
            resumos.append(resumo)
            if not args.json:
                imprimir_resumo(resumo)
    if args.json:
        print(json.dumps(resumos, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
