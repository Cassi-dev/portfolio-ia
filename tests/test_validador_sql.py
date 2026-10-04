import pytest

from validador_seguranca import validar_seguranca_sql

PERMITIDAS = [
    "SELECT * FROM pedidos",
    "SELECT nome, cidade FROM clientes WHERE estado = 'RS';",
    "SELECT c.nome, SUM(p.valor_total) FROM clientes c JOIN pedidos p ON c.id = p.cliente_id GROUP BY c.id",
    "WITH t AS (SELECT cliente_id, SUM(valor_total) s FROM pedidos GROUP BY 1) SELECT * FROM t",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT n FROM r",
    "SELECT nome FROM clientes UNION SELECT nome FROM produtos",
    "SELECT nome FROM clientes UNION ALL SELECT nome FROM produtos ORDER BY 1",
    "SELECT nome FROM clientes EXCEPT SELECT nome FROM produtos",
    "SELECT * FROM (SELECT id FROM clientes) t",
    "```sql\nSELECT 1\n```",
]

BLOQUEADAS = [
    "DROP TABLE clientes;",
    "DELETE FROM pedidos WHERE id = 1;",
    "UPDATE pedidos SET valor_total = 0",
    "INSERT INTO clientes (nome) VALUES ('x')",
    "ALTER TABLE clientes ADD COLUMN x TEXT",
    "CREATE TABLE t (id INTEGER)",
    "SELECT 1; DROP TABLE clientes",
    "SELECT 1 /* ; */ ; DROP TABLE clientes",
    "SELECT 1; SELECT 2",
    "PRAGMA table_info(clientes)",
    "ATTACH DATABASE 'x.db' AS x",
    "EXPLAIN SELECT 1",
    "VACUUM",
    "SELECT load_extension('x')",
    "SELECT readfile('/etc/passwd')",
    "SELECT * FROM clientes WHERE id IN (SELECT writefile('a', 'b'))",
    "",
    "   ",
]


@pytest.mark.parametrize("sql", PERMITIDAS)
def test_consultas_de_leitura_passam(sql):
    valido, msg, _ = validar_seguranca_sql(sql)
    assert valido, msg


@pytest.mark.parametrize("sql", BLOQUEADAS)
def test_comandos_perigosos_sao_bloqueados(sql):
    valido, _, _ = validar_seguranca_sql(sql)
    assert not valido


def test_mensagem_de_bloqueio_diz_qual_comando_foi_pego():
    _, msg, _ = validar_seguranca_sql("DROP TABLE clientes")
    assert "DROP" in msg and "BLOQUEIO DE SEGURANÇA" in msg
