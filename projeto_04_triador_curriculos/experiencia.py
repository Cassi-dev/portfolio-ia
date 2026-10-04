"""
Tempo de experiência a partir dos períodos do currículo. É o que o cosseno não enxerga:
"2 anos de Python" e "10 anos de Python" ficam com vetores quase iguais.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from texto import chave

_MESES = {
    "jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
    "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}
_NOME_MES = r"(?:jan|fev|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|out|oct|nov|dez|dec)[a-z]*"


def _data(sufixo: str) -> str:
    return (
        rf"(?:(?:(?P<mn{sufixo}>{_NOME_MES})\.?\s*(?:/|de|-)?\s*|(?P<mm{sufixo}>0?[1-9]|1[0-2])\s*[/.-]\s*)?"
        rf"(?P<a{sufixo}>(?:19|20)\d{{2}}))"
    )


def _atual(sufixo: str) -> str:
    return rf"(?P<atual{sufixo}>atual(?:mente)?|presente|hoje|current|present|now|ate o momento|em andamento)"


# "2019 - 2022", "2019 - atual" ou "2019 até o momento" (aqui o "até" já faz parte do marcador de período aberto)
_PERIODO = re.compile(
    rf"(?<![\d/])\b{_data('1')}\s*(?:(?:-|a|ate|to|/)\s*(?:{_data('2')}|{_atual('A')})|{_atual('B')})\b(?![\d])"
)
_DECLARADO = re.compile(r"(\d{1,2})\s*\+?\s*anos?\s+de\s+experiencia")


@dataclass
class ResultadoExperiencia:
    meses: int = 0
    intervalos: list = field(default_factory=list)      # [(indice_mes_inicio, indice_mes_fim)]
    fonte: str = "nenhuma"                              # "periodos" | "declarado" | "nenhuma"

    @property
    def anos(self) -> float:
        return round(self.meses / 12, 1)


def _mes(nome, numero):
    if nome:
        return _MESES.get(nome[:3])
    return int(numero) if numero else None


def _indice(ano: int, mes: int) -> int:
    return ano * 12 + mes - 1


def calcular_experiencia(texto: str, hoje: date | None = None) -> ResultadoExperiencia:
    """
    Soma os meses de todos os períodos (sem contar a mesma época duas vezes). Data só com ano é tratada
    de forma conservadora: começo em julho e fim em junho ("2018 - 2021" = 3 anos). Períodos "até hoje"
    usam a data de referência. Se não houver nenhum período, usa "N anos de experiência" quando declarado.
    """
    hoje = hoje or date.today()
    t = chave(texto).replace("–", "-").replace("—", "-")
    intervalos = []

    for m in _PERIODO.finditer(t):
        ano1 = int(m.group("a1"))
        mes1 = _mes(m.group("mn1"), m.group("mm1"))
        inicio = _indice(ano1, mes1 or 7)

        if m.group("atualA") or m.group("atualB"):
            fim = _indice(hoje.year, hoje.month)
        else:
            ano2 = int(m.group("a2"))
            mes2 = _mes(m.group("mn2"), m.group("mm2"))
            fim = _indice(ano2, mes2 or 6)
            if not mes1 and not mes2 and ano2 == ano1:
                fim = inicio + 5                         # "2019 - 2019": no mínimo 6 meses
        if fim < inicio or fim > _indice(hoje.year, hoje.month) + 1 or ano1 < 1970:
            continue                                     # período impossível (fim antes do início ou no futuro)
        intervalos.append((inicio, fim))

    if intervalos:
        intervalos.sort()
        unidos = [list(intervalos[0])]
        for ini, fim in intervalos[1:]:
            if ini <= unidos[-1][1] + 1:
                unidos[-1][1] = max(unidos[-1][1], fim)
            else:
                unidos.append([ini, fim])
        meses = sum(f - i + 1 for i, f in unidos)
        return ResultadoExperiencia(meses=meses, intervalos=[tuple(u) for u in unidos], fonte="periodos")

    declarados = [int(n) for n in _DECLARADO.findall(t)]
    if declarados:
        return ResultadoExperiencia(meses=max(declarados) * 12, fonte="declarado")
    return ResultadoExperiencia()
