"""
Detectores do monitor: o que mudou desde a última vez.

São funções puras sobre listas de eventos já guardados — nada de banco nem de rede aqui —, para serem testadas
com listas escritas à mão. Um evento é um dict com pelo menos: data (ISO), titulo, score (ou None) e ciclo_id.

Os limiares abaixo são CHUTES INICIAIS, não números medidos. A taxa de alarme falso só existe depois de rotular
eventos à mão (ponto 4 do plano). Todos são parâmetros, para ajustar sem mexer no código.
"""
import re
import unicodedata
from datetime import date, timedelta

# Palavras que sozinhas justificam um alerta, mesmo sem pico nem virada de sentimento.
GATILHOS_NEGOCIO = [
    "recuperacao judicial", "falencia", "interdicao", "interditado", "fechamento", "fechou as portas",
    "intoxicacao", "vigilancia sanitaria", "fiscalizacao", "multa", "processo", "denuncia",
    "inauguracao", "inaugura", "nova unidade", "abre filial", "reforma", "mudanca de endereco",
]
GATILHOS_ACAO = [
    "investigacao", "recuperacao judicial", "fusao", "aquisicao", "oferta publica", "rebaixamento",
    "delacao", "cvm", "fato relevante", "dividendo extraordinario", "mudanca de comando",
]

MEIA_VIDA_PADRAO = 5
DIAS_ALERTA = 7            # gatilho em notícia de 25 dias atrás não é alerta, é histórico
DIAS_MINIMOS_OBSERVADOS = 14


