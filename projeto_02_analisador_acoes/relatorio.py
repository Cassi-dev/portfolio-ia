"""
O Radar: o arquivo que o cliente recebe. É o produto — o painel e o banco são bastidores.

Duas decisões que vêm da natureza do serviço:

1. **Nada é gerado por IA aqui.** O relatório só organiza fatos que já estão na base, cada linha com fonte,
   data e link. Um parágrafo de abertura escrito por um modelo seria bonito e seria o único lugar do produto
   onde caberia uma invenção — justamente no que vai assinado para o cliente.
2. **O período é "desde o último relatório que você recebeu"**, não "os últimos 7 dias". Assim nada é contado
   duas vezes nem cai no vão entre uma edição e outra. Rascunho descartado não move o corte.

O HTML é autocontido (sem CSS externo, sem fonte remota) e imprime em PDF pelo navegador.
"""
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

from cardapio import houve_mudanca
from ciclo import diferenca_de_cardapio
from deteccao import (
    DIAS_ALERTA, gatilhos, janela, normalizar, pico_de_volume, sinal_ponderado, virada_de_sentimento,
)

BASE = Path(__file__).resolve().parent
PASTA_RELATORIOS = BASE / "relatorios"
DIAS_PRIMEIRO_RADAR = 7
TITULOS = {"proprio": "O seu negócio", "concorrente": "Concorrentes", "tema": "O mercado"}
NAO_COBERTO = [
    "Só acompanhamos notícia publicada na web e o cardápio que você nos envia.",
    "Avaliações do Google, redes sociais, preço de fornecedor e valor de aluguel ainda não entram.",
    "Restaurante pequeno aparece pouco em notícia: ausência aqui não quer dizer ausência no mercado.",
]


# ==============================================================================
# CONTEÚDO
# ==============================================================================
def _evento_para_radar(evento: dict) -> dict:
    mostrar_score = evento.get("motor") == "gemini" and evento.get("score") is not None
    return {
        "id": evento["id"], "titulo": evento["titulo"], "data": evento["data"], "fonte": evento.get("fonte", ""),
        "link": evento.get("link", ""), "classificacao": evento.get("classificacao") if mostrar_score else None,
        "score": evento.get("score") if mostrar_score else None,
    }


def _destaques(alvo_nome: str, papel: str, analise: dict, cardapio) -> list:
    """As linhas de "o que mudou" que abrem o relatório: só o que tem motivo, não a lista inteira."""
    linhas = []
    for evento in analise["gatilhos"]:
        # a manchete quase sempre já cita o alvo; repetir o nome na frente fica "Boteco: Boteco sofre..."
        prefixo = "" if normalizar(alvo_nome) in normalizar(evento["titulo"]) else f"{alvo_nome}: "
        linhas.append({"alvo": alvo_nome, "papel": papel, "tipo": "gatilho",
                       "texto": f"{prefixo}{evento['titulo']}", "data": evento["data"],
                       "fonte": evento.get("fonte", ""), "link": evento.get("link", "")})
    if cardapio and houve_mudanca(cardapio):
        partes = []
        for quantos, rotulo in ((len(cardapio["subiram"]), "subiram de preço"), (len(cardapio["baixaram"]), "baixaram"),
                                (len(cardapio["novos"]), "entraram"), (len(cardapio["sumiram"]), "saíram")):
            if quantos:
                partes.append(f"{quantos} {rotulo}")
        media = f" (média {cardapio['variacao_media_pct']:+.1f}%)" if cardapio["variacao_media_pct"] is not None else ""
        linhas.append({"alvo": alvo_nome, "papel": papel, "tipo": "cardapio",
                       "texto": f"Cardápio de {alvo_nome}: {', '.join(partes)}{media}",
                       "data": cardapio["para"], "fonte": "cardápio enviado", "link": ""})
    if analise["pico"]["e_pico"]:
        razao = f"{analise['pico']['razao']}x o normal" if analise["pico"]["razao"] else "sem histórico para comparar"
        linhas.append({"alvo": alvo_nome, "papel": papel, "tipo": "pico",
                       "texto": f"{alvo_nome} apareceu {analise['pico']['n_recente']} vezes em 7 dias ({razao})",
                       "data": "", "fonte": "", "link": ""})
    if analise["virada"]["virou"]:
        virada = analise["virada"]
        direcao = "melhorou" if virada["delta"] > 0 else "piorou"
        linhas.append({"alvo": alvo_nome, "papel": papel, "tipo": "virada",
                       "texto": f"O tom das notícias sobre {alvo_nome} {direcao} "
                                f"({virada['anterior']:+.2f} para {virada['atual']:+.2f})",
                       "data": "", "fonte": "", "link": ""})
    return linhas


