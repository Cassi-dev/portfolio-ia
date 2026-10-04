import json

import pytest
from pydantic import BaseModel, Field

from core import cache, llm
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado, gerar_texto


class Nota(BaseModel):
    indice: int
    score: float = Field(ge=-1, le=1)


SEM_ESPERA = {"dormir": lambda s: None}


def test_texto_simples(cliente_falso):
    assert gerar_texto(cliente_falso("olá"), "oi", **SEM_ESPERA) == "olá"


def test_erro_transitorio_tenta_de_novo_com_backoff(cliente_falso, erro_api):
    esperas = []
    cliente = cliente_falso(erro_api(503), erro_api(429), "ok")
    assert gerar_texto(cliente, "p", dormir=esperas.append) == "ok"
    assert esperas == [2.0, 4.0]
    assert len(cliente.models.chamadas) == 3


def test_erro_permanente_nao_repete(cliente_falso, erro_api):
    cliente = cliente_falso(erro_api(400, "pedido inválido"))
    with pytest.raises(FalhaLLM, match="pedido inválido"):
        gerar_texto(cliente, "p", **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 1


def test_erro_transitorio_persistente_esgota_as_tentativas(cliente_falso, erro_api):
    cliente = cliente_falso(erro_api(503))
    with pytest.raises(FalhaLLM):
        gerar_texto(cliente, "p", tentativas=3, **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 3


def test_resposta_vazia_e_falha(cliente_falso):
    with pytest.raises(FalhaLLM, match="vazia"):
        gerar_texto(cliente_falso("   "), "p", **SEM_ESPERA)


def test_estruturado_valida_e_devolve_o_modelo(cliente_falso):
    cliente = cliente_falso(json.dumps([{"indice": 0, "score": 0.5}, {"indice": 1, "score": -1}]))
    notas = gerar_estruturado(cliente, "p", list[Nota], **SEM_ESPERA)
    assert [n.score for n in notas] == [0.5, -1]
    config = cliente.models.chamadas[0]["config"]
    assert config.response_mime_type == "application/json" and config.response_schema == list[Nota]


def test_estruturado_aceita_cerca_markdown(cliente_falso):
    cliente = cliente_falso("```json\n" + json.dumps({"indice": 1, "score": 0}) + "\n```")
    assert gerar_estruturado(cliente, "p", Nota, **SEM_ESPERA).indice == 1


def test_estruturado_repara_uma_vez_devolvendo_o_erro_ao_modelo(cliente_falso):
    cliente = cliente_falso(json.dumps({"indice": 1, "score": 7}), json.dumps({"indice": 1, "score": 0.7}))
    assert gerar_estruturado(cliente, "p", Nota, **SEM_ESPERA).score == 0.7
    segundo_prompt = cliente.models.chamadas[1]["contents"]
    assert "rejeitada" in segundo_prompt and "score" in segundo_prompt


def test_estruturado_invalido_duas_vezes_levanta_resposta_invalida(cliente_falso):
    cliente = cliente_falso("isto não é json")
    with pytest.raises(RespostaInvalida):
        gerar_estruturado(cliente, "p", Nota, **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 2


def test_estruturado_sem_reparo_faz_uma_chamada_so(cliente_falso):
    cliente = cliente_falso("{}")
    with pytest.raises(RespostaInvalida):
        gerar_estruturado(cliente, "p", Nota, reparar=False, **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 1


def test_cache_evita_a_segunda_chamada(cliente_falso, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setattr(cache, "PASTA", tmp_path)
    cliente = cliente_falso(json.dumps({"indice": 3, "score": 0.1}))

    primeira = gerar_estruturado(cliente, "mesmo prompt", Nota, **SEM_ESPERA)
    segunda = gerar_estruturado(cliente, "mesmo prompt", Nota, **SEM_ESPERA)

    assert primeira == segunda
    assert len(cliente.models.chamadas) == 1
    gerar_estruturado(cliente, "outro prompt", Nota, **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 2


def test_cache_de_texto(cliente_falso, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setattr(cache, "PASTA", tmp_path)
    cliente = cliente_falso("resposta")
    gerar_texto(cliente, "p", **SEM_ESPERA)
    gerar_texto(cliente, "p", **SEM_ESPERA)
    assert len(cliente.models.chamadas) == 1


def test_estatisticas_contam_chamadas_e_cache(cliente_falso, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE", "1")
    monkeypatch.setattr(cache, "PASTA", tmp_path)
    llm.historico.clear()
    cliente = cliente_falso("x")
    gerar_texto(cliente, "p", **SEM_ESPERA)
    gerar_texto(cliente, "p", **SEM_ESPERA)
    est = llm.estatisticas()
    assert est["chamadas_api"] == 1 and est["cache_hits"] == 1


# --- tokens de pensamento e custo -----------------------------------------------------------------

class _Uso:
    def __init__(self, entrada, saida, pensamento):
        self.prompt_token_count = entrada
        self.candidates_token_count = saida
        self.thoughts_token_count = pensamento


class _RespostaComUso:
    def __init__(self, texto, uso):
        self.text = texto
        self.usage_metadata = uso


def test_os_tokens_de_pensamento_entram_na_conta(monkeypatch):
    """
    Eles são cobrados como saída, à mesma tarifa, e ficavam de fora: a estimativa de custo saía bem abaixo
    do que a fatura mostra.
    """
    from core import llm, preco

    # O modelo padrão vem do ambiente deste computador e pode não estar na tabela de preços (custo_usd devolve
    # None de propósito: melhor sem custo do que com número inventado). O teste fixa um preço conhecido.
    monkeypatch.setitem(preco.PRECOS_USD, preco.MODELO_GEMINI, {"entrada": 0.75, "saida": 3.75})
    llm.historico.clear()
    llm._registrar(_RespostaComUso("ok", _Uso(15_000, 2_400, 12_000)), 0.5, do_cache=False)
    uso = llm.estatisticas()
    assert uso["tokens_pensamento"] == 12_000
    assert uso["custo_usd"] == pytest.approx(preco.custo_usd(15_000, 14_400))
    assert uso["custo_usd"] > 3 * preco.custo_usd(15_000, 2_400)       # o pensamento domina a conta


def test_resposta_sem_tokens_de_pensamento_nao_quebra():
    from core import llm

    llm.historico.clear()
    llm._registrar(_RespostaComUso("ok", _Uso(100, 20, None)), 0.1, do_cache=False)
    assert llm.estatisticas()["tokens_pensamento"] == 0


def test_modelo_fora_da_tabela_nao_inventa_custo():
    from core import preco

    assert preco.custo_usd(1000, 1000, modelo="gemini-inexistente-9") is None
    assert preco.custo_usd(1_000_000, 0, modelo="gemini-3.6-flash") == pytest.approx(0.75)
