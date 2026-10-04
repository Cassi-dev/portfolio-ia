import json
import re
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

import monitorados
import rodar_monitor
from base_eventos import BaseEventos, id_do_evento
from ciclo import pontuar_pendentes, rodar_ciclo
from coleta_noticias import montar_url, montar_url_termos
from deteccao import (
    analisar_alvo, gatilhos, janela, merece_alerta, normalizar, novidades, pico_de_volume, sinal_ponderado,
    virada_de_sentimento,
)
from monitorados import Alvo, Cadastro, Cliente, alvo_de_ticker

HOJE = date(2026, 9, 19)


def dias_atras(n):
    return (HOJE - timedelta(days=n)).isoformat()


def evento(titulo="Manchete", dias=0, score=None, ciclo_id=1, **extra):
    return {"titulo": titulo, "data": dias_atras(dias), "score": score, "ciclo_id": ciclo_id,
            "fonte": "Portal", "link": "http://x", **extra}


def manchetes_distintas(n, inicio=0):
    """Títulos que a deduplicação por similaridade NÃO deve agrupar (duas palavras exclusivas em cada um)."""
    return [evento(f"Assunto{i} movimenta setor{i} nesta semana", dias=i % 20) for i in range(inicio, inicio + n)]


@pytest.fixture
def base(tmp_path):
    with BaseEventos(tmp_path / "teste.db") as b:
        yield b


# --- consulta generalizada (ticker continua igual) ----------------------------------------------------------------

def test_url_de_ticker_nao_mudou():
    url = montar_url("PETR4.SA", 30)
    assert "when%3A30d" in url and "%28%22Petrobras%22%20OR%20PETR4%29" in url and "hl=pt-BR" in url


def test_url_por_termos_livres_cita_nome_proprio_e_deixa_codigo_solto():
    url = montar_url_termos(["Bar do Zé", "PETR4"], "(Porto Alegre)", 15)
    assert "%28%22Bar%20do%20Z%C3%A9%22%20OR%20PETR4%29" in url
    assert "Porto%20Alegre" in url and "when%3A15d" in url and "hl=pt-BR" in url
    assert "hl=en-US" in montar_url_termos(["Apple"], regiao="US")


def test_url_sem_termo_util_e_erro():
    with pytest.raises(ValueError, match="ao menos um termo"):
        montar_url_termos(["", "   "])


# --- cadastro ------------------------------------------------------------------------------------------------------

def alvo(id="alvo-a", papel="proprio", **extra):
    return Alvo(id=id, nome="Alvo A", papel=papel, termos=["Alvo A"], **extra)


def test_cadastro_de_exemplo_e_valido_e_tem_um_cliente_de_cada_perfil():
    cadastro = monitorados.cadastro_de_exemplo()
    assert {c.perfil for c in cadastro.clientes} == {"negocio", "acao"}
    assert cadastro.por_id("restaurante-exemplo").proprio.papel == "proprio"


def test_gatilhos_padrao_vem_do_perfil_e_podem_ser_trocados():
    negocio = Cliente(id="c", nome="C", perfil="negocio", alvos=[alvo()])
    acao = Cliente(id="c", nome="C", perfil="acao", alvos=[alvo()])
    assert "recuperacao judicial" in negocio.gatilhos and "interdicao" in negocio.gatilhos
    assert "fato relevante" in acao.gatilhos and "interdicao" not in acao.gatilhos
    assert Cliente(id="c", nome="C", perfil="negocio", alvos=[alvo()], gatilhos=["greve"]).gatilhos == ["greve"]


@pytest.mark.parametrize("campos,erro", [
    ({"id": "Bar do Zé"}, "minúsculo"),
    ({"alvos": []}, "at least 1"),
    ({"janela_dias": 3}, "greater than or equal"),
    ({"perfil": "outro"}, "perfil"),
])
def test_cadastro_invalido_falha_na_carga(campos, erro):
    base = {"id": "c", "nome": "C", "perfil": "negocio", "alvos": [alvo()]}
    with pytest.raises(ValidationError, match=erro):
        Cliente(**{**base, **campos})


def test_alvo_exige_termo_e_id_em_formato_slug():
    with pytest.raises(ValidationError, match="não vazio"):
        Alvo(id="a", nome="A", termos=["  "])
    with pytest.raises(ValidationError, match="minúsculo"):
        Alvo(id="Alvo A", nome="A", termos=["x"])


