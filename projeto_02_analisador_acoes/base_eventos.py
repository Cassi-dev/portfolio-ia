"""
Base de eventos do monitor (SQLite local): o que faz o projeto deixar de ser uma consulta avulsa e virar
um monitor. Sem isto não existe "o que mudou desde a semana passada" nem pontuação incremental.

Duas camadas de deduplicação, porque a mesma notícia volta em toda coleta e sai em vários portais:
  1. identidade exata: hash de (alvo, tipo, título normalizado) — a mesma manchete nunca entra duas vezes;
  2. quase-duplicata: similaridade de Jaccard contra o que já está guardado na janela — "Petrobras anuncia
     dividendos" do InfoMoney e do Valor contam como um evento só.

É a camada 2 que faz a economia valer: sem ela, cada portal repetindo a notícia seria uma pontuação paga.
"""
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from cardapio import chave_do_item
from deteccao import normalizar

BASE = Path(__file__).resolve().parent
CAMINHO_PADRAO = BASE / "monitor.db"
JANELA_DEDUP_DIAS = 30
LIMIAR_SIMILARIDADE = 0.60

ESQUEMA = """
CREATE TABLE IF NOT EXISTS eventos (
    id            TEXT PRIMARY KEY,
    cliente_id    TEXT NOT NULL,
    alvo_id       TEXT NOT NULL,
    tipo          TEXT NOT NULL,
    titulo        TEXT NOT NULL,
    fonte         TEXT,
    link          TEXT,
    data          TEXT NOT NULL,
    publicado_em  TEXT,
    visto_em      TEXT NOT NULL,
    ciclo_id      INTEGER,
    score         REAL,
    classificacao TEXT,
    motivo        TEXT,
    motor         TEXT,
    pontuado_em   TEXT
);
CREATE INDEX IF NOT EXISTS idx_eventos_alvo ON eventos (cliente_id, alvo_id, data);
CREATE INDEX IF NOT EXISTS idx_eventos_sem_score ON eventos (cliente_id, score);

CREATE TABLE IF NOT EXISTS ciclos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id TEXT NOT NULL,
    inicio     TEXT NOT NULL,
    fim        TEXT,
    coletados  INTEGER DEFAULT 0,
    novos      INTEGER DEFAULT 0,
    pontuados  INTEGER DEFAULT 0,
    erros      TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ciclos_cliente ON ciclos (cliente_id, id);

-- Uma captura = uma foto/PDF de cardápio já lido. A imagem NÃO é guardada (é material do cliente):
-- fica só a tabela extraída e o nome do arquivo de origem.
CREATE TABLE IF NOT EXISTS capturas_cardapio (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id      TEXT NOT NULL,
    alvo_id         TEXT NOT NULL,
    data            TEXT NOT NULL,
    origem          TEXT,
    estabelecimento TEXT,
    observacoes     TEXT,
    criado_em       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capturas ON capturas_cardapio (cliente_id, alvo_id, data);

CREATE TABLE IF NOT EXISTS itens_cardapio (
    captura_id  INTEGER NOT NULL,
    nome        TEXT NOT NULL,
    chave       TEXT NOT NULL,
    preco       REAL,
    preco_texto TEXT,
    categoria   TEXT,
    descricao   TEXT
);
CREATE INDEX IF NOT EXISTS idx_itens_captura ON itens_cardapio (captura_id);

-- Um relatório (Radar) por período, com estado: nada vai para o cliente sem passar por "aprovado".
CREATE TABLE IF NOT EXISTS relatorios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id    TEXT NOT NULL,
    periodo_de    TEXT,
    periodo_ate   TEXT,
    corte         TEXT,
    gerado_em     TEXT NOT NULL,
    estado        TEXT NOT NULL,
    arquivo       TEXT,
    itens         INTEGER DEFAULT 0,
    notas         TEXT DEFAULT '',
    atualizado_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_relatorios ON relatorios (cliente_id, id);

-- Rótulo humano por evento: valia a pena mostrar ao cliente? É o que permite medir a taxa de ruído.
-- A maior parte vem de graça da revisão: o que você descarta vira 0, o que sobrevive a um Radar aprovado vira 1.
CREATE TABLE IF NOT EXISTS rotulos (
    evento_id   TEXT PRIMARY KEY,
    relevante   INTEGER NOT NULL,
    motivo      TEXT DEFAULT '',
    origem      TEXT NOT NULL,
    rotulado_em TEXT NOT NULL
);
"""

