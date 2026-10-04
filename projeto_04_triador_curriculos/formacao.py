"""Nível de formação: maior nível concluído citado no currículo."""
import re

from texto import chave

NIVEIS = ["nenhuma", "medio", "tecnico", "graduacao", "pos", "mestrado", "doutorado"]
PONTOS = {"nenhuma": 20, "medio": 40, "tecnico": 55, "graduacao": 75, "pos": 90, "mestrado": 100, "doutorado": 100}

_PADROES = [
    ("doutorado", r"\bdoutorado\b|\bphd\b|\bph\.d\b"),
    ("mestrado", r"\bmestrado\b|\bmaster of\b|\bmsc\b"),
    ("pos", r"\bpos[- ]?graduacao\b|\bespecializacao\b|\bmba\b|\bpost[- ]?graduate\b"),
    ("graduacao", r"\bgraduacao\b|\bbacharel\w*\b|\blicenciatura\b|\btecnologo\b|\bensino superior\b|\bsuperior completo\b|\bbachelor\b"),
    ("tecnico", r"\btecnico\b|\bcurso tecnico\b|\btechnical\b"),
    ("medio", r"\bensino medio\b|\bsegundo grau\b|\bhigh school\b"),
]
_NAO_CONCLUIDO = re.compile(r"cursando|em andamento|incompleto|trancado|previsao|prevista|\bem curso\b|ongoing|expected")


def nivel_formacao(texto: str) -> str:
    """Ignora linhas de curso em andamento ou incompleto."""
    melhor = 0
    for linha in texto.splitlines():
        t = chave(linha)
        if not t or _NAO_CONCLUIDO.search(t):
            continue
        for nivel, padrao in _PADROES:
            if re.search(padrao, t):
                melhor = max(melhor, NIVEIS.index(nivel))
                break
    return NIVEIS[melhor]


def atende_formacao(nivel: str, minimo: str) -> bool:
    return NIVEIS.index(nivel) >= NIVEIS.index(minimo)