def montar_radar(base, cliente, hoje: date = None, corte: str = None) -> dict:
    """
    Monta o conteúdo do Radar a partir da base. `corte` é o gerado_em do último relatório entregue;
    sem ele, o Radar cobre os últimos 7 dias e se apresenta como o primeiro.
    """
    hoje = hoje or datetime.now(timezone.utc).date()
    corte = corte if corte is not None else base.corte_do_proximo_relatorio(cliente.id)
    primeiro = corte is None
    periodo_de = corte[:10] if corte else (hoje - timedelta(days=DIAS_PRIMEIRO_RADAR)).isoformat()

    novos_por_alvo = {}
    for evento in base.eventos_desde(cliente.id, corte):
        novos_por_alvo.setdefault(evento["alvo_id"], []).append(evento)

    observando_desde = base.observando_desde(cliente.id)
    secoes, destaques, total = [], [], 0
    for papel in ("proprio", "concorrente", "tema"):
        alvos_do_papel = []
        for alvo in [a for a in cliente.alvos if a.papel == papel]:
            todos = base.eventos(cliente.id, alvo_id=alvo.id, desde=hoje - timedelta(days=cliente.janela_dias))
            novos = novos_por_alvo.get(alvo.id, [])
            # "novo" aqui é "desde o último relatório", não "desde o último ciclo": são recortes diferentes
            analise = {
                "gatilhos": gatilhos(janela(novos, hoje, DIAS_ALERTA), cliente.gatilhos),
                "pico": pico_de_volume(todos, hoje, observando_desde=observando_desde),
                "virada": virada_de_sentimento(todos, hoje),
            }
            cardapio = diferenca_de_cardapio(base, cliente.id, alvo.id, corte)
            total += len(novos)
            destaques += _destaques(alvo.nome, papel, analise, cardapio)
            alvos_do_papel.append({
                "alvo": alvo.id, "nome": alvo.nome,
                "novidades": [_evento_para_radar(e) for e in novos],
                "sinal": sinal_ponderado(todos, hoje), "total_na_janela": len(todos),
                "cardapio": cardapio if cardapio and houve_mudanca(cardapio) else None,
            })
        if alvos_do_papel:
            secoes.append({"papel": papel, "titulo": TITULOS[papel], "alvos": alvos_do_papel})

    motores = {}
    for evento in base.eventos_desde(cliente.id, corte):
        motores[evento.get("motor") or "sem pontuação"] = motores.get(evento.get("motor") or "sem pontuação", 0) + 1
    avisos = []
    if motores.get("lexico"):
        avisos.append(f"{motores['lexico']} de {total} manchete(s) tiveram o tom avaliado por uma lista de palavras, "
                      "não por IA. Para notícia de restaurante essa lista acerta pouco, então o tom foi omitido nelas.")

    return {
        "cliente": cliente.id, "cliente_nome": cliente.nome, "perfil": cliente.perfil,
        "periodo_de": periodo_de, "periodo_ate": hoje.isoformat(),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "corte": corte, "primeiro": primeiro,
        "destaques": destaques, "secoes": secoes, "total_itens": total,
        "avisos": avisos, "nao_coberto": list(NAO_COBERTO),
    }


def sem_novidade(radar: dict) -> bool:
    return radar["total_itens"] == 0 and not radar["destaques"]


