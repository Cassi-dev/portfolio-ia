"""
Indexação dos documentos (única implementação, usada pelo script e pelo app).

- blocos que respeitam frases (nunca cortam uma palavra ao meio) e têm sobreposição
- modo "contextual": cada bloco começa com "Documento > Seção" e guarda a seção nos metadados
- ID do bloco = hash do (arquivo, página, texto): reindexar o mesmo arquivo é idempotente
- indexar um arquivo SUBSTITUI o que já havia dele (sem blocos duplicados nem órfãos)
- a sincronização só reindexa o que mudou (hash do arquivo + versão do formato de indexação)
"""
import hashlib
import os
import re

from pypdf import PdfReader

from estrutura import dividir_em_secoes, resumo_estrutural, titulo_do_documento

TAMANHO_CHUNK = 500
SOBREPOSICAO = 75
EXTENSOES = (".pdf", ".txt", ".md")
VERSAO_INDEXACAO = 2                     # sobe quando a forma de indexar muda, para forçar a reindexação


def extrair_paginas(caminho):
    """[(nº da página, texto)] só das páginas com texto nativo. PDF escaneado devolve lista vazia."""
    paginas = []
    if caminho.lower().endswith(".pdf"):
        for numero, pagina in enumerate(PdfReader(caminho).pages, start=1):
            texto = pagina.extract_text() or ""
            if texto.strip():
                paginas.append((numero, texto))
    elif caminho.lower().endswith((".txt", ".md")):
        with open(caminho, "r", encoding="utf-8-sig", errors="ignore") as f:
            texto = f.read()
        if texto.strip():
            paginas.append((1, texto))
    return paginas


