"""A vaga: requisitos obrigatórios (filtro), desejáveis (peso), anos mínimos e formação mínima."""
import re
from typing import Literal

from pydantic import BaseModel, Field

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado
from formacao import NIVEIS, nivel_formacao
from texto import chave

Nivel = Literal["nenhuma", "medio", "tecnico", "graduacao", "pos", "mestrado", "doutorado"]


class VagaExtraida(BaseModel):
    titulo: str
    requisitos_obrigatorios: list[str] = Field(
        description="Um requisito por item, curto (ex.: 'Python', 'SQL', 'APIs REST'). Só o que a vaga trata como indispensável; "
                    "não inclua anos de experiência nem formação aqui."
    )
    requisitos_desejaveis: list[str] = Field(description="Diferenciais, 'desejável' ou 'nice to have'")
    anos_experiencia_minimos: int = Field(ge=0, le=40, description="0 se a vaga não exige um mínimo")
    formacao_minima: Nivel = Field(description="'nenhuma' se a vaga não exige")


class Vaga(VagaExtraida):
    descricao: str = ""


_OBRIGATORIOS = re.compile(r"^(requisitos?( obrigatorios?| minimos?| essenciais)?|obrigatorios?|must[- ]have|qualificacoes( obrigatorias)?|voce precisa ter)$")
_DESEJAVEIS = re.compile(r"^(requisitos desejaveis|desejav(?:el|eis)|diferenciais?|nice[- ]to[- ]have|sera um diferencial|bonus)$")
_TITULO_DE_BLOCO = re.compile(r"^[^:]{2,50}:\s*$")
_MARCADOR = re.compile(r"^(?:[\s\-*•·▪–—>]+|\d+[.)]\s+)+")
_ANOS = re.compile(r"(\d{1,2})\s*\+?\s*anos?\b")


def _itens(linhas) -> list[str]:
    itens = []
    for parte in re.split(r"[;\n]|,(?![^(]*\))", "\n".join(linhas)):
        parte = _MARCADOR.sub("", parte).strip(" .")
        if parte:
            itens.append(parte)
    return itens


def _separar_blocos(texto: str) -> dict:
    blocos = {"obrigatorio": [], "desejavel": []}
    atual = None
    for linha in texto.splitlines():
        cabecalho, dois_pontos, resto = linha.partition(":")
        c = chave(cabecalho)
        if dois_pontos and _OBRIGATORIOS.match(c):
            atual = "obrigatorio"
            blocos[atual].append(resto)
        elif dois_pontos and _DESEJAVEIS.match(c):
            atual = "desejavel"
            blocos[atual].append(resto)
        elif _TITULO_DE_BLOCO.match(linha.strip()) and not linha.strip().startswith(("-", "*", "•")):
            atual = None                                     # "Responsabilidades:", "Benefícios:" etc.
        elif atual and linha.strip():
            blocos[atual].append(linha)
    return blocos


def extrair_vaga_por_regras(texto: str) -> Vaga:
    """Lê os blocos 'Requisitos obrigatórios' e 'Desejável/Diferenciais'. Anos e formação viram campos próprios."""
    titulo = next((_MARCADOR.sub("", l).strip() for l in texto.splitlines() if l.strip()), "Vaga")
    titulo = re.sub(r"^vaga\s*:\s*", "", titulo, flags=re.I)

    blocos = _separar_blocos(texto)
    anos, formacao, obrigatorios = 0, "nenhuma", []
    for item in _itens(blocos["obrigatorio"]):
        c = chave(item)
        achou_anos = _ANOS.search(c)
        if achou_anos and "experiencia" in c:
            anos = max(anos, int(achou_anos.group(1)))
        elif nivel_formacao(item) != "nenhuma":
            formacao = max(formacao, nivel_formacao(item), key=NIVEIS.index)
        else:
            obrigatorios.append(item)

    if not anos:
        m = re.search(r"(\d{1,2})\s*\+?\s*anos?\s+de\s+experiencia", chave(texto))
        anos = int(m.group(1)) if m else 0

    return Vaga(
        titulo=titulo, requisitos_obrigatorios=obrigatorios, requisitos_desejaveis=_itens(blocos["desejavel"]),
        anos_experiencia_minimos=min(anos, 40), formacao_minima=formacao, descricao=texto.strip(),
    )


def extrair_vaga(texto: str, client=None):
    """(Vaga, degradado, motivo). Com IA ela lê a vaga; sem, ou se falhar, usam-se as regras. O usuário revisa depois."""
    motivo = MOTIVO_SEM_CHAVE
    if client is not None:
        prompt = (
            "Extraia os requisitos desta descrição de vaga. Obrigatório é só o que a vaga trata como indispensável; "
            "'desejável', 'diferencial' e 'nice to have' vão em desejáveis. Um requisito por item, curto, sem inventar.\n\n"
            f"VAGA:\n{texto}"
        )
        try:
            extraida = gerar_estruturado(client, prompt, VagaExtraida, temperatura=0.0)
            return Vaga(**extraida.model_dump(), descricao=texto.strip()), False, None
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)
    return extrair_vaga_por_regras(texto), True, motivo
