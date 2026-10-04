"""
Currículo é dado pessoal (LGPD). Tudo é analisado localmente; só o que vai para a API de um LLM passa
por aqui antes: contatos e documentos são trocados por marcadores, e o nome vira "[CANDIDATO]".
"""
import re

_PADROES = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("[CPF]", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("[TELEFONE]", re.compile(r"(?:\+?55\s?)?(?:\(\d{2}\)\s?|\b\d{2}\s)9?\d{4}[-\s]?\d{4}\b")),
    ("[LINK]", re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github)\.com/\S+", re.I)),
    ("[CEP]", re.compile(r"\b\d{5}-\d{3}\b")),
]
_NOME = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ'’-]+(?:\s+(?:d[aeo]s?|e|[A-ZÀ-Ý][a-zà-ÿ'’-]+)){1,5}$")


def extrair_nome(texto: str, alternativa: str = "Candidato") -> str:
    """Primeira linha que parece um nome próprio (2 a 6 palavras, só letras); senão, `alternativa`."""
    for linha in texto.splitlines()[:6]:
        linha = linha.strip()
        if _NOME.match(linha):
            return linha
    return alternativa


def redigir_pii(texto: str, nome: str | None = None) -> str:
    for marcador, padrao in _PADROES:
        texto = padrao.sub(marcador, texto)
    if nome and len(nome) > 3:
        texto = re.sub(re.escape(nome), "[CANDIDATO]", texto, flags=re.I)
        for parte in nome.split():
            if len(parte) > 3:
                texto = re.sub(rf"\b{re.escape(parte)}\b", "[CANDIDATO]", texto, flags=re.I)
    return texto