# Colunas acrescentadas depois da primeira versão: um monitor.db que já existe precisa ganhá-las.
COLUNAS_NOVAS = {
    "eventos": [("excluido", "INTEGER DEFAULT 0"), ("motivo_exclusao", "TEXT")],
    # o que foi revisado e aprovado, congelado em JSON: o e-mail manda isso, não uma nova leitura da base
    "relatorios": [("resumo", "TEXT DEFAULT ''")],
}
ESTADOS = ("rascunho", "aprovado", "enviado", "descartado")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def id_do_evento(alvo_id: str, tipo: str, titulo: str) -> str:
    """Identidade estável: o mesmo título, do mesmo alvo, é sempre o mesmo evento (mesmo em outra execução)."""
    return sha256(f"{alvo_id}|{tipo}|{normalizar(titulo)}".encode("utf-8")).hexdigest()[:16]


class BaseEventos:
    """Use como context manager (`with BaseEventos(...) as base:`) ou chame fechar() no fim."""

    def __init__(self, caminho=None):
        self.caminho = str(caminho or CAMINHO_PADRAO)
        # check_same_thread=False porque o Streamlit reexecuta o script em outra thread e guarda a conexão
        # entre execuções; o acesso continua serializado (uma execução por vez), então não há concorrência real.
        self.conn = sqlite3.connect(self.caminho, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(ESQUEMA)
        self._migrar()
        self.conn.commit()

    def _migrar(self) -> None:
        """Acrescenta colunas que surgiram depois, para um banco antigo continuar servindo."""
        for tabela, colunas in COLUNAS_NOVAS.items():
            existentes = {linha["name"] for linha in self.conn.execute(f"PRAGMA table_info({tabela})")}
            for nome, tipo in colunas:
                if nome not in existentes:
                    self.conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def fechar(self):
        self.conn.close()

    # --- ciclos -------------------------------------------------------------------------------------------------

    def abrir_ciclo(self, cliente_id: str) -> int:
        with closing(self.conn.cursor()) as cur:
            cur.execute("INSERT INTO ciclos (cliente_id, inicio) VALUES (?, ?)", (cliente_id, agora()))
            self.conn.commit()
            return cur.lastrowid

    def fechar_ciclo(self, ciclo_id: int, coletados: int, novos: int, pontuados: int, erros=()) -> None:
        self.conn.execute(
            "UPDATE ciclos SET fim = ?, coletados = ?, novos = ?, pontuados = ?, erros = ? WHERE id = ?",
            (agora(), coletados, novos, pontuados, " | ".join(erros), ciclo_id),
        )
        self.conn.commit()

    def observando_desde(self, cliente_id: str):
        """
        Data do primeiro ciclo deste cliente. Antes dela não havia observação, então o que a primeira busca
        trouxe de histórico não serve de linha de base para detectar pico (ver pico_de_volume).
        """
        linha = self.conn.execute("SELECT MIN(inicio) inicio FROM ciclos WHERE cliente_id = ?", (cliente_id,)).fetchone()
        return date.fromisoformat(linha["inicio"][:10]) if linha and linha["inicio"] else None

    def quantos_ciclos(self, cliente_id: str) -> int:
        return self.conn.execute("SELECT COUNT(*) n FROM ciclos WHERE cliente_id = ?", (cliente_id,)).fetchone()["n"]

    def ciclos(self, cliente_id=None, limite: int = 20) -> list:
        sql = "SELECT * FROM ciclos"
        parametros = []
        if cliente_id:
            sql += " WHERE cliente_id = ?"
            parametros.append(cliente_id)
        sql += " ORDER BY id DESC LIMIT ?"
        parametros.append(limite)
        return [dict(linha) for linha in self.conn.execute(sql, parametros)]

    # --- eventos ------------------------------------------------------------------------------------------------

    def registrar_eventos(self, cliente_id: str, alvo_id: str, tipo: str, itens: list, ciclo_id: int,
                          hoje: date = None, janela_dias: int = JANELA_DEDUP_DIAS,
                          limiar: float = LIMIAR_SIMILARIDADE, deduplicador=None) -> list:
        """
        Guarda o que ainda não existe e devolve só os eventos NOVOS (já no formato de leitura).
        Sem `deduplicador`, usa palavras em comum — barato, mas que mede 0 de 21 em repetição real
        (ver deduplicacao.py). O ciclo passa o de embedding.
        """
        if deduplicador is None:
            from deduplicacao import Deduplicador
            deduplicador = Deduplicador("tokens", limiar)
        hoje = hoje or datetime.now(timezone.utc).date()
        corte = (hoje - timedelta(days=janela_dias)).isoformat()
        conhecidos = [
            linha["titulo"] for linha in self.conn.execute(
                "SELECT titulo FROM eventos WHERE alvo_id = ? AND tipo = ? AND data >= ?", (alvo_id, tipo, corte)
            )
        ]
        visto_em, novos = agora(), []
        for item in itens:
            titulo = str(item.get("titulo", "")).strip()
            if not titulo:
                continue
            identificador = id_do_evento(alvo_id, tipo, titulo)
            if self.conn.execute("SELECT 1 FROM eventos WHERE id = ?", (identificador,)).fetchone():
                continue
            if deduplicador.e_duplicata(titulo, conhecidos):
                continue
            evento = {
                "id": identificador, "cliente_id": cliente_id, "alvo_id": alvo_id, "tipo": tipo, "titulo": titulo,
                "fonte": item.get("fonte", ""), "link": item.get("link", ""),
                "data": item.get("data") or hoje.isoformat(), "publicado_em": item.get("publicado_em", ""),
                "visto_em": visto_em, "ciclo_id": ciclo_id, "score": None, "classificacao": None,
                "motivo": None, "motor": None, "pontuado_em": None,
            }
            self.conn.execute(
                "INSERT INTO eventos (id, cliente_id, alvo_id, tipo, titulo, fonte, link, data, publicado_em,"
                " visto_em, ciclo_id) VALUES (:id, :cliente_id, :alvo_id, :tipo, :titulo, :fonte, :link, :data,"
                " :publicado_em, :visto_em, :ciclo_id)", evento,
            )
            conhecidos.append(titulo)          # o próprio lote também não pode repetir
            novos.append(evento)
        self.conn.commit()
        return novos

    def eventos(self, cliente_id: str, alvo_id=None, desde: date = None, tipo=None,
                incluir_excluidos: bool = False) -> list:
        """Sem `incluir_excluidos`, o que a revisão descartou não volta: nem no relatório, nem nos detectores."""
        sql = "SELECT * FROM eventos WHERE cliente_id = ?"
        parametros = [cliente_id]
        if not incluir_excluidos:
            sql += " AND COALESCE(excluido, 0) = 0"
        for coluna, valor in (("alvo_id", alvo_id), ("tipo", tipo)):
            if valor:
                sql += f" AND {coluna} = ?"
                parametros.append(valor)
        if desde:
            sql += " AND data >= ?"
            parametros.append(desde.isoformat())
        return [dict(linha) for linha in self.conn.execute(sql + " ORDER BY data DESC, id", parametros)]

    def sem_pontuacao(self, cliente_id: str, limite: int = 500) -> list:
        """O coração da economia: só estes vão para a IA, em vez do lote inteiro a cada execução."""
        return [dict(linha) for linha in self.conn.execute(
            "SELECT * FROM eventos WHERE cliente_id = ? AND score IS NULL AND COALESCE(excluido, 0) = 0"
            " ORDER BY data DESC LIMIT ?", (cliente_id, limite),
        )]

    def gravar_pontuacoes(self, itens: list) -> int:
        """Grava score/classificação/motor dos dicts já pontuados (os mesmos que saíram de sem_pontuacao)."""
        quando = agora()
        linhas = [
            (i.get("score"), i.get("classificacao"), i.get("motivo"), i.get("motor"), quando, i["id"])
            for i in itens if i.get("score") is not None
        ]
        self.conn.executemany(
            "UPDATE eventos SET score = ?, classificacao = ?, motivo = ?, motor = ?, pontuado_em = ? WHERE id = ?",
            linhas,
        )
        self.conn.commit()
        return len(linhas)

    # --- cardápios ----------------------------------------------------------------------------------------------

    def guardar_cardapio(self, cliente_id: str, alvo_id: str, data: str, origem: str, lido: dict) -> int:
        """Guarda uma captura já lida (ver cardapio.ler_cardapio) e devolve o id dela."""
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "INSERT INTO capturas_cardapio (cliente_id, alvo_id, data, origem, estabelecimento, observacoes,"
                " criado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cliente_id, alvo_id, data, origem, lido.get("estabelecimento", ""), lido.get("observacoes", ""), agora()),
            )
            captura_id = cur.lastrowid
            cur.executemany(
                "INSERT INTO itens_cardapio (captura_id, nome, chave, preco, preco_texto, categoria, descricao)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(captura_id, i["nome"], chave_do_item(i["nome"]), i.get("preco"), i.get("preco_texto", ""),
                  i.get("categoria", ""), i.get("descricao", "")) for i in lido.get("itens", [])],
            )
        self.conn.commit()
        return captura_id

    def capturas(self, cliente_id: str, alvo_id=None, limite: int = 20) -> list:
        """Capturas da mais recente para a mais antiga (por data e, em empate, por ordem de entrada)."""
        sql = "SELECT * FROM capturas_cardapio WHERE cliente_id = ?"
        parametros = [cliente_id]
        if alvo_id:
            sql += " AND alvo_id = ?"
            parametros.append(alvo_id)
        parametros.append(limite)
        return [dict(l) for l in self.conn.execute(sql + " ORDER BY data DESC, id DESC LIMIT ?", parametros)]

    def itens_da_captura(self, captura_id: int) -> list:
        return [dict(l) for l in self.conn.execute(
            "SELECT nome, chave, preco, preco_texto, categoria, descricao FROM itens_cardapio WHERE captura_id = ?"
            " ORDER BY rowid", (captura_id,))]

    # --- exclusão (a revisão humana vira rótulo) --------------------------------------------------------------

    def excluir_eventos(self, ids: list, motivo: str = "descartado na revisão") -> int:
        """
        Tira um evento do relatório para sempre. Além de limpar o Radar, cada exclusão é um rótulo humano de
        "isto é ruído" — matéria-prima para medir a taxa de alarme falso mais adiante.
        """
        with closing(self.conn.cursor()) as cur:
            cur.executemany("UPDATE eventos SET excluido = 1, motivo_exclusao = ? WHERE id = ?",
                            [(motivo, i) for i in ids])
            self.conn.commit()
            excluidos = cur.rowcount
        self.rotular([(i, 0, motivo, "revisao") for i in ids])          # descartar é dizer "isto é ruído"
        return excluidos

    def restaurar_eventos(self, ids: list) -> None:
        self.conn.executemany("UPDATE eventos SET excluido = 0, motivo_exclusao = NULL WHERE id = ?",
                              [(i,) for i in ids])
        self.conn.commit()

    def eventos_desde(self, cliente_id: str, visto_apos: str = None, incluir_excluidos: bool = False,
                      visto_ate: str = None) -> list:
        """O que ENTROU na base depois de `visto_apos` (o gerado_em do relatório anterior)."""
        sql = "SELECT * FROM eventos WHERE cliente_id = ?"
        parametros = [cliente_id]
        if not incluir_excluidos:
            sql += " AND COALESCE(excluido, 0) = 0"
        for coluna, valor in ((">", visto_apos), ("<=", visto_ate)):
            if valor:
                sql += f" AND visto_em {coluna} ?"
                parametros.append(valor)
        return [dict(l) for l in self.conn.execute(sql + " ORDER BY data DESC, id", parametros)]

    # --- rótulos (medição) -------------------------------------------------------------------------------------

    def rotular(self, pares: list, sobrescrever: bool = True) -> int:
        """
        `pares` é uma lista de (evento_id, relevante, motivo, origem). Sem `sobrescrever`, um rótulo que já
        existe é preservado — o automático da revisão nunca apaga o que uma pessoa decidiu à mão.
        """
        conflito = "REPLACE" if sobrescrever else "IGNORE"
        quando = agora()
        with closing(self.conn.cursor()) as cur:
            cur.executemany(
                f"INSERT OR {conflito} INTO rotulos (evento_id, relevante, motivo, origem, rotulado_em)"
                " VALUES (?, ?, ?, ?, ?)",
                [(i, int(bool(r)), m, o, quando) for i, r, m, o in pares],
            )
            self.conn.commit()
            return cur.rowcount

    def rotulos(self, cliente_id=None) -> list:
        """Rótulos com o evento junto, para as métricas saberem alvo, fonte e motor."""
        sql = ("SELECT r.*, e.cliente_id, e.alvo_id, e.titulo, e.fonte, e.data, e.motor, e.classificacao"
               " FROM rotulos r JOIN eventos e ON e.id = r.evento_id")
        parametros = []
        if cliente_id:
            sql += " WHERE e.cliente_id = ?"
            parametros.append(cliente_id)
        return [dict(l) for l in self.conn.execute(sql + " ORDER BY r.rotulado_em DESC", parametros)]

    def sem_rotulo(self, cliente_id: str, limite: int = 100) -> list:
        return [dict(l) for l in self.conn.execute(
            "SELECT e.* FROM eventos e LEFT JOIN rotulos r ON r.evento_id = e.id"
            " WHERE e.cliente_id = ? AND r.evento_id IS NULL ORDER BY e.data DESC LIMIT ?", (cliente_id, limite))]

    # --- relatórios -------------------------------------------------------------------------------------------

    def criar_relatorio(self, cliente_id: str, periodo_de: str, periodo_ate: str, corte, itens: int,
                        arquivo: str = "", resumo: str = "") -> int:
        with closing(self.conn.cursor()) as cur:
            cur.execute(
                "INSERT INTO relatorios (cliente_id, periodo_de, periodo_ate, corte, gerado_em, estado, arquivo,"
                " itens, resumo, atualizado_em) VALUES (?, ?, ?, ?, ?, 'rascunho', ?, ?, ?, ?)",
                (cliente_id, periodo_de, periodo_ate, corte, agora(), arquivo, itens, resumo, agora()),
            )
            self.conn.commit()
            return cur.lastrowid

    def relatorio(self, relatorio_id: int):
        linha = self.conn.execute("SELECT * FROM relatorios WHERE id = ?", (relatorio_id,)).fetchone()
        return dict(linha) if linha else None

    def mudar_estado(self, relatorio_id: int, estado: str, notas: str = "") -> None:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado} (use {', '.join(ESTADOS)})")
        self.conn.execute("UPDATE relatorios SET estado = ?, notas = ?, atualizado_em = ? WHERE id = ?",
                          (estado, notas, agora(), relatorio_id))
        self.conn.commit()
        if estado == "aprovado":
            self._rotular_aprovados(relatorio_id)

    def _rotular_aprovados(self, relatorio_id: int) -> None:
        """Aprovar um Radar é dizer que o que sobrou nele vale a pena. Não sobrescreve rótulo feito à mão."""
        registro = self.conn.execute("SELECT * FROM relatorios WHERE id = ?", (relatorio_id,)).fetchone()
        if registro is None:
            return
        do_relatorio = self.eventos_desde(registro["cliente_id"], registro["corte"], visto_ate=registro["gerado_em"])
        self.rotular([(e["id"], 1, "sobreviveu à revisão", "revisao") for e in do_relatorio], sobrescrever=False)

    def relatorios(self, cliente_id=None, estado=None, limite: int = 20) -> list:
        sql = "SELECT * FROM relatorios WHERE 1=1"
        parametros = []
        for coluna, valor in (("cliente_id", cliente_id), ("estado", estado)):
            if valor:
                sql += f" AND {coluna} = ?"
                parametros.append(valor)
        parametros.append(limite)
        return [dict(l) for l in self.conn.execute(sql + " ORDER BY id DESC LIMIT ?", parametros)]

    def corte_do_proximo_relatorio(self, cliente_id: str):
        """
        O `gerado_em` do último relatório que chegou ao cliente. Rascunho descartado NÃO conta: o que estava
        nele precisa aparecer no próximo, senão a semana some do acompanhamento.
        """
        linha = self.conn.execute(
            "SELECT MAX(gerado_em) g FROM relatorios WHERE cliente_id = ? AND estado IN ('aprovado', 'enviado')",
            (cliente_id,)).fetchone()
        return linha["g"] if linha else None

    def contagem(self, cliente_id=None) -> dict:
        sql = "SELECT COUNT(*) total, SUM(score IS NULL) sem_score FROM eventos"
        parametros = []
        if cliente_id:
            sql += " WHERE cliente_id = ?"
            parametros.append(cliente_id)
        linha = self.conn.execute(sql, parametros).fetchone()
        return {"total": linha["total"] or 0, "sem_score": linha["sem_score"] or 0}