def test_ids_repetidos_sao_recusados():
    with pytest.raises(ValidationError, match="alvos com id repetido"):
        Cliente(id="c", nome="C", perfil="negocio", alvos=[alvo(), alvo()])
    with pytest.raises(ValidationError, match="clientes com id repetido"):
        Cadastro(clientes=[Cliente(id="c", nome="C", perfil="negocio", alvos=[alvo()])] * 2)


def test_alvo_de_ticker_reaproveita_o_mapa_de_nomes():
    assert alvo_de_ticker("PETR4.SA").termos == ["Petrobras", "PETR4"]
    assert alvo_de_ticker("AAPL").regiao == "US"
    assert alvo_de_ticker("XPTO3").termos == ["XPTO3"] and alvo_de_ticker("XPTO3").regiao == "BR"


def test_cadastro_salvo_volta_igual(tmp_path):
    caminho = monitorados.salvar(monitorados.cadastro_de_exemplo(), tmp_path / "m.json")
    assert monitorados.carregar(caminho) == monitorados.cadastro_de_exemplo()


def test_cadastro_ausente_explica_como_criar(tmp_path):
    with pytest.raises(FileNotFoundError, match="--criar-exemplo"):
        monitorados.carregar(tmp_path / "nao-existe.json")


def test_cliente_desconhecido_lista_os_que_existem():
    with pytest.raises(KeyError, match="restaurante-exemplo"):
        monitorados.cadastro_de_exemplo().por_id("fantasma")


# --- base de eventos ------------------------------------------------------------------------------------------------

def test_identidade_ignora_caixa_acento_e_espaco():
    assert id_do_evento("a", "noticia", "Petrobras  SOBE 3%") == id_do_evento("a", "noticia", "petrobras sobe 3%")
    assert id_do_evento("a", "noticia", "Ação sobe") == id_do_evento("a", "noticia", "Acao sobe")
    assert id_do_evento("a", "noticia", "X") != id_do_evento("b", "noticia", "X")       # alvo diferente


def test_a_mesma_manchete_nao_entra_duas_vezes(base):
    itens = [evento("Petrobras anuncia dividendos extraordinários")]
    assert len(base.registrar_eventos("c", "a", "noticia", itens, 1, hoje=HOJE)) == 1
    assert base.registrar_eventos("c", "a", "noticia", itens, 2, hoje=HOJE) == []
    assert base.contagem("c") == {"total": 1, "sem_score": 1}


def test_quase_duplicata_de_outro_portal_conta_como_um_evento_so(base):
    base.registrar_eventos("c", "a", "noticia", [evento("Petrobras anuncia dividendos extraordinários bilhões")], 1, hoje=HOJE)
    novos = base.registrar_eventos("c", "a", "noticia", [
        evento("Petrobras anuncia dividendos extraordinários bilhões hoje"),      # mesma notícia, outro portal
        evento("Vale amplia produção de minério no trimestre"),                   # notícia diferente
    ], 2, hoje=HOJE)
    assert [n["titulo"] for n in novos] == ["Vale amplia produção de minério no trimestre"]


def test_duplicata_dentro_do_proprio_lote_tambem_e_barrada(base):
    novos = base.registrar_eventos("c", "a", "noticia", [
        evento("Restaurante Exemplo abre nova unidade no centro"),
        evento("Restaurante Exemplo abre nova unidade no centro da cidade"),
    ], 1, hoje=HOJE)
    assert len(novos) == 1


def test_alvos_diferentes_nao_se_deduplicam(base):
    item = [evento("Mesma manchete para os dois")]
    assert len(base.registrar_eventos("c", "a", "noticia", item, 1, hoje=HOJE)) == 1
    assert len(base.registrar_eventos("c", "b", "noticia", item, 1, hoje=HOJE)) == 1


def test_manchete_sem_titulo_e_ignorada(base):
    assert base.registrar_eventos("c", "a", "noticia", [{"titulo": "  ", "data": dias_atras(0)}], 1, hoje=HOJE) == []


def test_consulta_filtra_por_alvo_e_janela(base):
    base.registrar_eventos("c", "a", "noticia", [evento("Recente", dias=1), evento("Antiga", dias=40)], 1, hoje=HOJE)
    base.registrar_eventos("c", "b", "noticia", [evento("De outro alvo", dias=1)], 1, hoje=HOJE)
    assert len(base.eventos("c")) == 3
    assert [e["titulo"] for e in base.eventos("c", alvo_id="a", desde=HOJE - timedelta(days=30))] == ["Recente"]


