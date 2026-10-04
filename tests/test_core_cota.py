"""Leitura do 429 do Gemini: quanto esperar, qual cota estourou e o que dizer ao usuário."""
import pytest

from core import cota, llm
from core.degradacao import motivo_falha

# O 429 chega assim, com o JSON do erro dentro do texto.
POR_MINUTO = (
    "ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', "
    "'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}, "
    "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '37s'}]}}"
)
POR_DIA = POR_MINUTO.replace("PerMinute", "PerDay").replace("'retryDelay': '37s'", "'retryDelay': '0s'")


def test_le_a_espera_que_a_api_sugeriu():
    assert cota.detalhes(Exception(POR_MINUTO))["espera"] == 37.0


def test_distingue_limite_por_minuto_de_limite_por_dia():
    assert cota.detalhes(Exception(POR_MINUTO))["por_dia"] is False
    assert cota.detalhes(Exception(POR_DIA))["por_dia"] is True


def test_erro_que_nao_e_de_cota_passa_batido():
    info = cota.detalhes(Exception("500 INTERNAL"))
    assert info["cota"] is False and cota.explicar(Exception("500 INTERNAL")) == ""


def test_reconhece_a_cota_pelo_codigo_do_erro(erro_api):
    assert cota.e_cota(erro_api(429)) and not cota.e_cota(erro_api(503))


def test_a_mensagem_por_minuto_diz_quanto_esperar():
    texto = cota.explicar(Exception(POR_MINUTO))
    assert "limite de chamadas por minuto" in texto and "37s" in texto


def test_a_mensagem_por_dia_avisa_que_esperar_nao_resolve():
    texto = cota.explicar(Exception(POR_DIA))
    assert "cota diária" in texto and "Esperar não resolve hoje" in texto


def test_o_usuario_le_a_instrucao_e_nao_o_erro_cru():
    """Era isto que aparecia na tela: 'ClientError: 429 RESOURCE_EXHAUSTED...' cortado no meio."""
    motivo = motivo_falha(Exception(POR_DIA))
    assert "ClientError" not in motivo and "RESOURCE_EXHAUSTED" not in motivo
    assert "faturamento" in motivo


def test_erro_comum_continua_mostrando_o_erro():
    assert "falha na chamada da IA" in motivo_falha(Exception("ValueError: deu ruim"))


# --- efeito na hora de chamar a IA ----------------------------------------------------------------

def _cliente_que_estoura(cliente_falso, texto, vezes=5):
    return cliente_falso(*[Exception(texto)] * vezes)


def test_espera_o_tempo_que_a_api_mandou_e_so_uma_vez(cliente_falso):
    """O backoff era 2s e 4s, curto demais para o limite por minuto; mas esperar 3 vezes congelaria a tela."""
    esperas = []
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, POR_MINUTO), "p", usar_cache=False,
                        dormir=esperas.append)
    assert esperas == [37.0]


def test_cota_diaria_nao_fica_tentando_de_novo(cliente_falso):
    esperas = []
    cliente = _cliente_que_estoura(cliente_falso, POR_DIA)
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(cliente, "p", usar_cache=False, dormir=esperas.append)
    assert esperas == [] and len(cliente.models.chamadas) == 1


def test_depois_da_cota_estourar_as_proximas_chamadas_falham_na_hora(cliente_falso):
    """Sem isto, cada etapa seguinte do map-reduce repetiria as tentativas e a espera por nada."""
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, POR_DIA), "p", usar_cache=False, dormir=lambda s: None)

    outro = cliente_falso("resposta que nem deveria ser pedida")
    with pytest.raises(llm.FalhaLLM, match="tente de novo em"):
        llm.gerar_texto(outro, "p", usar_cache=False, dormir=lambda s: None)
    assert outro.models.chamadas == []


def test_o_bloqueio_diz_o_motivo_em_portugues(cliente_falso):
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, POR_DIA), "p", usar_cache=False, dormir=lambda s: None)
    with pytest.raises(llm.FalhaLLM, match="cota diária"):
        llm.gerar_texto(cliente_falso("x"), "p", usar_cache=False, dormir=lambda s: None)


def test_uma_chamada_que_da_certo_libera_o_bloqueio(cliente_falso):
    esperas = []
    assert llm.gerar_texto(cliente_falso(Exception(POR_MINUTO), "ok"), "p", usar_cache=False,
                           dormir=esperas.append) == "ok"
    assert llm.bloqueio_restante() == 0.0


def test_a_espera_nunca_passa_do_teto(cliente_falso):
    absurdo = POR_MINUTO.replace("'37s'", "'86400s'")
    esperas = []
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, absurdo), "p", usar_cache=False, dormir=esperas.append)
    assert esperas == [llm.ESPERA_MAXIMA]


def test_a_explicacao_nao_e_embrulhada_nem_cortada_de_novo(cliente_falso):
    """
    O que apareceu em uso real: "falha na chamada da IA (a cota diária ... ou continue )" — a explicação
    já pronta entrava no formato de erro genérico e era truncada em 140 caracteres, no meio da palavra.
    """
    with pytest.raises(llm.FalhaLLM) as capturado:
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, POR_DIA), "p", usar_cache=False, dormir=lambda s: None)

    motivo = motivo_falha(capturado.value)
    assert motivo.startswith("a cota diária") and motivo.endswith("continue amanhã")
    assert "falha na chamada da IA" not in motivo


def test_o_erro_do_bloqueio_tambem_sai_inteiro(cliente_falso):
    with pytest.raises(llm.FalhaLLM):
        llm.gerar_texto(_cliente_que_estoura(cliente_falso, POR_DIA), "p", usar_cache=False, dormir=lambda s: None)
    with pytest.raises(llm.FalhaLLM) as capturado:
        llm.gerar_texto(cliente_falso("x"), "p", usar_cache=False, dormir=lambda s: None)

    motivo = motivo_falha(capturado.value)
    assert "tente de novo em" in motivo and "falha na chamada da IA" not in motivo


def test_erro_comum_continua_sendo_embrulhado_e_encurtado(cliente_falso, erro_api):
    with pytest.raises(llm.FalhaLLM) as capturado:
        llm.gerar_texto(cliente_falso(erro_api(400, "x" * 300)), "p", usar_cache=False, dormir=lambda s: None)
    motivo = motivo_falha(capturado.value)
    assert motivo.startswith("falha na chamada da IA (") and len(motivo) < 200
