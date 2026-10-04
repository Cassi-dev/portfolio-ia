import json
import sys
from datetime import date

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from pydantic import BaseModel, Field

from banco_dados import executar_consulta, obter_schema_ddl, obter_valores_categoricos
from core.config import MODELO_GEMINI
from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, criar_cliente, gerar_estruturado
from validador_seguranca import validar_seguranca_sql

MODO_IA = f"Gemini ({MODELO_GEMINI})"

# ==========================================================
# PROCESSO 3: FEW-SHOT PROMPTING & CICLO DE AUTO-CORREÇÃO
# ==========================================================


class ConsultaSQL(BaseModel):
    sql: str = Field(description="Uma única consulta SELECT do SQLite, sem markdown e sem explicações")


EXEMPLOS_FEW_SHOT = """
Exemplo 1:
Pergunta: "Qual o faturamento total por canal de venda?"
SQL: SELECT canal_venda, ROUND(SUM(valor_total), 2) AS faturamento_total FROM pedidos GROUP BY canal_venda ORDER BY faturamento_total DESC;

Exemplo 2:
Pergunta: "Quais os 3 clientes que mais faturaram?"
SQL: SELECT c.nome, c.cidade, ROUND(SUM(p.valor_total), 2) AS total_comprado FROM clientes c JOIN pedidos p ON c.id = p.cliente_id GROUP BY c.id ORDER BY total_comprado DESC LIMIT 3;

Exemplo 3:
Pergunta: "Quais produtos têm estoque abaixo de 50 unidades?"
SQL: SELECT nome, categoria, estoque, preco_venda FROM produtos WHERE estoque < 50 ORDER BY estoque ASC;

Exemplo 4:
Pergunta: "Qual o ticket médio dos pedidos por segmento de cliente?"
SQL: SELECT c.segmento, COUNT(p.id) AS total_pedidos, ROUND(AVG(p.valor_total), 2) AS ticket_medio FROM clientes c JOIN pedidos p ON c.id = p.cliente_id GROUP BY c.segmento ORDER BY ticket_medio DESC;
"""


def montar_prompt_sql(pergunta, schema_ddl, valores, hoje, erro_anterior=None, sql_anterior=None):
    instrucao_correcao = ""
    if erro_anterior and sql_anterior:
        instrucao_correcao = (
            "\nATENÇÃO: a tentativa anterior falhou no SQLite.\n"
            f"Consulta que falhou: {sql_anterior}\nMensagem de erro: {erro_anterior}\n"
            "CORRIJA o SQL, ajustando nomes de colunas ou tabelas ao schema fornecido.\n"
        )

    valores_txt = "\n".join(f"- {coluna}: {json.dumps(v, ensure_ascii=False)}" for coluna, v in valores.items())
    return f"""Você é um Administrador de Banco de Dados e Especialista SQL sênior em SQLite.
Converta a pergunta em linguagem natural em uma consulta SQL precisa, eficiente e segura.

REGRAS OBRIGATÓRIAS:
1. É ESTRITAMENTE PROIBIDO gerar comandos de alteração de dados (DROP, DELETE, UPDATE, INSERT, ALTER). Gere APENAS uma consulta de leitura (SELECT).
2. Use APENAS as tabelas e colunas definidas no SCHEMA abaixo. Não invente nomes de colunas.
3. Para agregações de valor financeiro, use ROUND(..., 2).
4. Compare colunas de texto usando EXATAMENTE os valores listados em VALORES POSSÍVEIS.
5. A data de hoje é {hoje.isoformat()}. Use-a para "hoje", "mês passado", "últimos 30 dias" etc. (datas estão em YYYY-MM-DD; use strftime/date do SQLite).

SCHEMA DO BANCO DE DADOS (SQLite):
{schema_ddl}

VALORES POSSÍVEIS DAS COLUNAS DE TEXTO CATEGÓRICAS:
{valores_txt}

EXEMPLOS DE PADRÃO (FEW-SHOT):
{EXEMPLOS_FEW_SHOT}
{instrucao_correcao}
PERGUNTA DO USUÁRIO:
"{pergunta}"
"""


def gerar_sql_com_gemini(client, pergunta, schema_ddl, valores, hoje, erro_anterior=None, sql_anterior=None):
    prompt = montar_prompt_sql(pergunta, schema_ddl, valores, hoje, erro_anterior, sql_anterior)
    return gerar_estruturado(client, prompt, ConsultaSQL, temperatura=0.0).sql