def test_pontuacao_e_gravada_e_o_evento_sai_da_fila(base):
    base.registrar_eventos("c", "a", "noticia", [evento("Uma manchete qualquer")], 1, hoje=HOJE)
    pendentes = base.sem_pontuacao("c")
    assert len(pendentes) == 1
    pendentes[0].update(score=0.8, classificacao="Otimista", motivo="m", motor="gemini")
    assert base.gravar_pontuacoes(pendentes) == 1
    assert base.sem_pontuacao("c") == [] and base.eventos("c")[0]["score"] == 0.8
    assert base.contagem("c") == {"total": 1, "sem_score": 0}


def test_ciclo_registra_inicio_fim_e_contagens(base):
    ciclo_id = base.abrir_ciclo("c")
    base.fechar_ciclo(ciclo_id, coletados=10, novos=3, pontuados=3, erros=["fonte x fora do ar"])
    registro = base.ciclos("c")[0]
    assert (registro["coletados"], registro["novos"], registro["pontuados"]) == (10, 3, 3)
    assert registro["fim"] and "fonte x" in registro["erros"]


def test_base_vazia_nao_quebra(base):
    assert base.contagem() == {"total": 0, "sem_score": 0} and base.ciclos() == [] and base.eventos("c") == []


# --- detectores -------------------------------------------------------------------------------------------------------

def test_normalizar():
    assert normalizar("  Vigilância   SANITÁRIA ") == "vigilancia sanitaria"


def test_janela_pega_hoje_e_os_dias_anteriores_sem_encostar_na_janela_seguinte():
    eventos = [evento(dias=0), evento(dias=6), evento(dias=7)]
    # 7 dias = hoje e os 6 anteriores; o de 7 dias atrás já pertence à janela de comparação
    assert len(janela(eventos, HOJE, 7)) == 2


def test_novidades_sao_so_as_do_ciclo_atual():
    eventos = [evento("Nova", ciclo_id=5), evento("Velha", ciclo_id=4)]
    assert [e["titulo"] for e in novidades(eventos, 5)] == ["Nova"]


def test_sinal_ponderado_pesa_mais_o_recente_e_ignora_sem_score():
    eventos = [evento(dias=0, score=1.0), evento(dias=5, score=-1.0), evento(dias=1, score=None)]
    assert sinal_ponderado(eventos, HOJE, meia_vida_dias=5) == pytest.approx(0.333, abs=0.001)
    assert sinal_ponderado([evento(score=None)], HOJE) is None and sinal_ponderado([], HOJE) is None


def test_pico_de_volume_compara_com_a_media_das_janelas_anteriores():
    recentes = [evento(f"r{i}", dias=i) for i in range(6)]                     # 6 nos últimos 7 dias
    antigos = [evento(f"a{i}", dias=10 + i * 4) for i in range(4)]             # 4 nos 28 dias anteriores
    resultado = pico_de_volume(recentes + antigos, HOJE)
    assert resultado["n_recente"] == 6 and resultado["media_anterior"] == 1.0
    assert resultado["razao"] == 6.0 and resultado["e_pico"]


def test_pico_exige_minimo_absoluto_para_nao_gritar_com_uma_noticia():
    assert pico_de_volume([evento("a", dias=1), evento("b", dias=2)], HOJE)["e_pico"] is False
    tres = [evento(f"n{i}", dias=i) for i in range(3)]
    assert pico_de_volume(tres, HOJE) == {"n_recente": 3, "media_anterior": 0.0, "razao": None,
                                          "comparavel": True, "e_pico": True}


def test_primeira_coleta_nao_vira_pico_porque_o_rss_traz_mais_noticia_recente():
    """O caso real que apareceu na primeira execução: 5 de 8 notícias do mês caíram nos últimos 7 dias."""
    eventos = [evento(f"r{i}", dias=i) for i in range(5)] + [evento(f"a{i}", dias=10 + i * 5) for i in range(3)]
    assert pico_de_volume(eventos, HOJE)["e_pico"] is True                              # sem saber desde quando observa
    de_hoje = pico_de_volume(eventos, HOJE, observando_desde=HOJE)
    assert de_hoje["comparavel"] is False and de_hoje["e_pico"] is False
    assert de_hoje["n_recente"] == 5                                                     # o número continua no relatório


