import hashlib

import chromadb
import pytest
from chromadb import EmbeddingFunction

from indexacao import (
    VERSAO_INDEXACAO,
    dividir_em_blocos,
    id_do_bloco,
    indexar_arquivo,
    indice_desatualizado,
    listar_documentos,
    montar_blocos,
    remover_documento,
    sincronizar_pasta,
)

TEXTO = (
    "O cliente tem prazo de até 7 dias corridos para pedir reembolso integral. "
    "Após esse período, cancelamentos só serão ressarcidos em caso de falha técnica comprovada! "
    "Pagamentos via PIX são restituídos em até 2 horas. Cartão de crédito pode levar até 2 faturas? "
    "O suporte humanizado atende de segunda a sexta, das 08h às 19h, no horário de Brasília. "
) * 4


class EmbeddingLeve(EmbeddingFunction):
    """Vetores determinísticos baratos, para testar o índice sem carregar o modelo de verdade."""

    def __init__(self):
        pass

    def __call__(self, input):
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:16]] for t in input]

    @staticmethod
    def name():
        return "embedding_leve_de_teste"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return EmbeddingLeve()


@pytest.fixture
def colecao(tmp_path):
    cliente = chromadb.PersistentClient(path=str(tmp_path / "banco"))
    return cliente.get_or_create_collection("teste", embedding_function=EmbeddingLeve())


# --- divisão em blocos -------------------------------------------------------

def test_blocos_respeitam_o_tamanho_e_nao_cortam_palavras():
    palavras_originais = set(TEXTO.split())
    blocos = dividir_em_blocos(TEXTO, tamanho=200, sobreposicao=30)
    assert len(blocos) > 3
    assert all(len(b) <= 200 for b in blocos)
    assert all(set(b.split()) <= palavras_originais for b in blocos)


def test_blocos_terminam_em_fim_de_frase_quando_possivel():
    blocos = dividir_em_blocos(TEXTO, tamanho=200, sobreposicao=30)
    assert sum(b.rstrip()[-1] in ".!?" for b in blocos) >= len(blocos) - 1


def test_blocos_tem_sobreposicao_e_cobrem_o_texto_todo():
    blocos = dividir_em_blocos(TEXTO, tamanho=200, sobreposicao=40)
    assert blocos[0].split()[-1] in blocos[1].split()[:8]
    assert set(TEXTO.split()) <= {p for b in blocos for p in b.split()}


def test_texto_curto_vira_um_bloco_e_vazio_vira_nenhum():
    assert dividir_em_blocos("Uma frase curta.") == ["Uma frase curta."]
    assert dividir_em_blocos("   \n  ") == []


def test_palavra_gigante_e_partida_sem_travar():
    blocos = dividir_em_blocos("x" * 1200 + " fim", tamanho=500, sobreposicao=50)
    assert all(len(b) <= 500 for b in blocos) and blocos[-1].endswith("fim")


# --- ids e montagem --------------------------------------------------------------

def test_id_e_deterministico_e_depende_de_arquivo_pagina_e_texto():
    base = id_do_bloco("a.pdf", 1, "texto")
    assert base == id_do_bloco("a.pdf", 1, "texto")
    assert len({base, id_do_bloco("b.pdf", 1, "texto"), id_do_bloco("a.pdf", 2, "texto"), id_do_bloco("a.pdf", 1, "outro")}) == 4


def test_montar_blocos_tem_contexto_global_e_nao_repete_bloco_igual():
    repetido = ("Linha de formulário em branco. " * 40)
    textos, metas, ids = montar_blocos("form.pdf", [(1, repetido)], tamanho=100, sobreposicao=0)
    assert metas[0]["tipo"] == "contexto_global" and "form.pdf" in textos[0]
    assert len(ids) == len(set(ids))


# --- índice: idempotência, substituição, sincronização -------------------------------

