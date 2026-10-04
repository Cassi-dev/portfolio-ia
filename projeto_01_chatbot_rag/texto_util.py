"""Normalização de texto para comparar e procurar (minúsculo, sem acento, espaços colapsados)."""
import re
import unicodedata


def chave(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def sem_cabecalho(texto: str, secao: str = "") -> str:
    """Tira do bloco a primeira linha "Documento > Seção" que a indexação contextual acrescenta (a tela já mostra a fonte)."""
    primeira, separador, resto = texto.partition("\n")
    if separador and secao and primeira.rstrip().endswith(f"> {secao}"):
        return resto.strip()
    return texto


def como_citacao(texto: str) -> str:
    """
    Bloco de citação em Markdown que preserva as quebras de linha (cada linha ganha o seu '> ').
    O divisor de frases junta as linhas do bloco com espaço, então "... prazo. - Após ..." volta a ser item de lista.
    """
    texto = re.sub(r"(?<=[.;:!?]) - (?=[A-ZÀ-ÚÇ0-9])", "\n- ", texto.strip())
    return "\n".join("> " + linha if linha.strip() else ">" for linha in texto.splitlines())
