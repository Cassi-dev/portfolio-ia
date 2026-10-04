"""
Lê a foto (ou PDF) de um cardápio, mostra o que entendeu e guarda como uma captura do alvo.
A partir da segunda captura do mesmo alvo, o monitor passa a dizer o que subiu, baixou, entrou e saiu.

    GEMINI_API_KEY=... python projeto_02_analisador_acoes/adicionar_cardapio.py --cliente bar-do-ze --alvo concorrente-a foto.jpg
    ... --so-ler foto.jpg          # lê e mostra, sem guardar (para conferir a leitura antes)
    ... --data 2026-09-15          # data do cardápio, se a foto não for de hoje
    ... --comparar                 # mostra a diferença para a captura anterior

Esta etapa NÃO tem modo offline: sem chave de API não há como ler uma imagem. A imagem em si não é guardada,
só a tabela extraída e o nome do arquivo.
"""
import argparse
import os
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import monitorados
from base_eventos import BaseEventos
from cardapio import SemLeituraDeImagem, comparar, ler_cardapio_de_arquivo
from ciclo import diferenca_de_cardapio
from core.llm import FalhaLLM, RespostaInvalida, criar_cliente


def imprimir_cardapio(lido: dict) -> None:
    print(f"\nEstabelecimento lido: {lido['estabelecimento'] or '(não apareceu na imagem)'}")
    print(f"Itens: {len(lido['itens'])} | com preço legível: {lido['com_preco']}")
    if lido["observacoes"]:
        print(f"Observação do leitor: {lido['observacoes']}")
    categoria_atual = None
    for item in lido["itens"]:
        if item["categoria"] != categoria_atual:
            categoria_atual = item["categoria"]
            print(f"\n  [{categoria_atual or 'sem categoria'}]")
        preco = f"R$ {item['preco']:.2f}" if item["preco"] is not None else (item["preco_texto"] or "sem preço")
        print(f"    {item['nome'][:60]:<62} {preco}")


def imprimir_diferenca(diferenca: dict) -> None:
    print(f"\n=== Cardápio: {diferenca['de']} -> {diferenca['para']} "
          f"({diferenca['itens_antes']} para {diferenca['itens_depois']} itens)")
    for aviso in diferenca["avisos"]:
        print(f"  ! {aviso}")
    if diferenca["variacao_media_pct"] is not None:
        print(f"  Variação média dos itens que mudaram: {diferenca['variacao_media_pct']:+.1f}%")
    for rotulo, chave in (("SUBIU", "subiram"), ("BAIXOU", "baixaram")):
        for m in diferenca[chave]:
            pct = f"{m['variacao_pct']:+.1f}%" if m["variacao_pct"] is not None else ""
            print(f"  {rotulo:<6} {m['nome'][:50]:<52} R$ {m['preco_antes']:.2f} -> R$ {m['preco_depois']:.2f}  {pct}")
    for m in diferenca["novos"]:
        preco = f"R$ {m['preco']:.2f}" if m["preco"] is not None else (m["preco_texto"] or "sem preço")
        print(f"  NOVO   {m['nome'][:50]:<52} {preco}")
    for m in diferenca["sumiram"]:
        print(f"  SAIU   {m['nome'][:50]}")
    if diferenca["sem_comparacao"]:
        print(f"  ({len(diferenca['sem_comparacao'])} item(ns) sem preço legível em alguma das capturas: não comparados)")
    print(f"  Sem mudança de preço: {diferenca['iguais']} item(ns).")


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Lê um cardápio por foto/PDF e guarda como captura do alvo.")
    parser.add_argument("arquivo", help="a foto ou o PDF do cardápio")
    parser.add_argument("--cliente", required=True)
    parser.add_argument("--alvo", required=True)
    parser.add_argument("--data", default=date.today().isoformat(), help="data do cardápio (padrão: hoje)")
    parser.add_argument("--cadastro", default=None)
    parser.add_argument("--banco", default=None)
    parser.add_argument("--so-ler", action="store_true", help="lê e mostra, sem guardar")
    parser.add_argument("--comparar", action="store_true", help="mostra a diferença para a captura anterior")
    args = parser.parse_args(argumentos)

    caminho = Path(args.arquivo)
    if not caminho.exists():
        print(f"arquivo não encontrado: {caminho}")
        return 1

    try:
        cadastro = monitorados.carregar(args.cadastro)
        cliente = cadastro.por_id(args.cliente)
    except (FileNotFoundError, KeyError) as erro:
        print(erro)
        return 1
    alvo = next((a for a in cliente.alvos if a.id == args.alvo), None)
    if alvo is None:
        print(f"alvo '{args.alvo}' não está no cliente '{cliente.id}' (há: {', '.join(a.id for a in cliente.alvos)})")
        return 1

    chave = os.environ.get("GEMINI_API_KEY", "")
    if not chave.strip():
        print("Defina GEMINI_API_KEY: ler cardápio por foto precisa da IA, não há OCR local neste projeto.")
        return 1

    try:
        lido = ler_cardapio_de_arquivo(criar_cliente(chave), caminho, alvo.nome)
    except (SemLeituraDeImagem, FalhaLLM, RespostaInvalida, ValueError) as erro:
        print(f"não consegui ler o cardápio: {erro}")
        return 1

    if not lido["legivel"]:
        print(f"A imagem não foi lida como cardápio. {lido['observacoes']}")
        return 1
    imprimir_cardapio(lido)

    if args.so_ler:
        print("\n(--so-ler: nada foi guardado)")
        return 0

    with BaseEventos(args.banco) as base:
        anterior = base.capturas(cliente.id, alvo.id, limite=1)
        captura_id = base.guardar_cardapio(cliente.id, alvo.id, args.data, caminho.name, lido)
        print(f"\nCaptura {captura_id} guardada para {alvo.nome} em {args.data} "
              f"({len(lido['itens'])} itens). A imagem não foi armazenada.")
        if anterior and args.comparar:
            imprimir_diferenca(diferenca_de_cardapio(base, cliente.id, alvo.id))
        elif anterior:
            print("Use --comparar para ver a diferença para a captura anterior (ou rode o monitor).")
        else:
            print("Esta é a primeira captura deste alvo: mande outra mais adiante para haver comparação.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
