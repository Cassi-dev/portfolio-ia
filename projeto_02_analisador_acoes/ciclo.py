"""
Um ciclo do monitor: coleta -> guarda só o que é novo -> pontua só o que ainda não tem score -> detecta o que mudou.

A ordem importa para o custo. Antes, cada execução mandava o lote inteiro de manchetes para a IA (o cache é da
chamada toda, então uma manchete nova repagava as outras ~100). Aqui a IA só vê o que entrou agora.

O resumo devolvido já é o material do relatório (ponto 3): nada de imprimir ou formatar aqui.
"""
from datetime import datetime, timedelta, timezone

from analise_sentimento import pontuar_sentimento_llm
from cardapio import comparar, houve_mudanca
from coleta_noticias import coletar_por_termos
from deteccao import analisar_alvo, merece_alerta

TAMANHO_LOTE = 60          # manchetes por chamada da IA: prompt grande demais piora a qualidade e arrisca o limite
CAMPOS_DO_RELATORIO = ("id", "titulo", "data", "fonte", "link", "score", "classificacao", "motor", "gatilho")


def coletar_do_alvo(alvo, limite_dias: int) -> list:
    return coletar_por_termos(alvo.termos, alvo.tema, limite_dias, alvo.regiao)


def _resumir(evento: dict) -> dict:
    return {campo: evento[campo] for campo in CAMPOS_DO_RELATORIO if campo in evento}


def pontuar_pendentes(base, cliente_id: str, client_llm=None, lote: int = TAMANHO_LOTE) -> dict:
    """Pontua o que está sem score (inclusive sobras de ciclos anteriores que falharam) e grava."""
    pendentes = base.sem_pontuacao(cliente_id)
    gravados, motores = 0, {}
    for inicio in range(0, len(pendentes), lote):
        fatia = pendentes[inicio:inicio + lote]
        pontuar_sentimento_llm(fatia, client=client_llm)
        gravados += base.gravar_pontuacoes(fatia)
        for item in fatia:
            motor = item.get("motor", "desconhecido")
            motores[motor] = motores.get(motor, 0) + 1
    return {"pendentes": len(pendentes), "pontuados": gravados, "motores": motores,
            "motivos_degradado": sorted({i["motivo_motor"] for i in pendentes
                                         if i.get("motor") == "lexico" and i.get("motivo_motor")})}


def diferenca_de_cardapio(base, cliente_id: str, alvo_id: str, desde: str = None):
    """
    Compara as duas capturas mais recentes do cardápio do alvo. None quando ainda não há duas.
    `nova` diz se a captura mais recente entrou depois do ciclo anterior — é o que evita repetir o mesmo
    alerta toda semana enquanto ninguém manda foto nova.
    """
    capturas = base.capturas(cliente_id, alvo_id, limite=2)
    if len(capturas) < 2:
        return None
    atual, anterior = capturas[0], capturas[1]
    diferenca = comparar(base.itens_da_captura(anterior["id"]), base.itens_da_captura(atual["id"]))
    return {**diferenca, "de": anterior["data"], "para": atual["data"],
            "nova": desde is None or atual["criado_em"] > desde}


def rodar_ciclo(cliente, base, client_llm=None, coletor=None, hoje=None, lote: int = TAMANHO_LOTE,
                deduplicador=None) -> dict:
    """
    `coletor(alvo, dias) -> list` é injetável para testar sem rede; `deduplicador` idem (o padrão por palavras
    é rápido, mas mede 0 de 21 em repetição real — a linha de comando passa o de embedding).
    """
    coletor = coletor or coletar_do_alvo
    hoje = hoje or datetime.now(timezone.utc).date()
    anteriores = base.ciclos(cliente.id, limite=1)
    desde = anteriores[0]["inicio"] if anteriores else None
    ciclo_id = base.abrir_ciclo(cliente.id)
    primeira_coleta = base.quantos_ciclos(cliente.id) == 1
    observando_desde = base.observando_desde(cliente.id)

    coletados, novos, erros = 0, 0, []
    for alvo in cliente.alvos:
        try:
            itens = coletor(alvo, cliente.janela_dias)
        except Exception as erro:                       # uma fonte fora do ar não pode derrubar o ciclo inteiro
            erros.append(f"{alvo.id}: {type(erro).__name__}: {erro}")
            continue
        coletados += len(itens)
        novos += len(base.registrar_eventos(cliente.id, alvo.id, "noticia", itens, ciclo_id, hoje=hoje,
                                            deduplicador=deduplicador))

    pontuacao = pontuar_pendentes(base, cliente.id, client_llm, lote)
    base.fechar_ciclo(ciclo_id, coletados, novos, pontuacao["pontuados"], erros)

    motivos = list(pontuacao["motivos_degradado"])
    if cliente.perfil == "negocio" and pontuacao["motores"].get("lexico"):
        motivos.append("o léxico foi escrito para manchete financeira: em notícia de restaurante ele devolve "
                       "quase sempre 0,00, então o sentimento sem chave de API não diz muita coisa")

    janela_desde = hoje - timedelta(days=cliente.janela_dias)
    por_alvo = []
    for alvo in cliente.alvos:
        analise = analisar_alvo(base.eventos(cliente.id, alvo_id=alvo.id, desde=janela_desde), ciclo_id, hoje,
                                cliente.gatilhos, observando_desde=observando_desde, primeira_coleta=primeira_coleta)
        # cardápio não sofre o viés do RSS: as duas capturas são atos deliberados, então alertam mesmo na 1ª coleta
        cardapio = diferenca_de_cardapio(base, cliente.id, alvo.id, desde)
        alerta_cardapio = bool(cardapio and cardapio["nova"] and houve_mudanca(cardapio))
        por_alvo.append({
            "alvo": alvo.id, "nome": alvo.nome, "papel": alvo.papel,
            "total_na_base": analise["total_na_base"], "novos": analise["novos"], "sinal": analise["sinal"],
            "pico": analise["pico"], "virada": analise["virada"],
            "alerta": merece_alerta(analise) or alerta_cardapio, "cardapio": cardapio,
            "novidades": [_resumir(e) for e in analise["novidades"]],
            "gatilhos": [_resumir(e) for e in analise["gatilhos"]],
        })

    return {
        "cliente": cliente.id, "cliente_nome": cliente.nome, "perfil": cliente.perfil,
        "ciclo_id": ciclo_id, "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "referencia": hoje.isoformat(), "janela_dias": cliente.janela_dias,
        "primeira_coleta": primeira_coleta, "observando_desde": observando_desde.isoformat() if observando_desde else None,
        "coletados": coletados, "novos": novos, "pontuados": pontuacao["pontuados"],
        "motores": pontuacao["motores"], "motivos_degradado": motivos,
        "com_alerta": [a["alvo"] for a in por_alvo if a["alerta"]],
        "por_alvo": por_alvo, "erros": erros,
    }