def test_reindexar_o_mesmo_arquivo_nao_duplica(colecao):
    paginas = [(1, TEXTO), (2, "Segunda página com outro conteúdo.")]
    primeira = indexar_arquivo(colecao, "doc.pdf", paginas)
    segunda = indexar_arquivo(colecao, "doc.pdf", paginas)
    assert primeira == segunda == colecao.count()


def test_reenviar_arquivo_alterado_substitui_os_blocos_antigos(colecao):
    indexar_arquivo(colecao, "doc.txt", [(1, "Conteúdo antigo sobre reembolso de clientes.")])
    indexar_arquivo(colecao, "outro.txt", [(1, "Documento que não pode ser afetado.")])
    indexar_arquivo(colecao, "doc.txt", [(1, "Conteúdo novo sobre suporte técnico.")])
    textos = colecao.get()["documents"]
    assert not any("antigo" in t for t in textos)
    assert any("novo" in t for t in textos) and any("não pode ser afetado" in t for t in textos)


def test_sincronizar_indexa_atualiza_e_remove(colecao, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "a.txt").write_text("Texto do arquivo A sobre reembolso.", encoding="utf-8")
    (pasta / "b.md").write_text("Texto do arquivo B sobre suporte.", encoding="utf-8")

    r1 = sincronizar_pasta(colecao, str(pasta))
    assert set(r1["indexados"]) == {"a.txt", "b.md"}
    total = colecao.count()
    assert sincronizar_pasta(colecao, str(pasta))["removidos"] == [] and colecao.count() == total

    (pasta / "b.md").unlink()
    r3 = sincronizar_pasta(colecao, str(pasta))
    assert r3["removidos"] == ["b.md"]
    assert {m["arquivo"] for m in colecao.get()["metadatas"]} == {"a.txt"}


def test_arquivo_corrompido_nao_derruba_os_outros_e_nao_e_apagado_do_indice(colecao, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "bom.txt").write_text("Arquivo saudável com conteúdo.", encoding="utf-8")
    (pasta / "quebrado.pdf").write_bytes(b"isto nao e um pdf")
    indexar_arquivo(colecao, "quebrado.pdf", [(1, "Conteúdo antigo, indexado via OCR.")])

    r = sincronizar_pasta(colecao, str(pasta))
    assert "bom.txt" in r["indexados"] and "quebrado.pdf" in r["erros"]
    assert "quebrado.pdf" in {m["arquivo"] for m in colecao.get()["metadatas"]}


# --- seção, cabeçalho contextual e modo antigo ---------------------------------------------------------------------

MD = "# Manual de RH\n\nEste manual reúne as regras.\n\n## Férias\n\nTodo colaborador tem 30 dias corridos de férias.\n\n## Licenças\n\nA licença-paternidade é de 20 dias.\n"


def test_contextual_guarda_a_secao_e_escreve_o_cabecalho_no_bloco():
    textos, metas, _ = montar_blocos("manual.md", [(1, MD)])
    detalhes = [(t, m) for t, m in zip(textos, metas) if m["tipo"] == "detalhe"]
    ferias = next((t, m) for t, m in detalhes if "30 dias" in t)
    assert ferias[1]["secao"] == "Férias" and ferias[0].startswith("Manual de RH > Férias\n")
    assert next(m for t, m in detalhes if "20 dias" in t)["secao"] == "Licenças"


def test_bloco_global_contextual_e_um_indice_do_documento():
    textos, metas, _ = montar_blocos("manual.md", [(1, MD)])
    assert metas[0]["tipo"] == "contexto_global"
    assert "Manual de RH" in textos[0] and "Seções: Férias; Licenças." in textos[0]


def test_modo_plano_reproduz_a_indexacao_antiga_sem_cabecalho_nem_secao():
    textos, metas, _ = montar_blocos("manual.md", [(1, MD)], modo="plano")
    assert all(m["secao"] == "" for m in metas)
    assert not any(t.startswith("Manual de RH >") for t in textos)


