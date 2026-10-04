"""
Gera o Radar de um cliente, mostra para você conferir e só depois marca como aprovado.

    python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze            # gera o rascunho e abre o HTML
    python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze --itens    # lista os itens com id
    python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze --excluir a1b2,c3d4
    python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze --aprovar 7
    python projeto_02_analisador_acoes/gerar_radar.py --historico

Nada é enviado por aqui. O comando entrega um arquivo HTML (imprima em PDF pelo navegador) e registra o estado.
O envio ao cliente é seu: assim ninguém recebe nada sem uma pessoa ter lido antes.
"""
import argparse
import json
import sys
import webbrowser
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import monitorados
from base_eventos import BaseEventos
from relatorio import montar_radar, salvar_html, sem_novidade


def listar_itens(base, cliente) -> int:
    """Os itens que entrariam no próximo Radar, com id, para você escolher o que descartar."""
    corte = base.corte_do_proximo_relatorio(cliente.id)
    eventos = base.eventos_desde(cliente.id, corte)
    if not eventos:
        print("Nenhum item novo desde o último Radar entregue.")
        return 0
    nomes = {a.id: a.nome for a in cliente.alvos}
    print(f"{len(eventos)} item(ns) entrariam no próximo Radar:\n")
    for evento in eventos:
        tom = f" [{evento['classificacao']}]" if evento.get("motor") == "gemini" and evento.get("classificacao") else ""
        print(f"  {evento['id']}  {evento['data']}  {nomes.get(evento['alvo_id'], evento['alvo_id'])[:18]:<20}"
              f"{evento['titulo'][:72]}{tom}")
    print("\nPara tirar algum do relatório: --excluir id1,id2 (a exclusão vale para sempre e também "
          "limpa os detectores).")
    return 0


def imprimir_resumo(radar: dict, arquivo: Path, relatorio_id: int) -> None:
    print(f"\nRadar #{relatorio_id} · {radar['cliente_nome']} · {radar['periodo_de']} a {radar['periodo_ate']}"
          f"{' (primeira edição)' if radar['primeiro'] else ''}")
    if sem_novidade(radar):
        print("  Sem novidade no período — o Radar diz isso ao cliente em vez de vir vazio.")
    else:
        print(f"  {radar['total_itens']} item(ns), {len(radar['destaques'])} destaque(s)")
        for destaque in radar["destaques"]:
            print(f"    • {destaque['texto']}")
        for secao in radar["secoes"]:
            for alvo in secao["alvos"]:
                cardapio = " + cardápio" if alvo["cardapio"] else ""
                print(f"    [{secao['papel']}] {alvo['nome']}: {len(alvo['novidades'])} novidade(s){cardapio}")
    for aviso in radar["avisos"]:
        print(f"  ! {aviso}")
    print(f"\n  Arquivo: {arquivo}")
    print(f"  Confira e depois: --aprovar {relatorio_id}   (ou --descartar {relatorio_id})")


