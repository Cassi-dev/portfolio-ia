import json
import sqlite3
from datetime import date

import pandas as pd
import pytest

import avaliar_acuracia
from avaliar_acuracia import avaliar, carregar_gabarito, comparar_resultados
from banco_dados import gerar_dados
from motor_text_to_sql import montar_prompt_sql, processar_pergunta_com_ciclo_correcao

HOJE = date(2026, 9, 19)


def resposta_sql(sql):
    return json.dumps({"sql": sql})


# --- dados de exemplo ---------------------------------------------------------

def test_dados_sao_deterministicos():
    assert gerar_dados() == gerar_dados()


def test_valor_total_do_pedido_e_a_soma_dos_itens(banco_temp):
    linhas = banco_temp.executar_consulta("""
        SELECT COUNT(*) FROM pedidos p
        JOIN (SELECT pedido_id, ROUND(SUM(quantidade * preco_unitario), 2) s FROM itens_pedido GROUP BY pedido_id) i
          ON i.pedido_id = p.id
        WHERE ABS(p.valor_total - i.s) > 0.01
    """)
    assert linhas.df.iloc[0, 0] == 0
    assert banco_temp.executar_consulta("SELECT COUNT(*) FROM pedidos").df.iloc[0, 0] == 400


def test_valores_categoricos_para_o_prompt(banco_temp):
    valores = banco_temp.obter_valores_categoricos()
    assert "PWA TACTO" in valores["pedidos.canal_venda"]
    assert valores["pedidos.status"] == ["Cancelado", "Concluído", "Pendente"]
    assert "clientes.nome" not in valores


# --- 2ª trava: o próprio SQLite --------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DELETE FROM clientes",
    "DROP TABLE clientes",
    "INSERT INTO clientes (nome, cidade, estado, segmento, data_cadastro) VALUES ('x', 'y', 'z', 'w', '2026-01-01')",
    "UPDATE produtos SET preco_venda = 0",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE ':memory:' AS outro",
    "SELECT load_extension('x')",
])
def test_banco_recusa_escrita_mesmo_sem_o_validador(banco_temp, sql):
    resultado = banco_temp.executar_consulta(sql)
    assert resultado.erro
    assert banco_temp.executar_consulta("SELECT COUNT(*) FROM clientes").df.iloc[0, 0] == 40


def test_arquivo_do_banco_abre_como_somente_leitura(banco_temp):
    conn = banco_temp.conectar_somente_leitura()
    with pytest.raises(sqlite3.Error):
        conn.execute("CREATE TABLE x (id INTEGER)")


def test_consulta_infinita_e_interrompida_pelo_limite_de_tempo(banco_temp):
    infinita = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r"
    resultado = banco_temp.executar_consulta(infinita, tempo_maximo=0.3)
    assert "interrompida" in resultado.erro


def test_resultado_grande_e_truncado(banco_temp):
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5000) SELECT n FROM r"
    resultado = banco_temp.executar_consulta(sql, limite=100)
    assert resultado.truncado and len(resultado.df) == 100 and resultado.erro is None


def test_resultado_pequeno_nao_e_truncado(banco_temp):
    resultado = banco_temp.executar_consulta("SELECT nome FROM produtos")
    assert not resultado.truncado and len(resultado.df) == 14


# --- prompt --------------------------------------------------------------------------

def test_prompt_leva_data_de_hoje_schema_valores_e_pergunta(banco_temp):
    prompt = montar_prompt_sql(
        "Quantos pedidos no mês passado?", banco_temp.obter_schema_ddl(), banco_temp.obter_valores_categoricos(), HOJE
    )
    assert "2026-09-19" in prompt
    assert "CREATE TABLE pedidos" in prompt
    assert '"PWA TACTO"' in prompt
    assert "Quantos pedidos no mês passado?" in prompt


def test_prompt_de_correcao_inclui_o_erro_anterior(banco_temp):
    prompt = montar_prompt_sql("p", "schema", {}, HOJE, erro_anterior="no such column: x", sql_anterior="SELECT x FROM t")
    assert "no such column: x" in prompt and "SELECT x FROM t" in prompt


# --- motor com IA simulada --------------------------------------------------------------

def test_caminho_feliz(banco_temp, cliente_falso):
    r = processar_pergunta_com_ciclo_correcao(
        "Quantos clientes existem?", client=cliente_falso(resposta_sql("SELECT COUNT(*) FROM clientes")), hoje=HOJE
    )
    assert r["seguro"] and not r["degradado"] and r["df"].iloc[0, 0] == 40 and r["tentativas"] == 1


