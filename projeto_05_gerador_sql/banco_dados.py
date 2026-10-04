import os
import random
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

import pandas as pd

CAMINHO_BANCO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tacto_negocios.db")

LIMITE_LINHAS = 1000
TEMPO_MAXIMO_S = 5.0
FUNCOES_BLOQUEADAS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}

# ==========================================================
# DADOS DE EXEMPLO: determinísticos (seed fixa) e consistentes
# (pedidos.valor_total é SEMPRE a soma dos itens do pedido)
# ==========================================================

DATA_INICIO_PEDIDOS = date(2026, 1, 15)
DATA_FIM_PEDIDOS = date(2026, 9, 18)

CLIENTES_BASE = [
    ("Bar Exemplo", "Porto Alegre", "RS", "Gastronomia", "2026-01-15"),
    ("Coquetelaria Exemplo", "Porto Alegre", "RS", "Bares", "2026-02-10"),
    ("Restaurante Exemplo", "Caxias do Sul", "RS", "Alta Gastronomia", "2026-03-05"),
    ("Consultoria Fit Exemplo", "São Paulo", "SP", "Fitness", "2026-03-20"),
    ("Clínica Exemplo", "Curitiba", "PR", "Saúde", "2026-04-12"),
    ("Hamburgueria La Mafia", "São Paulo", "SP", "Gastronomia", "2026-05-01"),
    ("Café & Confeitaria Bela Vista", "Gramado", "RS", "Cafeteria", "2026-05-18"),
    ("CrossFit Box Alpha", "Rio de Janeiro", "RJ", "Fitness", "2026-06-02"),
]
PREFIXOS = ["Bar", "Restaurante", "Cantina", "Bistrô", "Pizzaria", "Academia", "Studio", "Clínica", "Empório", "Cervejaria"]
SOBRENOMES = ["do Zé", "da Vila", "Central", "Gourmet", "Premium", "Express", "do Porto", "Sabor & Arte", "Nova Era", "Bom Gosto"]
LOCAIS = [
    ("Porto Alegre", "RS"), ("Caxias do Sul", "RS"), ("Gramado", "RS"), ("São Paulo", "SP"), ("Campinas", "SP"),
    ("Curitiba", "PR"), ("Florianópolis", "SC"), ("Rio de Janeiro", "RJ"), ("Belo Horizonte", "MG"), ("Salvador", "BA"),
]
SEGMENTOS = ["Gastronomia", "Bares", "Alta Gastronomia", "Fitness", "Saúde", "Cafeteria"]

PRODUTOS = [
    ("Chopp Artesanal IPA 500ml", "Bebidas", 24.00, 8.50, 150),
    ("Drink Autoral Smoky Negroni", "Bebidas", 38.00, 12.00, 80),
    ("Burguer Artesanal Costela", "Pratos", 46.00, 18.00, 60),
    ("Tábua de Queijos da Serra", "Petiscos", 68.00, 28.00, 40),
    ("Sobremesa Torta de Pistache", "Sobremesas", 28.00, 9.00, 30),
    ("Mensalidade Consultoria VIP", "Serviços", 299.00, 30.00, 999),
    ("Plano Trimestral PWA", "Serviços", 750.00, 50.00, 999),
    ("Café Especial Filtrado", "Bebidas", 14.00, 3.50, 200),
    ("Risoto de Cogumelos", "Pratos", 62.00, 21.00, 45),
    ("Porção de Batata Rústica", "Petiscos", 32.00, 9.50, 120),
    ("Cheesecake de Frutas Vermelhas", "Sobremesas", 26.00, 8.00, 25),
    ("Vinho Tinto Reserva", "Bebidas", 129.00, 55.00, 36),
    ("Setup Cardápio Digital", "Serviços", 1490.00, 120.00, 999),
    ("Combo Executivo", "Pratos", 39.90, 14.00, 90),
]
CANAIS = [("WhatsApp Direto", 30), ("Balcão", 25), ("PWA TACTO", 20), ("Site Institucional", 10), ("Delivery Próprio", 15)]
STATUS = [("Concluído", 88), ("Cancelado", 8), ("Pendente", 4)]
N_CLIENTES = 40
N_PEDIDOS = 400


