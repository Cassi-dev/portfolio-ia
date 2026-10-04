"""Utilidades de texto e extração de PDF."""
import re
import unicodedata


class PDFSemTexto(Exception):
    """PDF sem camada de texto (provavelmente escaneado): este projeto não faz OCR."""


def sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def chave(texto: str) -> str:
    """Minúsculo, sem acentos e com espaços colapsados: para comparar e procurar."""
    return re.sub(r"\s+", " ", sem_acentos(texto).lower()).strip()


def normalizar_texto(texto: str) -> str:
    texto = texto.replace(" ", " ").replace("\r", "\n")
    texto = re.sub(r"[•●▪◦■►➢✓]", "-", texto)
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)          # palavra hifenizada na quebra de linha
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def extrair_texto_pdf(origem) -> str:
    """`origem` é um caminho ou os bytes do PDF."""
    import pymupdf
    doc = pymupdf.open(stream=bytes(origem), filetype="pdf") if isinstance(origem, (bytes, bytearray, memoryview)) else pymupdf.open(origem)
    with doc:
        texto = "\n".join(pagina.get_text("text", sort=True) for pagina in doc)
    texto = normalizar_texto(texto)
    if len(texto) < 40:
        raise PDFSemTexto("PDF sem texto extraível (escaneado?).")
    return texto
