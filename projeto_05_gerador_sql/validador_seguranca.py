import sys
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import sqlglot
from sqlglot import exp

# ==========================================================
# PROCESSO 2: O CRIVO DE SEGURANÇA (1ª DE 2 TRAVAS)
# 'Só SELECT. Sempre. Um DROP TABLE gerado por LLM encerra o projeto e talvez o emprego.'
# Esta trava analisa a AST antes de tocar no banco. A 2ª trava (banco_dados.py) é o próprio
# SQLite: conexão somente leitura + autorizador + limite de tempo e de linhas. Uma não depende da outra.
# ==========================================================

_NOMES_PROIBIDOS = (
    "Drop", "Delete", "Update", "Insert", "Alter", "Create", "Command", "TruncateTable", "Pragma",
    "Attach", "Detach", "Merge", "Transaction", "Commit", "Rollback", "Use", "Copy",
)
NOS_PROIBIDOS = tuple(getattr(exp, nome) for nome in _NOMES_PROIBIDOS if hasattr(exp, nome))

FUNCOES_PROIBIDAS = {"LOAD_EXTENSION", "READFILE", "WRITEFILE", "EDIT", "FTS3_TOKENIZER"}


def limpar_sql(sql_code):
    """Remove cerca markdown e o prefixo 'sql', que alguns modelos ainda acrescentam."""
    sql_limpo = sql_code.strip()
    if sql_limpo.startswith("`"):
        sql_limpo = "\n".join(l for l in sql_limpo.split("\n") if not l.startswith("`")).strip()
    if sql_limpo.lower().startswith("sql"):
        sql_limpo = sql_limpo[3:].strip()
    return sql_limpo


def _bloqueio(motivo):
    return (
        "[BLOQUEIO DE SEGURANÇA NA MARRA]\n"
        f"{motivo}\n"
        "Por motivos de segurança e integridade do banco de dados, "
        "APENAS uma consulta de leitura (SELECT) por vez é permitida."
    )


def validar_seguranca_sql(sql_code):
    """Devolve (aprovado, mensagem, sql_limpo). Aceita SELECT, WITH (CTE) e UNION/EXCEPT/INTERSECT."""
    if not sql_code or not sql_code.strip():
        return False, "Comando SQL vazio.", None

    sql_limpo = limpar_sql(sql_code)

    try:
        comandos = [c for c in sqlglot.parse(sql_limpo, read="sqlite") if c is not None]
    except Exception as e:
        return False, f"Erro de sintaxe SQL detectado pelo sqlglot: {e}", sql_limpo

    if not comandos:
        return False, "Não foi possível interpretar a sintaxe do comando SQL.", sql_limpo

    for comando in comandos:
        if not isinstance(comando, exp.Query):
            return False, _bloqueio(f"Comando perigoso '{type(comando).__name__.upper()}' detectado!"), sql_limpo

        for no in comando.walk():
            if isinstance(no, NOS_PROIBIDOS):
                return False, _bloqueio(f"Operação de escrita ou administração '{type(no).__name__.upper()}' aninhada na consulta."), sql_limpo
            if isinstance(no, exp.Func):
                nome = (no.name if isinstance(no, exp.Anonymous) else no.sql_name()).upper()
                if nome in FUNCOES_PROIBIDAS:
                    return False, _bloqueio(f"Função '{nome}' não é permitida."), sql_limpo

    if len(comandos) > 1:
        return False, _bloqueio("Foram enviados vários comandos de uma vez."), sql_limpo

    return True, "Consulta validada e aprovada pelo crivo de segurança.", sql_limpo


if __name__ == "__main__":
    for sql in ["SELECT nome, cidade FROM clientes WHERE estado = 'RS';", "DROP TABLE clientes;", "DELETE FROM pedidos WHERE id = 1;"]:
        valido, msg, _ = validar_seguranca_sql(sql)
        print(f"{valido} | {sql}\n   {msg.splitlines()[0]}")