def _sortear(rng, opcoes):
    return rng.choices([o for o, _ in opcoes], weights=[p for _, p in opcoes])[0]


def gerar_dados(seed=42):
    """Devolve (clientes, produtos, pedidos, itens) prontos para inserir; mesma seed, mesmos dados."""
    rng = random.Random(seed)

    clientes = list(CLIENTES_BASE)
    nomes_usados = {c[0] for c in clientes}
    while len(clientes) < N_CLIENTES:
        nome = f"{rng.choice(PREFIXOS)} {rng.choice(SOBRENOMES)}"
        if nome in nomes_usados:
            continue
        nomes_usados.add(nome)
        cidade, estado = rng.choice(LOCAIS)
        cadastro = DATA_INICIO_PEDIDOS + timedelta(days=rng.randint(0, 200))
        clientes.append((nome, cidade, estado, rng.choice(SEGMENTOS), cadastro.isoformat()))

    dias = (DATA_FIM_PEDIDOS - DATA_INICIO_PEDIDOS).days
    pedidos, itens = [], []
    for pedido_id in range(1, N_PEDIDOS + 1):
        cliente_id = rng.randint(1, N_CLIENTES)
        dia = DATA_INICIO_PEDIDOS + timedelta(days=rng.randint(0, dias))
        linhas = []
        for produto_id in rng.sample(range(1, len(PRODUTOS) + 1), rng.randint(1, 4)):
            preco = PRODUTOS[produto_id - 1][2]
            servico = PRODUTOS[produto_id - 1][1] == "Serviços"
            linhas.append((pedido_id, produto_id, 1 if servico else rng.randint(1, 20), preco))
        total = round(sum(q * p for _, _, q, p in linhas), 2)
        pedidos.append((cliente_id, dia.isoformat(), total, _sortear(rng, CANAIS), _sortear(rng, STATUS)))
        itens.extend(linhas)
    return clientes, PRODUTOS, pedidos, itens


