"""Textos padrão do "modo degradado": o que dizer ao usuário quando um resultado não veio da IA."""

from core import cota

MOTIVO_SEM_CHAVE = "sem chave de API: conteúdo gerado por regras simples, não por IA"
MOTIVO_FORMATO = "a IA respondeu fora do formato esperado"


def motivo_falha(erro) -> str:
    """Erro de cota vira instrução do que fazer; o resto continua mostrando o erro, encurtado."""
    if getattr(erro, "amigavel", False):
        return str(erro)                       # já escrito para o usuário: não embrulhar nem cortar
    if explicacao := cota.explicar(erro):
        return explicacao
    return f"falha na chamada da IA ({str(erro)[:140]})"