def normalizar(texto: str) -> str:
    """Minúsculo, sem acento, espaços colapsados. Usado para casar gatilho e para a identidade do evento."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", str(texto)) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _data(evento) -> date:
    return date.fromisoformat(evento["data"])


def janela(eventos: list, fim: date, dias: int) -> list:
    """Eventos com fim - dias < data <= fim (janela fechada à direita, para não contar o mesmo dia duas vezes)."""
    inicio = fim - timedelta(days=dias)
    return [e for e in eventos if inicio < _data(e) <= fim]


def novidades(eventos: list, ciclo_id: int) -> list:
    """O que entrou na base NESTE ciclo. É a linha "o que mudou" do relatório."""
    return [e for e in eventos if e.get("ciclo_id") == ciclo_id]


def sinal_ponderado(eventos: list, hoje: date, meia_vida_dias: int = MEIA_VIDA_PADRAO):
    """
    Média dos scores com peso 0,5 ^ (idade / meia-vida): notícia velha quase não conta.
    None quando nenhum evento tem score. Mesma ideia de analise_sentimento, mas com `hoje` explícito (testável).
    """
    com_score = [e for e in eventos if e.get("score") is not None]
    if not com_score:
        return None
    pesos = [0.5 ** (max(0, (hoje - _data(e)).days) / meia_vida_dias) for e in com_score]
    total = sum(pesos)
    if total == 0:
        return None
    return round(sum(e["score"] * p for e, p in zip(com_score, pesos)) / total, 3)


def pico_de_volume(eventos: list, hoje: date, dias: int = 7, base_dias: int = 28, razao_minima: float = 2.0,
                   minimo_absoluto: int = 3, observando_desde: date = None,
                   dias_minimos: int = DIAS_MINIMOS_OBSERVADOS) -> dict:
    """
    Está se falando mais do alvo do que o normal? Compara a contagem da janela recente com a média das janelas
    anteriores (mesmo tamanho). O mínimo absoluto evita o falso pico de "1 notícia contra 0,2 de média".

    `observando_desde` é o que impede o pico falso da primeira coleta: o RSS devolve muito mais notícia recente
    do que antiga, então o histórico que vem de uma primeira busca NÃO é linha de base — ele só vira comparável
    depois de alguns dias observando de verdade. A média é calculada sobre o período realmente observado.
    """
    recentes = janela(eventos, hoje, dias)
    fim_base = hoje - timedelta(days=dias)
    anteriores = janela(eventos, fim_base, base_dias)

    dias_observados, comparavel = base_dias, True
    if observando_desde is not None:
        inicio_base = fim_base - timedelta(days=base_dias)
        dias_observados = (fim_base - max(inicio_base, observando_desde)).days
        comparavel = (hoje - observando_desde).days >= dias_minimos and dias_observados >= dias

    media = len(anteriores) / (dias_observados / dias) if comparavel and dias_observados >= dias else 0.0
    razao = round(len(recentes) / media, 2) if media > 0 else None
    e_pico = bool(comparavel and len(recentes) >= minimo_absoluto and (razao is None or razao >= razao_minima))
    return {"n_recente": len(recentes), "media_anterior": round(media, 2), "razao": razao,
            "comparavel": comparavel, "e_pico": e_pico}


def virada_de_sentimento(eventos: list, hoje: date, dias: int = 7, delta_minimo: float = 0.30,
                         minimo_por_janela: int = 3) -> dict:
    """
    O humor sobre o alvo mudou de direção? Compara a média simples de score da janela atual com a anterior.
    Exige um mínimo de eventos nas duas janelas: com 1 notícia de cada lado, qualquer delta é ruído.
    """
    def media(itens):
        com_score = [e["score"] for e in itens if e.get("score") is not None]
        return (round(sum(com_score) / len(com_score), 3), len(com_score)) if com_score else (None, 0)

    atual, n_atual = media(janela(eventos, hoje, dias))
    anterior, n_anterior = media(janela(eventos, hoje - timedelta(days=dias), dias))
    comparavel = n_atual >= minimo_por_janela and n_anterior >= minimo_por_janela
    delta = round(atual - anterior, 3) if comparavel else None
    return {
        "atual": atual, "anterior": anterior, "n_atual": n_atual, "n_anterior": n_anterior,
        "delta": delta, "virou": bool(delta is not None and abs(delta) >= delta_minimo),
    }


def gatilhos(eventos: list, palavras: list) -> list:
    """Eventos cujo título contém alguma palavra-gatilho. Devolve o evento com a palavra que casou."""
    normalizadas = [(p, normalizar(p)) for p in palavras if str(p).strip()]
    achados = []
    for evento in eventos:
        titulo = normalizar(evento.get("titulo", ""))
        casou = next((original for original, chave in normalizadas if chave in titulo), None)
        if casou:
            achados.append({**evento, "gatilho": casou})
    return achados


def analisar_alvo(eventos: list, ciclo_id: int, hoje: date, palavras_gatilho: list,
                  meia_vida_dias: int = MEIA_VIDA_PADRAO, observando_desde: date = None,
                  primeira_coleta: bool = False, dias_alerta: int = DIAS_ALERTA) -> dict:
    """Junta os detectores de um alvo. Os gatilhos olham só as novidades recentes: um alerta por evento, uma vez só."""
    novos = novidades(eventos, ciclo_id)
    return {
        "total_na_base": len(eventos),
        "novos": len(novos),
        "novidades": novos,
        "primeira_coleta": primeira_coleta,
        "sinal": sinal_ponderado(eventos, hoje, meia_vida_dias),
        "pico": pico_de_volume(eventos, hoje, observando_desde=observando_desde),
        "virada": virada_de_sentimento(eventos, hoje),
        "gatilhos": gatilhos(janela(novos, hoje, dias_alerta), palavras_gatilho),
    }


def merece_alerta(analise: dict) -> bool:
    """
    Vale interromper o cliente fora do relatório? Só pico, virada ou gatilho — novidade sozinha não.
    Na primeira coleta nada é alerta: ali tudo é novo por definição, porque a base estava vazia.
    """
    if analise.get("primeira_coleta"):
        return False
    return bool(analise["gatilhos"]) or analise["pico"]["e_pico"] or analise["virada"]["virou"]