def responder_offline(pergunta, motivo):
    """Modo sem IA: só reconhece 3 famílias de pergunta. Fora delas, avisa que a resposta NÃO corresponde."""
    p = pergunta.lower()
    reconhecida = True
    if "canal" in p:
        sql = "SELECT canal_venda, ROUND(SUM(valor_total), 2) AS total FROM pedidos GROUP BY canal_venda ORDER BY total DESC;"
    elif "cliente" in p or "maiores" in p:
        sql = "SELECT c.nome, c.cidade, ROUND(SUM(p.valor_total), 2) AS total FROM clientes c JOIN pedidos p ON c.id = p.cliente_id GROUP BY c.id ORDER BY total DESC LIMIT 5;"
    elif "estoque" in p or "baixo" in p:
        sql = "SELECT nome, categoria, estoque, preco_venda FROM produtos WHERE estoque < 50 ORDER BY estoque ASC;"
    else:
        reconhecida = False
        sql = "SELECT p.id, c.nome AS cliente, p.data_pedido, p.valor_total, p.canal_venda FROM pedidos p JOIN clientes c ON p.cliente_id = c.id ORDER BY p.data_pedido DESC LIMIT 10;"

    valido, msg_sec, sql_limpo = validar_seguranca_sql(sql)
    resultado = executar_consulta(sql_limpo)
    motivo = f"{motivo}: o modo offline só reconhece perguntas sobre canal, cliente e estoque"
    if not reconhecida:
        motivo += ". Sua pergunta não bateu com nenhuma delas, então a consulta abaixo (últimos 10 pedidos) NÃO responde ao que foi perguntado"
    return {
        "sql": sql_limpo,
        "seguro": valido,
        "msg_seguranca": msg_sec,
        "df": resultado.df,
        "truncado": resultado.truncado,
        "erro_banco": resultado.erro,
        "tentativas": 1,
        "modo": "Offline (Heurístico)",
        "degradado": True,
        "motivo_degradado": motivo,
        "pergunta_reconhecida": reconhecida,
    }


def processar_pergunta_com_ciclo_correcao(pergunta, api_key="", max_tentativas=2, client=None, hoje=None):
    """
    Ciclo completo de Text-to-SQL:
    Gera (saída estruturada) -> Valida (AST) -> Executa (somente leitura) -> Auto-corrige se der erro.
    """
    hoje = hoje or date.today()

    if client is None and api_key.strip():
        try:
            client = criar_cliente(api_key)
        except FalhaLLM as e:
            return responder_offline(pergunta, motivo_falha(e))
    if client is None:
        return responder_offline(pergunta, MOTIVO_SEM_CHAVE)

    schema = obter_schema_ddl()
    valores = obter_valores_categoricos()

    tentativa_atual = 1
    erro_anterior = None
    sql_anterior = None
    base = {"modo": MODO_IA, "degradado": False, "motivo_degradado": None, "truncado": False}

    while tentativa_atual <= max_tentativas:
        try:
            sql_candidato = gerar_sql_com_gemini(client, pergunta, schema, valores, hoje, erro_anterior, sql_anterior)
        except RespostaInvalida:
            return responder_offline(pergunta, MOTIVO_FORMATO)
        except FalhaLLM as e:
            return responder_offline(pergunta, motivo_falha(e))

        valido, msg_sec, sql_limpo = validar_seguranca_sql(sql_candidato)
        if not valido:
            return {**base, "sql": sql_candidato, "seguro": False, "msg_seguranca": msg_sec, "df": None,
                    "erro_banco": None, "tentativas": tentativa_atual}

        resultado = executar_consulta(sql_limpo)
        if not resultado.erro:
            return {**base, "sql": sql_limpo, "seguro": True, "msg_seguranca": msg_sec, "df": resultado.df,
                    "truncado": resultado.truncado, "erro_banco": None, "tentativas": tentativa_atual}

        erro_anterior, sql_anterior = resultado.erro, sql_limpo
        tentativa_atual += 1

    return {**base, "sql": sql_anterior, "seguro": True,
            "msg_seguranca": "Aprovado pelo validador, mas o banco retornou erro persistente.",
            "df": None, "erro_banco": erro_anterior, "tentativas": tentativa_atual - 1}


if __name__ == "__main__":
    res = processar_pergunta_com_ciclo_correcao("Quais os clientes com maior faturamento?")
    print(f"SQL Gerado:\n{res['sql']}")
    print(f"Segurança: {res['seguro']} ({res['msg_seguranca']})")
    print(f"\nResultado da Consulta (Primeiras linhas):\n{res['df']}")