def test_metadados_carregam_versao_e_hash_do_arquivo():
    _, metas, _ = montar_blocos("m.md", [(1, MD)], hash_arquivo="abc123")
    assert all(m["hash_arquivo"] == "abc123" and m["versao"] == VERSAO_INDEXACAO for m in metas)


# --- sincronização incremental, listagem e remoção --------------------------------------------------------------------

class ContaChamadas(EmbeddingLeve):
    chamadas = 0

    def __call__(self, input):
        ContaChamadas.chamadas += len(input)
        return super().__call__(input)

    @staticmethod
    def name():
        return "conta_chamadas_de_teste"

    @staticmethod
    def build_from_config(config):
        return ContaChamadas()


def test_sincronizar_pula_o_que_nao_mudou_e_reindexa_o_que_mudou(tmp_path):
    cliente = chromadb.PersistentClient(path=str(tmp_path / "banco"))
    colecao = cliente.get_or_create_collection("contagem", embedding_function=ContaChamadas())
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "a.md").write_text(MD, encoding="utf-8")
    (pasta / "b.txt").write_text("Texto do arquivo B sobre suporte.", encoding="utf-8")

    sincronizar_pasta(colecao, str(pasta))
    depois_da_primeira = ContaChamadas.chamadas
    assert depois_da_primeira > 0

    r2 = sincronizar_pasta(colecao, str(pasta))
    assert sorted(r2["pulados"]) == ["a.md", "b.txt"] and r2["indexados"] == {}
    assert ContaChamadas.chamadas == depois_da_primeira                    # nenhum embedding novo

    (pasta / "b.txt").write_text("Texto novo e diferente do arquivo B.", encoding="utf-8")
    r3 = sincronizar_pasta(colecao, str(pasta))
    assert r3["pulados"] == ["a.md"] and list(r3["indexados"]) == ["b.txt"]

    r4 = sincronizar_pasta(colecao, str(pasta), forcar=True)
    assert set(r4["indexados"]) == {"a.md", "b.txt"}


def test_indice_no_formato_antigo_e_detectado_e_reindexado(colecao, tmp_path):
    colecao.upsert(documents=["bloco antigo"], metadatas=[{"arquivo": "a.md", "pagina": 1, "bloco": 1, "tipo": "detalhe"}], ids=["x"])
    assert indice_desatualizado(colecao)
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "a.md").write_text(MD, encoding="utf-8")
    r = sincronizar_pasta(colecao, str(pasta))
    assert "a.md" in r["indexados"] and not indice_desatualizado(colecao)


def test_listar_e_remover_documento(colecao, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "a.md").write_text(MD, encoding="utf-8")
    (pasta / "b.txt").write_text("Texto simples do arquivo B.", encoding="utf-8")
    sincronizar_pasta(colecao, str(pasta))

    docs = {d["arquivo"]: d for d in listar_documentos(colecao)}
    assert set(docs) == {"a.md", "b.txt"} and docs["a.md"]["secoes"] == 2 and docs["b.txt"]["blocos"] >= 1

    remover_documento(colecao, "a.md", str(pasta))
    assert {d["arquivo"] for d in listar_documentos(colecao)} == {"b.txt"}
    assert not (pasta / "a.md").exists() and (pasta / "b.txt").exists()
    assert "a.md" not in sincronizar_pasta(colecao, str(pasta))["indexados"]     # não volta sozinho


def test_remover_sem_apagar_o_arquivo_deixa_a_sincronizacao_recria_lo(colecao, tmp_path):
    pasta = tmp_path / "docs"
    pasta.mkdir()
    (pasta / "a.md").write_text(MD, encoding="utf-8")
    sincronizar_pasta(colecao, str(pasta))
    remover_documento(colecao, "a.md")                                            # só do índice
    assert "a.md" in sincronizar_pasta(colecao, str(pasta))["indexados"]
