"""
Estrutura do documento: título e seções. É o que permite guardar a *seção* como metadado (o e-book pede
arquivo, página e seção) e escrever, no início de cada bloco, "Documento > Seção", que dá contexto ao bloco
na hora da busca (a ideia por trás do "contextual retrieval").
"""
import re
import unicodedata

_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_SECAO_NUMERADA = re.compile(r"^(?:se[cç][aã]o|cap[ií]tulo|artigo|art\.)\s*\d+\s*[:.\-–]?\s*(.*)$", re.I)
_NUMERADO = re.compile(r"^\d{1,2}(?:\.\d{1,2})*[.)]?\s+\S")
_PONTUACAO_FINAL = re.compile(r"[.,;:!?]$")


def _sem_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _e_caixa_alta(linha: str) -> bool:
    letras = [c for c in linha if c.isalpha()]
    return len(letras) >= 3 and all(c.isupper() for c in letras)


def classificar_linha(linha: str, linha_anterior_vazia: bool, proxima_e_item: bool = False):
    """
    ('h1' | 'titulo', texto) se a linha parece um título; senão None.
    `proxima_e_item`: a linha seguinte também é um item numerado ou com marcador (então isto é uma lista, não um título).
    """
    bruta = linha.strip()
    if not bruta or len(bruta) > 90:
        return None
    m = _MD.match(bruta)
    if m:
        return ("h1" if len(m.group(1)) == 1 else "titulo", m.group(2).strip())
    if not linha_anterior_vazia or len(bruta) > 70 or _PONTUACAO_FINAL.search(bruta):
        return None
    if _SECAO_NUMERADA.match(bruta) or _e_caixa_alta(bruta):
        return ("titulo", bruta.capitalize() if _e_caixa_alta(bruta) else bruta)
    if _NUMERADO.match(bruta) and len(bruta.split()) <= 8 and not proxima_e_item:
        return ("titulo", bruta)
    return None


def _e_item_de_lista(linha: str) -> bool:
    bruta = linha.strip()
    return bool(_NUMERADO.match(bruta) or re.match(r"^[-*•]\s+\S", bruta))


def titulo_do_documento(texto: str, nome_arquivo: str) -> str:
    """Primeiro '# Título'; senão a primeira linha curta; senão o nome do arquivo, arrumado."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    for linha in linhas[:8]:
        m = _MD.match(linha)
        if m and len(m.group(1)) == 1:
            return m.group(2)
    if linhas and len(linhas[0]) <= 80 and not _PONTUACAO_FINAL.search(linhas[0]):
        return linhas[0].lstrip("# ").strip()
    base = re.sub(r"\.[A-Za-z0-9]{2,4}(\.[A-Za-z0-9]{2,4})?$", "", nome_arquivo)
    return re.sub(r"[_\-]+", " ", base).strip().capitalize()


def dividir_em_secoes(texto: str, secao_inicial: str = ""):
    """
    [(título_da_seção, texto)] em ordem. O título do documento (`# ...`) não é seção.
    `secao_inicial` continua a seção da página anterior, quando o texto vem de um PDF paginado.
    """
    secoes, atual, corpo = [], secao_inicial, []
    anterior_vazia = True

    def fechar():
        texto_corpo = "\n".join(corpo).strip()
        if texto_corpo:
            secoes.append((atual, texto_corpo))

    linhas = texto.splitlines()
    for indice, linha in enumerate(linhas):
        seguinte = next((l for l in linhas[indice + 1:] if l.strip()), "")
        achado = classificar_linha(linha, anterior_vazia, _e_item_de_lista(seguinte))
        if achado and achado[0] == "h1":
            pass
        elif achado:
            fechar()
            corpo, atual = [], achado[1]
        elif linha.strip():
            corpo.append(linha)
        anterior_vazia = not linha.strip()
    fechar()
    return secoes


def resumo_estrutural(titulo: str, primeira_parte: str, secoes: list) -> str:
    """Parágrafo de abertura + lista de seções: responde 'do que trata este documento?' sem precisar de IA."""
    abertura = " ".join(primeira_parte.split())[:300]
    nomes = []
    for s in secoes:
        if s and s not in nomes:
            nomes.append(s)
    partes = [f"Documento: {titulo}."]
    if abertura:
        partes.append(abertura)
    if nomes:
        partes.append("Seções: " + "; ".join(nomes) + ".")
    return " ".join(partes)
