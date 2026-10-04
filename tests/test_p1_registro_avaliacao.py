import importlib.util
import json
from pathlib import Path

import chromadb
import pytest

import registro

RAIZ = Path(__file__).resolve().parents[1]
BASE_P1 = RAIZ / "projeto_01_chatbot_rag"


def carregar_avaliador():
    spec = importlib.util.spec_from_file_location("avaliar_recuperacao", BASE_P1 / "5_avaliar_recuperacao.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


aval = carregar_avaliador()


# --- registro e feedback ---------------------------------------------------------------------------------------------------

@pytest.fixture
def pasta_de_registro(tmp_path, monkeypatch):
    monkeypatch.setattr(registro, "PASTA", tmp_path / "registros")
    monkeypatch.setenv("RAG_LOG", "1")
    return tmp_path / "registros"


def consulta(pergunta="q", decisao="respondeu", total=100.0):
    return {"pergunta": pergunta, "decisao": decisao, "latencias_ms": {"total": total}, "trechos": [{"arquivo": "a.md"}]}


def test_consulta_e_gravada_em_jsonl_e_devolve_o_id(pasta_de_registro):
    identificador = registro.registrar_consulta(consulta("Quantos dias de férias?"))
    linhas = (pasta_de_registro / "consultas.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 1 and json.loads(linhas[0])["id"] == identificador
    assert json.loads(linhas[0])["pergunta"] == "Quantos dias de férias?"


def test_registro_desligado_nao_grava_nada(pasta_de_registro, monkeypatch):
    monkeypatch.setenv("RAG_LOG", "0")
    assert registro.registrar_consulta(consulta())
    assert not pasta_de_registro.exists() and registro.carregar() == []


def test_feedback_o_ultimo_voto_vale_e_voto_invalido_e_ignorado(pasta_de_registro):
    i = registro.registrar_consulta(consulta())
    registro.registrar_feedback(i, 1)
    registro.registrar_feedback(i, -1)
    registro.registrar_feedback(i, 5)
    assert registro.resumo_metricas(registro.carregar())["pct_positivo"] == 0


def test_metricas_de_uso(pasta_de_registro):
    ids = [registro.registrar_consulta(consulta(f"q{n}", "respondeu" if n < 3 else "nao_sei", total=100.0 * (n + 1))) for n in range(4)]
    registro.registrar_feedback(ids[0], 1)
    registro.registrar_feedback(ids[1], -1)
    m = registro.resumo_metricas(registro.carregar())
    assert m["consultas"] == 4 and m["pct_nao_sei"] == 25 and m["com_feedback"] == 2 and m["pct_positivo"] == 50
    assert m["latencia_mediana_ms"] == 250 and m["latencia_p95_ms"] == 400


def test_metricas_sem_consultas(pasta_de_registro):
    assert registro.resumo_metricas([]) == {"consultas": 0}


def test_candidatos_a_gabarito_separa_erros_de_acertos_e_nao_inclui_quem_nao_votou(pasta_de_registro):
    a, b, _ = (registro.registrar_consulta(consulta(f"pergunta {n}")) for n in range(3))
    registro.registrar_feedback(a, 1)
    registro.registrar_feedback(b, -1)
    candidatos = registro.candidatos_a_gabarito(registro.carregar())
    assert [c["voto"] for c in candidatos] == ["negativo", "positivo"] and len(candidatos) == 2
    assert candidatos[0]["arquivo_do_melhor_trecho"] == "a.md" and candidatos[0]["revisar"]


# --- métricas do avaliador ----------------------------------------------------------------------------------------------------

def test_auroc():
    assert aval.auroc([3, 4, 5], [0, 1, 2]) == 1.0
    assert aval.auroc([0, 1], [3, 4]) == 0.0
    assert aval.auroc([1, 2], [1, 2]) == 0.5
    assert aval.auroc([], [1]) != aval.auroc([], [1])                        # NaN


def test_melhor_corte_separa_os_dois_grupos():
    corte = aval.melhor_corte([5, 6, 7], [1, 2, 3])
    assert 3 < corte < 5


def test_calibracao_cruzada_em_dados_separaveis_acerta_tudo_e_em_dados_misturados_nao():
    separaveis = [(True, 20 + i) for i in range(10)] + [(False, i) for i in range(10)]
    r = aval.recusa_com_calibracao_cruzada(separaveis)
    assert r["acerta_o_que_tem_resposta"] == 1.0 and r["recusa_o_que_nao_tem"] == 1.0
    misturados = [(i % 2 == 0, (i * 7) % 5) for i in range(20)]
    r2 = aval.recusa_com_calibracao_cruzada(misturados)
    assert r2["acerta_o_que_tem_resposta"] < 1.0 or r2["recusa_o_que_nao_tem"] < 1.0


class TrechoFalso:
    def __init__(self, arquivo, texto):
        self.arquivo, self.texto = arquivo, texto


def test_acerto_exige_arquivo_certo_e_a_frase_de_evidencia_ignorando_acento_e_caixa():
    item = {"arquivo": "rh.md", "evidencia": "30 dias corridos de férias"}
    assert aval.acertou(TrechoFalso("rh.md", "Manual > Férias\ntem 30 DIAS corridos de ferias"), item)
    assert not aval.acertou(TrechoFalso("outro.md", "30 dias corridos de férias"), item)
    assert not aval.acertou(TrechoFalso("rh.md", "20 dias corridos"), item)
    assert aval.acertou(TrechoFalso("rh.md", "qualquer coisa"), {"arquivo": "rh.md", "evidencia": None})        # abrangente


def test_posicao_do_acerto():
    item = {"arquivo": "a.md", "evidencia": "alvo"}
    assert aval.posicao_do_acerto([TrechoFalso("a.md", "x"), TrechoFalso("a.md", "o alvo")], item) == 2
    assert aval.posicao_do_acerto([TrechoFalso("a.md", "x")], item) is None


# --- o gabarito e o corpus ---------------------------------------------------------------------------------------------------------------

def test_gabarito_tem_68_perguntas_das_categorias_esperadas():
    perguntas = aval.carregar_gabarito()
    tipos = {t: sum(1 for p in perguntas if p["tipo"] == t) for t in {p["tipo"] for p in perguntas}}
    assert len(perguntas) == 68 and tipos == {"literal": 8, "parafrase": 24, "numerica_sigla": 16, "abrangente": 6,
                                              "fora_dominio": 8, "fora_dominio_dificil": 6}
    assert len({p["pergunta"] for p in perguntas}) == 68


def test_toda_evidencia_existe_exatamente_uma_vez_no_documento_indicado():
    from texto_util import chave
    for p in aval.carregar_gabarito():
        if p["evidencia"]:
            texto = chave((BASE_P1 / "corpus_ficticio" / p["arquivo"]).read_text(encoding="utf-8"))
            assert texto.count(chave(p["evidencia"])) == 1, p["evidencia"]
        elif p["arquivo"]:
            assert (BASE_P1 / "corpus_ficticio" / p["arquivo"]).exists()


def test_avaliacao_de_ponta_a_ponta_com_embedding_falso_mede_recall_e_nao_sei(tmp_path, embedding_palavras, reranker_falso):
    from recuperacao import Recuperador
    cliente = chromadb.PersistentClient(path=str(tmp_path / "b"))
    colecao = aval.construir_colecao(cliente, "aval_contextual", "contextual", embedding_palavras())
    assert colecao.count() > 30
    r = aval.avaliar_configuracao(Recuperador(colecao, "hibrido"), aval.carregar_gabarito())
    assert r["recall@5"] >= 0.85 and r["mrr@5"] > 0.5                       # saco de palavras já acha o lexical
    assert 0.0 <= r["auroc_nao_sei"] <= 1.0 and {"corte_sugerido", "latencia_p95_ms"} <= set(r)
    r2 = aval.avaliar_configuracao(Recuperador(colecao, "vetorial_rerank", reranker=reranker_falso), aval.carregar_gabarito())
    assert r2["recall@5"] >= 0.85


# --- avaliação de ponta a ponta com a IA (6_avaliar_resposta.py) ------------------------------------------------------------------------

def carregar_ponta_a_ponta():
    spec = importlib.util.spec_from_file_location("avaliar_resposta", BASE_P1 / "6_avaliar_resposta.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ponta = carregar_ponta_a_ponta()


@pytest.mark.parametrize("resposta,evidencia,esperado", [
    ("Você tem 30 dias corridos de férias.", "30 dias corridos de férias", True),
    ("São 30 dias.", "30 dias corridos de férias", False),                       # faltam palavras do fato
    ("Você tem 20 dias corridos de férias.", "30 dias corridos de férias", False),   # número errado
    ("O plano Pro custa R$ 299 por mês.", "plano Pro custa R$ 299 por mês", True),
    ("O preço é sob consulta, fale com vendas.", "preço sob consulta", True),
    ("Qualquer texto", None or "", True),
])
def test_resposta_contem_evidencia(resposta, evidencia, esperado):
    assert ponta.resposta_contem_evidencia(resposta, evidencia) is esperado


@pytest.mark.parametrize("item,desfecho,resposta,esperado", [
    ({"arquivo": "a.md", "evidencia": "7 dias"}, "respondida", "São 7 dias.", "acerto"),
    ({"arquivo": "a.md", "evidencia": "7 dias"}, "respondida", "São 30 dias.", "resposta_errada"),
    ({"arquivo": "a.md", "evidencia": "7 dias"}, "recusou_busca", "", "omissao"),
    ({"arquivo": "a.md", "evidencia": "7 dias"}, "nao_verificada", "São 7 dias.", "omissao"),
    ({"arquivo": "a.md", "evidencia": None}, "respondida", "Trata de RH.", "acerto"),
    ({"arquivo": None, "evidencia": None}, "recusou_busca", "", "recusa_correta"),
    ({"arquivo": None, "evidencia": None}, "sem_base", "", "recusa_correta"),
    ({"arquivo": None, "evidencia": None}, "nao_verificada", "inventado", "recusa_correta"),
    ({"arquivo": None, "evidencia": None}, "respondida", "A capital é Canberra.", "resposta_indevida"),
    ({"arquivo": "a.md", "evidencia": "7 dias"}, "falhou", "", "falha_da_ia"),
])
def test_classificacao_do_resultado(item, desfecho, resposta, esperado):
    assert ponta.classificar(item, desfecho, resposta) == esperado


def test_ponta_a_ponta_com_ia_simulada_conta_acertos_omissoes_e_respostas_indevidas(tmp_path, embedding_palavras, cliente_falso):
    from recuperacao import Recuperador
    aval = carregar_avaliador()
    colecao = aval.construir_colecao(chromadb.PersistentClient(path=str(tmp_path / "b")), "ponta_a_ponta", "contextual", embedding_palavras())
    gabarito = [
        {"tipo": "literal", "pergunta": "Quantos dias corridos de férias o colaborador tem direito?", "arquivo": "manual_rh_ferias_beneficios.md", "evidencia": "30 dias corridos de férias"},
        {"tipo": "fora_dominio", "pergunta": "Qual é a capital da Austrália?", "arquivo": None, "evidencia": None},
    ]
    certa = json.dumps({"suficiente": True, "resposta": "São 30 dias corridos de férias [1].",
                        "citacoes": [{"trecho": 1, "texto_literal": "30 dias corridos de férias"}]})
    # limiar de distância alto: a busca deixa passar tudo e a decisão fica com a IA, que aqui dá SEMPRE a mesma resposta
    r = ponta.avaliar_ponta_a_ponta(cliente_falso(certa), Recuperador(colecao, "vetorial"), gabarito, limiar_distancia=2.0)
    # Na pergunta sem resposta a IA "responde" citando uma frase que não está nos trechos recuperados: a conferência de
    # citações a barra (não_verificada) e ela conta como recusa correta, em vez de resposta indevida.
    assert r["contagem"] == {"acerto": 1, "recusa_correta": 1}
    assert r["acerto_nas_que_tem_resposta"] == 1.0 and r["resposta_indevida_nas_que_nao_tem"] == 0.0
    assert r["citacoes_conferidas"] == "1/2"


# --- exibição do trecho no modo local ---------------------------------------------------------------------------------------------------

def test_sem_cabecalho_tira_a_linha_do_documento_e_secao_so_quando_ela_confere():
    from texto_util import sem_cabecalho
    bloco = "MANUAL - FOCO TI > Seção 1: reembolso\nO cliente tem 7 dias.\n- Após isso, só falha técnica."
    assert sem_cabecalho(bloco, "Seção 1: reembolso") == "O cliente tem 7 dias.\n- Após isso, só falha técnica."
    assert sem_cabecalho(bloco, "Outra seção") == bloco                # seção não confere: não mexe
    assert sem_cabecalho(bloco, "") == bloco
    assert sem_cabecalho("uma linha só > Seção", "Seção") == "uma linha só > Seção"    # sem corpo, nada a tirar


def test_como_citacao_preserva_as_linhas_para_a_lista_nao_virar_paragrafo():
    from texto_util import como_citacao
    assert como_citacao("Prazo: 7 dias.\n\n- item A\n- item B") == "> Prazo: 7 dias.\n>\n> - item A\n> - item B"


def test_como_citacao_recupera_itens_de_lista_achatados_mas_nao_mexe_em_hifen_no_meio_da_frase():
    from texto_util import como_citacao
    assert como_citacao("Prazo de 7 dias. - Após isso só com falha. - Pix em 2 horas.") == "> Prazo de 7 dias.\n> - Após isso só com falha.\n> - Pix em 2 horas."
    assert como_citacao("O plano Pro - o mais vendido - custa R$ 299.") == "> O plano Pro - o mais vendido - custa R$ 299."