def test_depois_de_observar_o_suficiente_o_pico_volta_a_valer():
    eventos = [evento(f"r{i}", dias=i) for i in range(6)] + [evento(f"a{i}", dias=10 + i * 4) for i in range(4)]
    resultado = pico_de_volume(eventos, HOJE, observando_desde=HOJE - timedelta(days=60))
    assert resultado["comparavel"] and resultado["razao"] == 6.0 and resultado["e_pico"]


def test_linha_de_base_parcial_e_medida_so_no_periodo_observado():
    # observando há 21 dias: a janela de comparação só vale pelos 14 dias que realmente foram vistos
    eventos = [evento(f"r{i}", dias=i) for i in range(4)] + [evento(f"a{i}", dias=8 + i) for i in range(4)]
    parcial = pico_de_volume(eventos, HOJE, observando_desde=HOJE - timedelta(days=21))
    assert parcial["comparavel"] and parcial["media_anterior"] == 2.0 and parcial["razao"] == 2.0


def test_volume_estavel_nao_e_pico():
    eventos = [evento(f"r{i}", dias=i) for i in range(4)] + [evento(f"a{i}", dias=8 + i) for i in range(16)]
    assert pico_de_volume(eventos, HOJE)["e_pico"] is False


def test_virada_de_sentimento_precisa_de_amostra_nas_duas_janelas():
    otimista = [evento(f"o{i}", dias=i, score=0.8) for i in range(3)]
    pessimista = [evento(f"p{i}", dias=8 + i, score=-0.6) for i in range(3)]
    resultado = virada_de_sentimento(otimista + pessimista, HOJE)
    assert resultado["anterior"] == -0.6 and resultado["atual"] == 0.8
    assert resultado["delta"] == pytest.approx(1.4) and resultado["virou"]

    poucos = virada_de_sentimento(otimista + pessimista[:1], HOJE)
    assert poucos["delta"] is None and poucos["virou"] is False


def test_variacao_pequena_nao_conta_como_virada():
    atual = [evento(f"a{i}", dias=i, score=0.30) for i in range(3)]
    anterior = [evento(f"b{i}", dias=8 + i, score=0.20) for i in range(3)]
    resultado = virada_de_sentimento(atual + anterior, HOJE)
    assert resultado["delta"] == pytest.approx(0.1) and resultado["virou"] is False


def test_gatilho_casa_sem_acento_e_diz_qual_palavra_bateu():
    eventos = [evento("Restaurante é interditado pela Vigilância Sanitária"), evento("Casa lança novo cardápio")]
    achados = gatilhos(eventos, ["vigilancia sanitaria", "interdicao"])
    assert len(achados) == 1 and achados[0]["gatilho"] == "vigilancia sanitaria"
    assert gatilhos(eventos, []) == []


def test_analise_junta_tudo_e_so_alerta_com_motivo():
    calmo = [evento(f"n{i}", dias=8 + i, score=0.1, ciclo_id=1) for i in range(4)]
    analise = analisar_alvo(calmo, ciclo_id=9, hoje=HOJE, palavras_gatilho=["interdicao"])
    assert analise["novos"] == 0 and merece_alerta(analise) is False

    com_gatilho = calmo + [evento("Interdição da unidade central", dias=0, score=-0.8, ciclo_id=9)]
    assert merece_alerta(analisar_alvo(com_gatilho, 9, HOJE, ["interdicao"])) is True


# --- ciclo completo ----------------------------------------------------------------------------------------------------

def cliente_de_teste(**extra):
    return Cliente(id="cli", nome="Cliente", perfil="negocio", gatilhos=["interdicao"],
                   alvos=[alvo("meu-bar", "proprio"), alvo("concorrente-a", "concorrente")], **extra)


def coletor_fixo(por_alvo):
    return lambda alvo, dias: [dict(i) for i in por_alvo.get(alvo.id, [])]


def manchetes_no_prompt(cliente_falso_obj):
    """Quantas manchetes foram enviadas em cada chamada da IA (o prompt numera com [0], [1]...)."""
    return [len(re.findall(r"^\[\d+\] ", c["contents"], re.M)) for c in cliente_falso_obj.models.chamadas]