def test_ciclo_de_correcao_devolve_o_erro_ao_modelo(banco_temp, cliente_falso):
    cliente = cliente_falso(resposta_sql("SELECT total FROM pedidos"), resposta_sql("SELECT COUNT(*) FROM pedidos"))
    r = processar_pergunta_com_ciclo_correcao("Quantos pedidos?", client=cliente, hoje=HOJE)
    assert r["tentativas"] == 2 and r["df"].iloc[0, 0] == 400
    assert "no such column" in cliente.models.chamadas[1]["contents"]


def test_erro_persistente_nao_vira_loop(banco_temp, cliente_falso):
    r = processar_pergunta_com_ciclo_correcao("?", client=cliente_falso(resposta_sql("SELECT x FROM y")), hoje=HOJE, max_tentativas=2)
    assert r["df"] is None and r["erro_banco"] and r["tentativas"] == 2


def test_sql_destrutivo_gerado_pela_ia_e_bloqueado_e_nunca_executa(banco_temp, cliente_falso):
    r = processar_pergunta_com_ciclo_correcao("apague tudo", client=cliente_falso(resposta_sql("DROP TABLE clientes")), hoje=HOJE)
    assert not r["seguro"] and "BLOQUEIO" in r["msg_seguranca"] and r["df"] is None
    assert banco_temp.executar_consulta("SELECT COUNT(*) FROM clientes").df.iloc[0, 0] == 40


def test_falha_da_api_cai_no_offline_com_aviso(banco_temp, cliente_falso):
    r = processar_pergunta_com_ciclo_correcao("Quais clientes?", client=cliente_falso(RuntimeError("cota esgotada")), hoje=HOJE)
    assert r["degradado"] and "cota esgotada" in r["motivo_degradado"] and r["modo"].startswith("Offline")


def test_resposta_fora_do_schema_cai_no_offline_com_aviso(banco_temp, cliente_falso):
    r = processar_pergunta_com_ciclo_correcao("Quais clientes?", client=cliente_falso("não é json"), hoje=HOJE)
    assert r["degradado"] and "formato" in r["motivo_degradado"]


def test_sem_chave_pergunta_reconhecida_e_nao_reconhecida(banco_temp):
    conhecida = processar_pergunta_com_ciclo_correcao("Faturamento por canal?")
    assert conhecida["degradado"] and conhecida["pergunta_reconhecida"] and "NÃO responde" not in conhecida["motivo_degradado"]
    estranha = processar_pergunta_com_ciclo_correcao("Qual o ticket médio por estado?")
    assert not estranha["pergunta_reconhecida"] and "NÃO responde" in estranha["motivo_degradado"]


# --- avaliação ------------------------------------------------------------------------------

def test_comparador():
    a = pd.DataFrame({"x": [1, 2], "y": ["a", "b"]})
    assert comparar_resultados(a, pd.DataFrame({"n": [2, 1], "m": ["b", "a"]}))                       # ordem e nomes não contam
    assert not comparar_resultados(a, pd.DataFrame({"n": [2, 1], "m": ["b", "a"]}), ordenado=True)
    assert comparar_resultados(pd.DataFrame({"v": [5]}), pd.DataFrame({"v": [5.0]}))                  # int x float
    assert comparar_resultados(pd.DataFrame({"v": [1.004]}), pd.DataFrame({"v": [1.0]}))              # 2 casas
    assert not comparar_resultados(a, a[["x"]])                                                       # nº de colunas
    assert not comparar_resultados(pd.DataFrame({"v": [1]}), pd.DataFrame({"v": [2]}))


def test_gabarito_tem_50_perguntas_e_o_proprio_sql_acerta_100(banco_temp, tmp_path, monkeypatch):
    monkeypatch.setattr(avaliar_acuracia, "BASE", tmp_path)
    _, perguntas = carregar_gabarito()
    assert len(perguntas) == 50
    resumo = avaliar("gabarito")
    assert resumo["acertos"] == 50 and resumo["acuracia"] == 1.0
    assert (tmp_path / "resultados" / "avaliacao_gabarito.json").exists()


def test_gabarito_nao_tem_perguntas_repetidas():
    _, perguntas = carregar_gabarito()
    assert len({p["pergunta"] for p in perguntas}) == len(perguntas)
