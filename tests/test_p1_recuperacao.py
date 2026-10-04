import chromadb
import pytest

from indexacao import indexar_arquivo
from recuperacao import BM25, MODOS, Recuperador, ResultadoBusca, Trecho, decidir, fusao_rrf, tokenizar

DOCS = {
    "rh.md": "# Manual de RH\n\n## Férias\n\nTodo colaborador tem 30 dias corridos de férias após 12 meses.\n\n## Benefícios\n\nO vale-refeição é de R$ 45 por dia útil.",
    "seguranca.md": "# Segurança\n\n## Senhas\n\nA senha deve ter no mínimo 12 caracteres e usar 2FA.\n\n## Backup\n\nO backup dos servidores é guardado por 30 dias.",
    "sla.md": "# Suporte\n\n## Prazos\n\nChamados P1 têm primeira resposta em até 15 minutos.\n\n## Canais\n\nO canal principal é o portal de suporte.",
}


@pytest.fixture
def colecao(tmp_path, embedding_palavras):
    c = chromadb.PersistentClient(path=str(tmp_path / "banco")).get_or_create_collection(
        "busca", embedding_function=embedding_palavras(), metadata={"hnsw:space": "cosine"})
    for nome, texto in DOCS.items():
        indexar_arquivo(c, nome, [(1, texto)])
    return c


# --- tokenização e BM25 -----------------------------------------------------------------------------------------------

def test_tokenizar_ignora_acento_caixa_stopwords_e_plural():
    assert tokenizar("Quantos DIAS de Férias, por favor?") == ["dia", "feria", "favor"]
    assert tokenizar("As funções e as ações") == ["funcao", "acao"]
    assert tokenizar("Cartão de crédito PIX 2FA") == ["cartao", "credito", "pix", "2fa"]


def test_bm25_acha_o_documento_com_o_termo_raro():
    bm25 = BM25(["reembolso integral em sete dias", "senha com doze caracteres e 2fa", "backup diário dos servidores"])
    notas = bm25.pontuar("preciso de 2FA")
    assert notas.argmax() == 1 and notas[0] == 0 and notas[2] == 0


def test_bm25_termo_desconhecido_nao_pontua_e_termo_raro_vale_mais_que_o_comum():
    bm25 = BM25(["prazo de dias", "prazo de horas", "prazo de semanas kubernetes"])
    assert bm25.pontuar("xyzabc").sum() == 0
    assert bm25.pontuar("kubernetes")[2] > bm25.pontuar("prazo")[2]


def test_bm25_com_colecao_vazia_nao_quebra():
    assert len(BM25([]).pontuar("qualquer coisa")) == 0


# --- fusão RRF -------------------------------------------------------------------------------------------------------------

def test_rrf_premia_quem_aparece_bem_nas_duas_listas():
    fundido = [i for i, _ in fusao_rrf([["a", "b", "c"], ["c", "b", "d"]])]
    assert set(fundido[:2]) == {"b", "c"} and set(fundido[2:]) == {"a", "d"}      # quem está nas duas listas vem antes


def test_rrf_nao_depende_da_escala_das_notas():
    assert fusao_rrf([["x", "y"]]) == fusao_rrf([["x", "y"]], k=60)
    assert fusao_rrf([["x"], ["x"]])[0][1] == pytest.approx(2 / 61)


# --- decidir ----------------------------------------------------------------------------------------------------------------------

def resultado(**kw):
    return ResultadoBusca(trechos=[Trecho("1", "t", "a.md")], **kw)


def test_decidir_com_reranker_usa_a_nota_dele():
    assert decidir(resultado(melhor_rerank=2.0, melhor_distancia=0.9), limiar_rerank=-4.0).responder
    assert not decidir(resultado(melhor_rerank=-6.0, melhor_distancia=0.01), limiar_rerank=-4.0).responder


def test_decidir_sem_reranker_usa_a_distancia():
    assert decidir(resultado(melhor_distancia=0.10), limiar_distancia=0.16).responder
    d = decidir(resultado(melhor_distancia=0.30), limiar_distancia=0.16)
    assert not d.responder and "0.3000" in d.motivo


def test_decidir_sem_trechos_recusa():
    assert not decidir(ResultadoBusca(trechos=[])).responder


# --- Recuperador ---------------------------------------------------------------------------------------------------------------------

def test_modo_invalido_e_recusado(colecao):
    with pytest.raises(ValueError):
        Recuperador(colecao, "inexistente")


@pytest.mark.parametrize("modo", ["vetorial", "bm25", "hibrido"])
def test_cada_modo_acha_o_documento_certo(colecao, modo):
    r = Recuperador(colecao, modo).buscar("quantos dias de férias o colaborador tem", k=3)
    assert r.trechos[0].arquivo == "rh.md" and "30 dias" in r.trechos[0].texto
    assert set(r.latencias_ms) >= {"vetorial", "bm25", "rerank", "total"}


def test_trecho_traz_arquivo_pagina_e_secao(colecao):
    t = Recuperador(colecao, "vetorial").buscar("senha mínimo caracteres 2FA", k=1).trechos[0]
    assert (t.arquivo, t.pagina, t.secao) == ("seguranca.md", 1, "Senhas") and t.distancia is not None


def test_modo_com_reranker_reordena_e_expoe_a_nota(colecao, reranker_falso):
    r = Recuperador(colecao, "vetorial_rerank", reranker=reranker_falso).buscar("primeira resposta chamados P1", k=3)
    assert r.trechos[0].arquivo == "sla.md" and r.melhor_rerank == r.trechos[0].nota_rerank
    notas = [t.nota_rerank for t in r.trechos]
    assert notas == sorted(notas, reverse=True)


def test_modo_sem_reranker_nao_calcula_nota_de_reranker(colecao):
    r = Recuperador(colecao, "hibrido").buscar("vale-refeição", k=2)
    assert r.melhor_rerank is None and all(t.nota_rerank is None for t in r.trechos)


def test_filtro_por_arquivo_restringe_todos_os_modos(colecao, reranker_falso):
    for modo in MODOS:
        r = Recuperador(colecao, modo, reranker=reranker_falso).buscar("dias", k=5, arquivos=["seguranca.md"])
        assert r.trechos and {t.arquivo for t in r.trechos} == {"seguranca.md"}, modo


def test_bm25_e_refeito_quando_o_conteudo_da_colecao_muda(colecao):
    rec = Recuperador(colecao, "bm25")
    assert not rec.buscar("kubernetes", k=3).trechos
    indexar_arquivo(colecao, "infra.md", [(1, "# Infra\n\n## Cluster\n\nUsamos Kubernetes em produção.")])
    assert rec.buscar("kubernetes", k=3).trechos[0].arquivo == "infra.md"


def test_colecao_vazia_nao_quebra_a_busca(tmp_path, embedding_palavras):
    vazia = chromadb.PersistentClient(path=str(tmp_path / "v")).get_or_create_collection("vazia", embedding_function=embedding_palavras())
    for modo in ("vetorial", "bm25", "hibrido"):
        assert Recuperador(vazia, modo).buscar("qualquer", k=3).trechos == []
