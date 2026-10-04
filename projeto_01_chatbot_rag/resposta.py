"""
Resposta com citações verificáveis e pergunta de continuação.

A IA responde em formato estruturado e copia, para cada afirmação, a frase exata do trecho que a sustenta.
O sistema confere se essa frase existe mesmo no trecho citado. Resposta cuja citação não confere NÃO é mostrada
como resposta: a interface mostra o trecho original e avisa. Isso não prova que a resposta está certa, mas pega a
invenção mais comum (citar o que o documento não diz).
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from core.degradacao import MOTIVO_FORMATO, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado
from seguranca_rag import montar_prompt_rag
from texto_util import chave

MENSAGEM_SEM_BASE = "Não encontrei essa informação nos documentos."
LIMIAR_CITACAO = 0.85


class Citacao(BaseModel):
    trecho: int = Field(ge=1, description="Número do trecho citado")
    texto_literal: str = Field(min_length=3, max_length=300, description="Frase copiada EXATAMENTE do trecho")


class RespostaRAG(BaseModel):
    suficiente: bool = Field(description="False se os trechos não bastam para responder")
    resposta: str = Field(description="Resposta curta, com marcadores [n] junto de cada afirmação")
    citacoes: list[Citacao] = Field(max_length=6)


class PerguntaIndependente(BaseModel):
    pergunta: str = Field(description="A pergunta reescrita para fazer sentido sozinha, sem depender da conversa")


def _numeros(texto: str) -> set:
    return set(re.findall(r"\d+(?:[.,]\d+)?", texto))


def citacao_confere(citacao: str, texto: str) -> bool:
    """
    A citação está no texto? Ignora acento, caixa e espaços e tolera pequenas variações (>= 85% casado).
    Um NÚMERO que não exista no texto reprova sempre: trocar "7 dias" por "30 dias" mantém a frase quase igual
    e é justamente o erro que importa pegar.
    """
    c, t = chave(citacao), chave(texto)
    if not c or not _numeros(c) <= _numeros(t):
        return False
    if c in t:
        return True
    blocos = SequenceMatcher(None, t, c, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocos if b.size >= 4) / len(c) >= LIMIAR_CITACAO


@dataclass
class ResultadoResposta:
    status: str                                  # "respondida" | "sem_base" | "nao_verificada" | "falhou"
    texto: str = ""
    citacoes_verificadas: int = 0
    citacoes_total: int = 0
    trechos_suspeitos: list = field(default_factory=list)
    motivo: str = ""


def responder_com_citacoes(client, pergunta: str, trechos: list) -> ResultadoResposta:
    prompt, suspeitos = montar_prompt_rag(pergunta, trechos)
    try:
        r = gerar_estruturado(client, prompt, RespostaRAG, temperatura=0.1)
    except RespostaInvalida:
        return ResultadoResposta("falhou", trechos_suspeitos=suspeitos, motivo=MOTIVO_FORMATO)
    except FalhaLLM as e:
        return ResultadoResposta("falhou", trechos_suspeitos=suspeitos, motivo=motivo_falha(e))

    if not r.suficiente:
        return ResultadoResposta("sem_base", MENSAGEM_SEM_BASE, trechos_suspeitos=suspeitos)

    verificadas = sum(1 for c in r.citacoes if c.trecho <= len(trechos) and citacao_confere(c.texto_literal, trechos[c.trecho - 1].texto))
    total = len(r.citacoes)
    if verificadas == 0:
        return ResultadoResposta("nao_verificada", r.resposta, 0, total, suspeitos,
                                 "nenhuma citação da IA foi encontrada nos trechos" if total else "a IA não citou nenhum trecho")
    return ResultadoResposta("respondida", r.resposta, verificadas, total, suspeitos)


def reescrever_pergunta(client, historico: list, pergunta: str):
    """
    Transforma "e depois disso?" em uma pergunta completa, usando as últimas mensagens.
    Devolve (pergunta, reescreveu, motivo_da_falha). Sem histórico ou sem IA, devolve a pergunta como veio.
    """
    if client is None or not historico:
        return pergunta, False, ""
    conversa = "\n".join(f"{m['role']}: {' '.join(m['content'].split())[:400]}" for m in historico[-6:])
    prompt = (
        "Reescreva a última pergunta do usuário para que ela faça sentido sozinha, resolvendo pronomes e referências à "
        "conversa. Não responda a pergunta e não acrescente informações. Se ela já faz sentido sozinha, devolva igual.\n\n"
        f"CONVERSA:\n{conversa}\n\nÚLTIMA PERGUNTA: {pergunta}"
    )
    try:
        nova = gerar_estruturado(client, prompt, PerguntaIndependente, temperatura=0.0).pergunta.strip()
    except (RespostaInvalida, FalhaLLM) as e:
        return pergunta, False, str(e)
    return (nova, nova != pergunta, "") if nova else (pergunta, False, "")