def hash_do_arquivo(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()


def _quebrar_por_palavras(texto, tamanho):
    partes, atual = [], ""
    for palavra in texto.split():
        while len(palavra) > tamanho:            # "palavra" gigante (URL, tabela colada): não tem escolha
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(palavra[:tamanho])
            palavra = palavra[tamanho:]
        if atual and len(atual) + 1 + len(palavra) > tamanho:
            partes.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        partes.append(atual)
    return partes


def _cauda(texto, sobreposicao):
    """Últimos ~`sobreposicao` caracteres do bloco, começando numa palavra inteira."""
    if sobreposicao <= 0 or len(texto) <= sobreposicao:
        return ""
    trecho = texto[-sobreposicao:]
    return trecho[trecho.find(" ") + 1:] if " " in trecho else ""


def dividir_em_blocos(texto, tamanho=TAMANHO_CHUNK, sobreposicao=SOBREPOSICAO):
    """Agrupa frases inteiras em blocos de até `tamanho` caracteres, repetindo o final de um no início do próximo."""
    texto = " ".join(texto.split())
    if not texto:
        return []

    unidades = []
    for frase in re.split(r"(?<=[.!?…])\s+", texto):
        unidades.extend([frase] if len(frase) <= tamanho else _quebrar_por_palavras(frase, tamanho))

    blocos, atual = [], ""
    for unidade in unidades:
        if not atual:
            atual = unidade
        elif len(atual) + 1 + len(unidade) <= tamanho:
            atual = f"{atual} {unidade}"
        else:
            blocos.append(atual)
            cauda = _cauda(atual, sobreposicao)
            atual = f"{cauda} {unidade}" if cauda and len(cauda) + 1 + len(unidade) <= tamanho else unidade
    if atual:
        blocos.append(atual)
    return blocos


def id_do_bloco(arquivo, pagina, texto):
    return hashlib.sha1(f"{arquivo}\x1f{pagina}\x1f{texto}".encode("utf-8")).hexdigest()[:20]


def cabecalho(titulo, secao):
    return f"{titulo} > {secao}" if secao else titulo


def montar_blocos(nome_arquivo, paginas, resumo_global=None, tamanho=TAMANHO_CHUNK, sobreposicao=SOBREPOSICAO,
                  modo="contextual", hash_arquivo=""):
    """
    Devolve (documentos, metadados, ids). Blocos idênticos na mesma página aparecem uma vez só.
    modo="plano" reproduz a indexação antiga (sem cabeçalho e sem seção), útil para comparar.
    """
    textos, metas, ids, vistos = [], [], [], set()
    contextual = modo == "contextual"
    titulo = titulo_do_documento(paginas[0][1], nome_arquivo) if paginas else nome_arquivo

    # 1. blocos de detalhe, por seção (a seção continua de uma página para a outra)
    secao_atual, secoes_vistas, primeira_parte = "", [], ""
    detalhes = []
    for numero, texto in paginas:
        partes = dividir_em_secoes(texto, secao_atual) if contextual else [("", texto)]
        for secao, corpo in partes:
            secao_atual = secao or secao_atual
            if contextual and not primeira_parte and not secao:
                primeira_parte = corpo
            secoes_vistas.append(secao)
            for indice, bloco in enumerate(dividir_em_blocos(corpo, tamanho, sobreposicao), start=1):
                detalhes.append((numero, secao, indice, bloco))

    # 2. bloco global: visão geral do documento
    texto_completo = " ".join(t for _, t in paginas)
    if resumo_global:
        resumo = resumo_global
    elif contextual:
        resumo = resumo_estrutural(titulo, primeira_parte or " ".join(texto_completo.split())[:300], secoes_vistas)
    else:
        resumo = " ".join(texto_completo.split())[:600]
    global_texto = f"VISÃO GERAL, RESUMO E CONTEXTO DO DOCUMENTO '{nome_arquivo}':\n{resumo}"
    base_meta = {"versao": VERSAO_INDEXACAO, "hash_arquivo": hash_arquivo}
    identificador = id_do_bloco(nome_arquivo, 0, "contexto_global")
    textos.append(global_texto)
    metas.append({"arquivo": nome_arquivo, "pagina": 1, "bloco": 0, "tipo": "contexto_global", "secao": "", **base_meta})
    ids.append(identificador)
    vistos.add(identificador)

    for numero, secao, indice, bloco in detalhes:
        conteudo = f"{cabecalho(titulo, secao)}\n{bloco}" if contextual else bloco
        identificador = id_do_bloco(nome_arquivo, numero, conteudo)
        if identificador in vistos:
            continue
        vistos.add(identificador)
        textos.append(conteudo)
        metas.append({"arquivo": nome_arquivo, "pagina": numero, "bloco": indice, "tipo": "detalhe", "secao": secao or "", **base_meta})
        ids.append(identificador)
    return textos, metas, ids


def indexar_arquivo(colecao, nome_arquivo, paginas, resumo_global=None, hash_arquivo="", modo="contextual"):
    """Troca tudo que havia do arquivo pelos blocos novos. Devolve quantos blocos foram gravados."""
    textos, metas, ids = montar_blocos(nome_arquivo, paginas, resumo_global, modo=modo, hash_arquivo=hash_arquivo)
    colecao.delete(where={"arquivo": nome_arquivo})
    colecao.upsert(documents=textos, metadatas=metas, ids=ids)
    return len(ids)


def _ja_indexado(colecao, nome, hash_atual):
    achado = colecao.get(where={"arquivo": nome}, include=["metadatas"], limit=1)["metadatas"]
    return bool(achado) and achado[0].get("hash_arquivo") == hash_atual and achado[0].get("versao") == VERSAO_INDEXACAO


def sincronizar_pasta(colecao, pasta, forcar=False):
    """
    Indexa o que é novo ou mudou, pula o que está igual, e remove do índice os arquivos que não existem mais na pasta.
    Arquivo que existe mas não tem texto nativo (PDF escaneado, indexado via OCR no app) é deixado como está.
    """
    arquivos = sorted(f for f in os.listdir(pasta) if f.lower().endswith(EXTENSOES))
    resumo = {"indexados": {}, "pulados": [], "sem_texto": [], "removidos": [], "erros": {}}

    for nome in arquivos:
        caminho = os.path.join(pasta, nome)
        hash_atual = hash_do_arquivo(caminho)
        if not forcar and _ja_indexado(colecao, nome, hash_atual):
            resumo["pulados"].append(nome)
            continue
        try:
            paginas = extrair_paginas(caminho)
        except Exception as e:                       # PDF corrompido não pode derrubar os outros arquivos
            resumo["erros"][nome] = f"{type(e).__name__}: {e}"
            continue
        if paginas:
            resumo["indexados"][nome] = indexar_arquivo(colecao, nome, paginas, hash_arquivo=hash_atual)
        else:
            resumo["sem_texto"].append(nome)

    no_indice = {m["arquivo"] for m in colecao.get(include=["metadatas"])["metadatas"]}
    for nome in sorted(no_indice - set(arquivos)):     # (arquivo com erro de leitura continua em `arquivos`, então é preservado)
        colecao.delete(where={"arquivo": nome})
        resumo["removidos"].append(nome)
    return resumo


def listar_documentos(colecao):
    """[{arquivo, blocos, paginas, secoes}] ordenado por nome."""
    por_arquivo = {}
    for m in colecao.get(include=["metadatas"])["metadatas"]:
        d = por_arquivo.setdefault(m["arquivo"], {"arquivo": m["arquivo"], "blocos": 0, "paginas": set(), "secoes": set()})
        d["blocos"] += 1
        d["paginas"].add(m.get("pagina", 1))
        if m.get("secao"):
            d["secoes"].add(m["secao"])
    return [{"arquivo": d["arquivo"], "blocos": d["blocos"], "paginas": len(d["paginas"]), "secoes": len(d["secoes"])}
            for d in sorted(por_arquivo.values(), key=lambda x: x["arquivo"])]


def indice_desatualizado(colecao) -> bool:
    """Há blocos indexados no formato antigo (sem seção nem cabeçalho)? Então vale sincronizar a pasta de novo."""
    return any(m.get("versao") != VERSAO_INDEXACAO for m in colecao.get(include=["metadatas"])["metadatas"])


def remover_documento(colecao, nome_arquivo, pasta=None):
    """Tira o arquivo do índice e, se `pasta` for informada, apaga também o arquivo dela (senão a sincronização o recriaria)."""
    colecao.delete(where={"arquivo": nome_arquivo})
    if pasta:
        caminho = os.path.join(pasta, os.path.basename(nome_arquivo))
        if os.path.exists(caminho):
            os.remove(caminho)