def entregar(base, args, parser) -> int:
    """Simula ou faz o envio. Simular não precisa de senha nenhuma e não toca na rede."""
    import entrega

    identificador = args.enviar or args.simular_envio
    registro = base.relatorio(identificador)
    if registro is None:
        print(f"Radar #{identificador} não existe.")
        return 1
    try:
        cliente = monitorados.carregar(args.cadastro).por_id(registro["cliente_id"])
    except (FileNotFoundError, KeyError) as erro:
        print(erro)
        return 1

    if args.simular_envio:
        # um endereço de mentira mesmo: entre parênteses viraria comentário de cabeçalho e o campo sairia vazio
        remetente = "remetente-ainda-nao-configurado@exemplo.com"
        if registro["estado"] != "aprovado":
            print(f"Atenção: este Radar está como '{registro['estado']}'. O envio de verdade seria recusado.\n")
    else:
        try:
            config = entrega.configuracao()
            remetente = config["remetente"]
        except entrega.ConfiguracaoIncompleta as erro:
            print(erro)
            return 1

    try:
        mensagem = (entrega.preparar(registro, cliente, remetente) if args.enviar
                    else entrega.montar_email(registro, cliente.nome, cliente.email or "cliente@exemplo.com", remetente))
    except (entrega.NaoAprovado, ValueError) as erro:
        print(erro)
        return 1

    anexos = [p.get_filename() for p in mensagem.iter_attachments()]
    print(f"De: {mensagem['From']}\nPara: {mensagem['To']}\nAssunto: {mensagem['Subject']}")
    print(f"Anexo(s): {', '.join(anexos) or 'nenhum'}\n")
    print(mensagem.get_body(("plain",)).get_content())

    if args.simular_envio:
        print("--simular-envio: nada foi enviado.")
        return 0
    try:
        entrega.enviar(mensagem, config)
    except Exception as erro:
        print(f"falha no envio: {type(erro).__name__}: {erro}")
        return 1
    base.mudar_estado(identificador, "enviado", f"enviado para {cliente.email}")
    print(f"Enviado. Radar #{identificador} marcado como enviado.")
    return 0


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(description="Gera, revisa e entrega o Radar de um cliente.")
    parser.add_argument("--cliente", help="id do cliente no cadastro")
    parser.add_argument("--cadastro", default=None)
    parser.add_argument("--banco", default=None)
    parser.add_argument("--pasta", default=None, help="onde gravar o HTML")
    parser.add_argument("--itens", action="store_true", help="lista os itens do próximo Radar e sai")
    parser.add_argument("--excluir", default="", help="ids de eventos a descartar, separados por vírgula")
    parser.add_argument("--restaurar", default="", help="ids de eventos a trazer de volta")
    parser.add_argument("--aprovar", type=int, help="marca o Radar como aprovado (pronto para enviar)")
    parser.add_argument("--enviado", type=int, help="marca o Radar como enviado ao cliente")
    parser.add_argument("--descartar", type=int, help="descarta o rascunho (os itens voltam no próximo)")
    parser.add_argument("--notas", default="", help="observação da revisão")
    parser.add_argument("--historico", action="store_true", help="lista os Radares já gerados")
    parser.add_argument("--sem-abrir", action="store_true", help="não abre o HTML no navegador")
    parser.add_argument("--simular-envio", type=int, metavar="ID",
                        help="mostra o e-mail que sairia, sem enviar nada nem precisar de senha")
    parser.add_argument("--enviar", type=int, metavar="ID",
                        help="envia por e-mail um Radar APROVADO e o marca como enviado")
    args = parser.parse_args(argumentos)

    with BaseEventos(args.banco) as base:
        if args.historico:
            for r in base.relatorios(args.cliente):
                print(f"[{r['id']}] {r['cliente_id']:<22} {r['periodo_de']} a {r['periodo_ate']}  "
                      f"{r['estado']:<11} {r['itens']} itens  {r['arquivo'] or ''} {r['notas']}")
            return 0

        if args.enviar or args.simular_envio:
            return entregar(base, args, parser)

        for identificador, estado in ((args.aprovar, "aprovado"), (args.enviado, "enviado"),
                                      (args.descartar, "descartado")):
            if identificador:
                existente = next((r for r in base.relatorios(limite=500) if r["id"] == identificador), None)
                if existente is None:
                    print(f"Radar #{identificador} não existe.")
                    return 1
                base.mudar_estado(identificador, estado, args.notas)
                print(f"Radar #{identificador} ({existente['cliente_id']}) agora está: {estado}.")
                if estado == "descartado":
                    print("Os itens dele voltam a aparecer no próximo Radar.")
                return 0

        if not args.cliente:
            parser.error("informe --cliente (ou use --historico)")
        try:
            cliente = monitorados.carregar(args.cadastro).por_id(args.cliente)
        except (FileNotFoundError, KeyError) as erro:
            print(erro)
            return 1

        if args.excluir or args.restaurar:
            if args.excluir:
                ids = [i.strip() for i in args.excluir.split(",") if i.strip()]
                print(f"{base.excluir_eventos(ids, args.notas or 'descartado na revisão')} item(ns) excluído(s).")
            if args.restaurar:
                base.restaurar_eventos([i.strip() for i in args.restaurar.split(",") if i.strip()])
                print("Itens restaurados.")
            return 0

        if args.itens:
            return listar_itens(base, cliente)

        radar = montar_radar(base, cliente)
        arquivo = salvar_html(radar, args.pasta)
        relatorio_id = base.criar_relatorio(cliente.id, radar["periodo_de"], radar["periodo_ate"], radar["corte"],
                                            radar["total_itens"], str(arquivo),
                                            json.dumps(radar["destaques"], ensure_ascii=False))
        imprimir_resumo(radar, arquivo, relatorio_id)
        if not args.sem_abrir:
            webbrowser.open(arquivo.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