def test_ciclo_guarda_pontua_e_resume(base, cliente_falso):
    coleta = {
        "meu-bar": [evento("Meu Bar ganha prêmio de melhor hamburguer", dias=1)],
        "concorrente-a": [evento("Concorrente A sofre interdição da vigilância sanitária", dias=0),
                          evento("Concorrente A muda o cardápio", dias=2)],
    }
    ia = cliente_falso(json.dumps([{"indice": i, "score": 0.5, "classificacao": "Otimista", "motivo": "m"} for i in range(3)]))
    resumo = rodar_ciclo(cliente_de_teste(), base, client_llm=ia, coletor=coletor_fixo(coleta), hoje=HOJE)

    assert (resumo["coletados"], resumo["novos"], resumo["pontuados"]) == (3, 3, 3)
    assert resumo["motores"] == {"gemini": 3} and resumo["erros"] == []
    por_alvo = {a["alvo"]: a for a in resumo["por_alvo"]}
    assert por_alvo["meu-bar"]["novos"] == 1 and por_alvo["meu-bar"]["papel"] == "proprio"
    assert [g["gatilho"] for g in por_alvo["concorrente-a"]["gatilhos"]] == ["interdicao"]
    assert set(por_alvo["meu-bar"]["novidades"][0]) <= {"id", "titulo", "data", "fonte", "link", "score",
                                                        "classificacao", "motor", "gatilho"}
    # o gatilho aparece no relatório, mas a primeira coleta não interrompe ninguém: ali tudo é novo por definição
    assert resumo["primeira_coleta"] is True and resumo["com_alerta"] == []


def test_alerta_so_a_partir_do_segundo_ciclo(base, cliente_falso):
    cliente = cliente_de_teste()
    historico = {"meu-bar": manchetes_distintas(4)}
    rodar_ciclo(cliente, base, coletor=coletor_fixo(historico), hoje=HOJE)

    com_gatilho = {"meu-bar": historico["meu-bar"] + [evento("Interdição do salão principal pela prefeitura", dias=0)]}
    segundo = rodar_ciclo(cliente, base, coletor=coletor_fixo(com_gatilho), hoje=HOJE)
    assert segundo["primeira_coleta"] is False and segundo["com_alerta"] == ["meu-bar"]


def test_gatilho_em_noticia_velha_nao_vira_alerta(base):
    cliente = cliente_de_teste()
    rodar_ciclo(cliente, base, coletor=coletor_fixo({"meu-bar": manchetes_distintas(4)}), hoje=HOJE)
    velha = {"meu-bar": [evento("Interdição ocorrida no mês passado volta a ser noticiada", dias=20)]}
    segundo = rodar_ciclo(cliente, base, coletor=coletor_fixo(velha), hoje=HOJE)
    assert segundo["novos"] == 1 and segundo["com_alerta"] == []


def test_segundo_ciclo_manda_para_a_ia_so_o_que_e_novo(base, cliente_falso):
    antigas = manchetes_distintas(5)
    ia = cliente_falso(json.dumps([{"indice": i, "score": 0.1, "classificacao": "Neutro", "motivo": "m"} for i in range(5)]))
    cliente = cliente_de_teste()

    rodar_ciclo(cliente, base, client_llm=ia, coletor=coletor_fixo({"meu-bar": antigas}), hoje=HOJE)
    assert manchetes_no_prompt(ia) == [5]

    nova = antigas + [evento("Fato inédito acontece na cidade hoje", dias=0)]
    segundo = rodar_ciclo(cliente, base, client_llm=ia, coletor=coletor_fixo({"meu-bar": nova}), hoje=HOJE)
    assert segundo["coletados"] == 6 and segundo["novos"] == 1
    assert manchetes_no_prompt(ia) == [5, 1]                 # a 2ª chamada levou 1 manchete, não 6
    assert base.contagem("cli") == {"total": 6, "sem_score": 0}


def test_ciclo_sem_novidade_nao_chama_a_ia(base, cliente_falso):
    itens = [evento("Uma única manchete do período", dias=1)]
    ia = cliente_falso(json.dumps([{"indice": 0, "score": 0.2, "classificacao": "Neutro", "motivo": "m"}]))
    cliente = cliente_de_teste()
    rodar_ciclo(cliente, base, client_llm=ia, coletor=coletor_fixo({"meu-bar": itens}), hoje=HOJE)
    segundo = rodar_ciclo(cliente, base, client_llm=ia, coletor=coletor_fixo({"meu-bar": itens}), hoje=HOJE)
    assert segundo["novos"] == 0 and segundo["pontuados"] == 0
    assert len(ia.models.chamadas) == 1