def inicializar_banco(recriar=False):
    """Cria e popula o SQLite de exemplo. `recriar=True` apaga as tabelas antes (demo, dados sintéticos)."""
    conn = sqlite3.connect(CAMINHO_BANCO)
    cursor = conn.cursor()

    if recriar:
        for tabela in ("itens_pedido", "pedidos", "produtos", "clientes"):
            cursor.execute(f"DROP TABLE IF EXISTS {tabela};")

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        cidade TEXT NOT NULL,
        estado TEXT NOT NULL,
        segmento TEXT NOT NULL,
        data_cadastro DATE NOT NULL
    );
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        categoria TEXT NOT NULL,
        preco_venda REAL NOT NULL,
        preco_custo REAL NOT NULL,
        estoque INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        data_pedido DATE NOT NULL,
        valor_total REAL NOT NULL,
        canal_venda TEXT NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id)
    );
    CREATE TABLE IF NOT EXISTS itens_pedido (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER NOT NULL,
        produto_id INTEGER NOT NULL,
        quantidade INTEGER NOT NULL,
        preco_unitario REAL NOT NULL,
        FOREIGN KEY (pedido_id) REFERENCES pedidos(id),
        FOREIGN KEY (produto_id) REFERENCES produtos(id)
    );
    """)

    if cursor.execute("SELECT COUNT(*) FROM clientes;").fetchone()[0] == 0:
        clientes, produtos, pedidos, itens = gerar_dados()
        cursor.executemany("INSERT INTO clientes (nome, cidade, estado, segmento, data_cadastro) VALUES (?, ?, ?, ?, ?);", clientes)
        cursor.executemany("INSERT INTO produtos (nome, categoria, preco_venda, preco_custo, estoque) VALUES (?, ?, ?, ?, ?);", produtos)
        cursor.executemany("INSERT INTO pedidos (cliente_id, data_pedido, valor_total, canal_venda, status) VALUES (?, ?, ?, ?, ?);", pedidos)
        cursor.executemany("INSERT INTO itens_pedido (pedido_id, produto_id, quantidade, preco_unitario) VALUES (?, ?, ?, ?);", itens)
        conn.commit()

    conn.close()
    return CAMINHO_BANCO


def obter_schema_ddl():
    """
    Extrai o DDL exato (CREATE TABLE) de todas as tabelas.
    'Mande o schema inteiro em toda chamada. Modelo sem schema chuta nome de coluna com uma confiança impressionante.'
    """
    conn = sqlite3.connect(CAMINHO_BANCO)
    tabelas = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';").fetchall()
    conn.close()
    return "\n\n".join(t[0] for t in tabelas if t[0])


def obter_valores_categoricos(max_distintos=12):
    """
    Valores distintos das colunas de texto com poucos valores (canal_venda, status, categoria...).
    Sem isso o modelo chuta literais ('PWA' em vez de 'PWA TACTO') e a consulta volta vazia sem erro.
    """
    conn = sqlite3.connect(CAMINHO_BANCO)
    try:
        valores = {}
        tabelas = [t[0] for t in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for tabela in tabelas:
            for _, coluna, tipo, *_ in conn.execute(f'PRAGMA table_info("{tabela}")').fetchall():
                if tipo.upper() != "TEXT":
                    continue
                distintos = [r[0] for r in conn.execute(f'SELECT DISTINCT "{coluna}" FROM "{tabela}" LIMIT {max_distintos + 1}')]
                if 0 < len(distintos) <= max_distintos:
                    valores[f"{tabela}.{coluna}"] = sorted(distintos)
        return valores
    finally:
        conn.close()


class ResultadoConsulta(NamedTuple):
    df: pd.DataFrame
    erro: str | None
    truncado: bool


def _autorizador(acao, arg1, arg2, banco, gatilho):
    """2ª trava: o próprio SQLite só deixa ler. Escrita, PRAGMA, ATTACH e funções perigosas são negados."""
    if acao in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if acao == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() not in FUNCOES_BLOQUEADAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def conectar_somente_leitura(caminho=None, tempo_maximo=TEMPO_MAXIMO_S):
    uri = Path(caminho or CAMINHO_BANCO).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_autorizador)
    inicio = time.monotonic()
    conn.set_progress_handler(lambda: 1 if time.monotonic() - inicio > tempo_maximo else 0, 10_000)
    return conn


def executar_consulta(sql_query, limite=LIMITE_LINHAS, tempo_maximo=TEMPO_MAXIMO_S, caminho=None):
    """Executa em conexão somente leitura, com teto de linhas e de tempo. Nunca levanta exceção."""
    try:
        conn = conectar_somente_leitura(caminho, tempo_maximo)
    except sqlite3.Error as e:
        return ResultadoConsulta(pd.DataFrame(), f"Não foi possível abrir o banco: {e}", False)
    try:
        cursor = conn.execute(sql_query)
        linhas = cursor.fetchmany(limite + 1)
        colunas = [d[0] for d in cursor.description] if cursor.description else []
        truncado = len(linhas) > limite
        return ResultadoConsulta(pd.DataFrame(linhas[:limite], columns=colunas), None, truncado)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            return ResultadoConsulta(pd.DataFrame(), f"A consulta passou de {tempo_maximo:g}s e foi interrompida.", False)
        return ResultadoConsulta(pd.DataFrame(), str(e), False)
    except Exception as e:
        return ResultadoConsulta(pd.DataFrame(), str(e), False)
    finally:
        conn.close()


if __name__ == "__main__":
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    banco = inicializar_banco(recriar="--recriar" in sys.argv)
    print(f"Banco pronto: {banco}")
    print("\n--- VALORES CATEGÓRICOS ---")
    for coluna, valores in obter_valores_categoricos().items():
        print(f"{coluna}: {valores}")