# ==============================================================================
# HTML
# ==============================================================================
def _br(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso or ""


def _moeda(valor) -> str:
    """Relatório brasileiro mostra R$ 12,00 — não R$ 12.00, que é o padrão do Python."""
    if valor is None:
        return "—"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _link(texto: str, url: str) -> str:
    seguro = escape(texto)
    return f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">{seguro}</a>' if url else seguro


ESTILO = """
:root { --tinta:#1c2024; --suave:#6b7480; --linha:#e3e6ea; --destaque:#b45309; --fundo:#fbfaf8; --caixa:#fff; }
* { box-sizing:border-box; }
body { margin:0; padding:32px 20px 60px; background:var(--fundo); color:var(--tinta);
       font:16px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
.folha { max-width:760px; margin:0 auto; }
header { border-bottom:3px solid var(--tinta); padding-bottom:14px; margin-bottom:26px; }
h1 { font-size:27px; margin:0 0 6px; letter-spacing:-.3px; }
.periodo { color:var(--suave); font-size:14px; }
h2 { font-size:18px; margin:34px 0 12px; padding-bottom:6px; border-bottom:1px solid var(--linha); }
h3 { font-size:16px; margin:22px 0 8px; }
.destaques { background:var(--caixa); border:1px solid var(--linha); border-left:4px solid var(--destaque);
             border-radius:8px; padding:14px 18px; }
.destaques ul { margin:0; padding-left:20px; }
.destaques li { margin:8px 0; }
.item { padding:10px 0; border-bottom:1px solid var(--linha); }
.item:last-child { border-bottom:0; }
.meta { color:var(--suave); font-size:13px; margin-top:3px; }
.tag { display:inline-block; font-size:11px; padding:1px 7px; border-radius:20px; border:1px solid var(--linha);
       color:var(--suave); margin-left:6px; vertical-align:1px; }
a { color:#1d4ed8; text-decoration:none; } a:hover { text-decoration:underline; }
table { width:100%; border-collapse:collapse; margin:10px 0 4px; font-size:14px; }
th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--linha); }
th { color:var(--suave); font-weight:600; font-size:12px; text-transform:uppercase; letter-spacing:.4px; }
td.num { text-align:right; white-space:nowrap; }
.sobe { color:#b91c1c; } .desce { color:#15803d; }
.vazio { background:var(--caixa); border:1px dashed var(--linha); border-radius:8px; padding:22px; text-align:center;
         color:var(--suave); }
footer { margin-top:44px; padding-top:16px; border-top:1px solid var(--linha); color:var(--suave); font-size:13px; }
footer ul { padding-left:20px; } footer li { margin:4px 0; }
.aviso { background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:10px 14px; margin:10px 0;
         font-size:14px; color:#78350f; }
@media print { body { background:#fff; padding:0; } .destaques, .vazio { break-inside:avoid; } }
"""


def _html_dos_destaques(destaques: list) -> str:
    if not destaques:
        return ""
    linhas = []
    for d in destaques:
        origem = " · ".join(p for p in (_br(d["data"]), d["fonte"]) if p)
        texto = _link(d["texto"], d["link"]) if d["link"] else escape(d["texto"])
        linhas.append(f"<li>{texto}{f'<div class=meta>{escape(origem)}</div>' if origem else ''}</li>")
    return f'<h2>O que mudou</h2><div class="destaques"><ul>{"".join(linhas)}</ul></div>'


def _html_do_cardapio(cardapio: dict) -> str:
    linhas = []
    for mudanca, classe in [(m, "sobe") for m in cardapio["subiram"]] + [(m, "desce") for m in cardapio["baixaram"]]:
        pct = f"{mudanca['variacao_pct']:+.1f}%" if mudanca["variacao_pct"] is not None else ""
        linhas.append(f"<tr><td>{escape(mudanca['nome'])}</td>"
                      f"<td class=num>{_moeda(mudanca['preco_antes'])}</td>"
                      f"<td class=num>{_moeda(mudanca['preco_depois'])}</td>"
                      f"<td class='num {classe}'>{pct}</td></tr>")
    for item in cardapio["novos"]:
        preco = _moeda(item["preco"]) if item["preco"] is not None else escape(item["preco_texto"] or "—")
        linhas.append(f"<tr><td>{escape(item['nome'])}</td><td class=num>—</td><td class=num>{preco}</td>"
                      f"<td class=num>novo</td></tr>")
    for item in cardapio["sumiram"]:
        linhas.append(f"<tr><td>{escape(item['nome'])}</td><td class=num>{_moeda(item['preco'])}</td>"
                      f"<td class=num>—</td><td class=num>saiu</td></tr>")
    avisos = "".join(f'<div class="aviso">{escape(a)}</div>' for a in cardapio["avisos"])
    return (f"<h3>Cardápio ({_br(cardapio['de'])} → {_br(cardapio['para'])})</h3>{avisos}"
            f"<table><tr><th>Item</th><th class=num>Antes</th><th class=num>Agora</th><th class=num>Variação</th></tr>"
            f"{''.join(linhas)}</table>"
            f"<div class=meta>{cardapio['iguais']} item(ns) sem mudança de preço.</div>")


def _html_dos_alvos(secao: dict) -> str:
    blocos = []
    for alvo in secao["alvos"]:
        itens = []
        for evento in alvo["novidades"]:
            tag = f'<span class=tag>{escape(evento["classificacao"])}</span>' if evento["classificacao"] else ""
            meta = " · ".join(p for p in (_br(evento["data"]), evento["fonte"]) if p)
            itens.append(f'<div class="item">{_link(evento["titulo"], evento["link"])}{tag}'
                         f'<div class=meta>{escape(meta)}</div></div>')
        corpo = "".join(itens) or '<div class=meta>Nenhuma notícia nova no período.</div>'
        cardapio = _html_do_cardapio(alvo["cardapio"]) if alvo["cardapio"] else ""
        blocos.append(f"<h3>{escape(alvo['nome'])}</h3>{corpo}{cardapio}")
    return f'<h2>{escape(secao["titulo"])}</h2>{"".join(blocos)}'


def renderizar_html(radar: dict) -> str:
    cabecalho = (f'<h1>Radar · {escape(radar["cliente_nome"])}</h1>'
                 f'<div class=periodo>{_br(radar["periodo_de"])} a {_br(radar["periodo_ate"])}'
                 f'{" · primeira edição" if radar["primeiro"] else ""} · '
                 f'gerado em {_br(radar["gerado_em"])}</div>')
    if sem_novidade(radar):
        miolo = ('<div class="vazio"><strong>Semana sem novidade.</strong><br>'
                 'Não encontramos notícia nova nem mudança de cardápio no período. '
                 'Isto também é informação: nada se mexeu por aqui.</div>')
    else:
        miolo = _html_dos_destaques(radar["destaques"]) + "".join(_html_dos_alvos(s) for s in radar["secoes"])
    avisos = "".join(f'<div class="aviso">{escape(a)}</div>' for a in radar["avisos"])
    rodape = ("<footer><strong>Como este Radar é feito</strong><ul>"
              "<li>Notícias públicas coletadas por busca, sem repetir o que já foi enviado antes.</li>"
              "<li>Cardápios lidos das fotos que você nos envia; a comparação é feita item a item.</li>"
              "<li>Cada linha traz a fonte e a data. Nada aqui é escrito por inteligência artificial.</li>"
              "</ul><strong>O que este Radar não cobre</strong><ul>"
              + "".join(f"<li>{escape(l)}</li>" for l in radar["nao_coberto"]) + "</ul></footer>")
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Radar · {escape(radar["cliente_nome"])}</title><style>{ESTILO}</style></head>'
            f'<body><div class="folha"><header>{cabecalho}</header>{avisos}{miolo}{rodape}</div></body></html>')


def salvar_html(radar: dict, pasta=None) -> Path:
    pasta = Path(pasta or PASTA_RELATORIOS)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"radar_{radar['cliente']}_{radar['periodo_ate']}.html"
    destino.write_text(renderizar_html(radar), encoding="utf-8")
    return destino