def test_lote_grande_e_dividido_em_varias_chamadas(base, cliente_falso):
    muitas = manchetes_distintas(25)
    ia = cliente_falso(json.dumps([{"indice": 0, "score": 0.1, "classificacao": "Neutro", "motivo": "m"}]))
    rodar_ciclo(cliente_de_teste(), base, client_llm=ia, coletor=coletor_fixo({"meu-bar": muitas}), hoje=HOJE, lote=10)
    assert manchetes_no_prompt(ia) == [10, 10, 5]


def test_sem_ia_o_lexico_pontua_e_o_resumo_avisa(base):
    coleta = {"meu-bar": [evento("Bar registra lucro recorde e dividendos", dias=1)]}
    resumo = rodar_ciclo(cliente_de_teste(), base, client_llm=None, coletor=coletor_fixo(coleta), hoje=HOJE)
    assert resumo["motores"] == {"lexico": 1} and resumo["pontuados"] == 1
    assert any("sem chave" in m for m in resumo["motivos_degradado"])
    assert resumo["por_alvo"][0]["novidades"][0]["score"] > 0


def test_falha_de_um_alvo_nao_derruba_o_ciclo(base):
    def coletor(alvo, dias):
        if alvo.id == "meu-bar":
            raise ConnectionError("RSS fora do ar")
        return [evento("Concorrente A abre segunda unidade", dias=1)]

    resumo = rodar_ciclo(cliente_de_teste(), base, coletor=coletor, hoje=HOJE)
    assert resumo["novos"] == 1 and len(resumo["erros"]) == 1
    assert "meu-bar" in resumo["erros"][0] and "RSS fora do ar" in resumo["erros"][0]
    assert base.ciclos("cli")[0]["erros"]


def test_pendencia_de_ciclo_anterior_e_repontuada(base):
    base.registrar_eventos("cli", "meu-bar", "noticia", [evento("Sobrou sem pontuação do ciclo passado", dias=1)], 1, hoje=HOJE)
    assert base.contagem("cli")["sem_score"] == 1
    assert pontuar_pendentes(base, "cli")["pontuados"] == 1
    assert base.contagem("cli")["sem_score"] == 0


# --- linha de comando ---------------------------------------------------------------------------------------------------

def test_cli_cria_exemplo_lista_e_nao_sobrescreve(tmp_path, capsys):
    cadastro = tmp_path / "m.json"
    assert rodar_monitor.main(["--criar-exemplo", "--cadastro", str(cadastro)]) == 0
    assert cadastro.exists() and "restaurante-exemplo" in cadastro.read_text(encoding="utf-8")
    assert rodar_monitor.main(["--criar-exemplo", "--cadastro", str(cadastro)]) == 1
    assert "não vou sobrescrever" in capsys.readouterr().out

    assert rodar_monitor.main(["--listar", "--cadastro", str(cadastro)]) == 0
    assert "restaurante-exemplo" in capsys.readouterr().out


def test_cli_sem_cadastro_explica_o_que_fazer(tmp_path, capsys):
    assert rodar_monitor.main(["--cadastro", str(tmp_path / "nao-existe.json")]) == 1
    assert "--criar-exemplo" in capsys.readouterr().out


def test_cli_historico_mostra_os_ciclos(tmp_path, capsys):
    banco = tmp_path / "m.db"
    with BaseEventos(banco) as b:
        b.fechar_ciclo(b.abrir_ciclo("cli"), 7, 2, 2)
    assert rodar_monitor.main(["--historico", "--banco", str(banco)]) == 0
    saida = capsys.readouterr().out
    assert "cli" in saida and "coletados 7" in saida and "Eventos guardados" in saida


def test_cli_roda_o_ciclo_sem_ia_e_imprime_json(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("ciclo.coletar_do_alvo", lambda alvo, dias: [evento("Notícia do dia para o alvo", dias=1)])
    cadastro = tmp_path / "m.json"
    monitorados.salvar(Cadastro(clientes=[cliente_de_teste()]), cadastro)
    codigo = rodar_monitor.main(["--cadastro", str(cadastro), "--banco", str(tmp_path / "m.db"), "--sem-ia",
                                 "--dedup", "tokens", "--json"])
    assert codigo == 0
    saida = capsys.readouterr().out
    resumos = json.loads(saida[saida.index("["):])            # o JSON vem depois das linhas de estado
    assert len(resumos) == 1 and resumos[0]["novos"] == 2 and resumos[0]["motores"] == {"lexico": 2}
