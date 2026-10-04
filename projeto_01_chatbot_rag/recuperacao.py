"""
Recuperação de trechos: vetorial, BM25 (palavras-chave), fusão dos dois (RRF) e reranker cross-encoder.

Vetor sozinho erra o que é literal (siglas, números, códigos), BM25 sozinho erra paráfrase; o padrão que virou
consenso é juntar os dois pela posição (RRF, que não depende de as escalas de nota serem comparáveis) e deixar um
cross-encoder reler os candidatos. O reranker também dá uma nota mais nítida para decidir o "não sei".
"""
import math
import re
import time
from dataclasses import dataclass, field

import numpy as np

from texto_util import chave

MODELO_RERANKER = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
MODOS = ("vetorial", "bm25", "hibrido", "vetorial_rerank", "hibrido_rerank")

_STOPWORDS = set("""a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sobre entre e ou mas que se ao aos
pelo pela pelos pelas eh sao ser foi tem ter ha como qual quais quanto quantos quanta quantas quando onde quem meu minha seu sua
deve devo posso pode preciso isso esse essa este esta nao mais muito ja tambem todo toda todos todas cada ate apos""".split())


def _radical(palavra: str) -> str:
    if len(palavra) > 5 and palavra.endswith("coes"):
        return palavra[:-4] + "cao"
    if len(palavra) > 4 and palavra.endswith("oes"):
        return palavra[:-3] + "ao"
    if len(palavra) > 3 and palavra.endswith("s") and not palavra.endswith("ss"):
        return palavra[:-1]
    return palavra


def tokenizar(texto: str) -> list:
    return [_radical(p) for p in re.findall(r"[a-z0-9]+", chave(texto)) if p not in _STOPWORDS]


class BM25:
    """BM25 Okapi. Implementação própria: para milhares de blocos é mais que suficiente e não pede dependência."""

    def __init__(self, documentos: list, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [self._contar(tokenizar(d)) for d in documentos]
        self.tamanhos = np.array([sum(t.values()) for t in self.tf], dtype=float)
        self.media = float(self.tamanhos.mean()) if len(documentos) else 0.0
        df = {}
        for t in self.tf:
            for termo in t:
                df[termo] = df.get(termo, 0) + 1
        n = len(documentos)
        self.idf = {termo: math.log(1 + (n - f + 0.5) / (f + 0.5)) for termo, f in df.items()}

    @staticmethod
    def _contar(tokens):
        contagem = {}
        for t in tokens:
            contagem[t] = contagem.get(t, 0) + 1
        return contagem

    def pontuar(self, consulta: str) -> np.ndarray:
        notas = np.zeros(len(self.tf))
        for termo in set(tokenizar(consulta)):
            idf = self.idf.get(termo)
            if idf is None:
                continue
            for i, t in enumerate(self.tf):
                f = t.get(termo)
                if f:
                    norma = self.k1 * (1 - self.b + self.b * self.tamanhos[i] / (self.media or 1))
                    notas[i] += idf * f * (self.k1 + 1) / (f + norma)
        return notas


def fusao_rrf(rankings: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion: junta listas de ids pela POSIÇÃO. Devolve [(id, nota)] do maior para o menor."""
    notas = {}
    for lista in rankings:
        for posicao, identificador in enumerate(lista, start=1):
            notas[identificador] = notas.get(identificador, 0.0) + 1.0 / (k + posicao)
    return sorted(notas.items(), key=lambda p: -p[1])


_RERANKERS = {}


def obter_reranker(nome: str = MODELO_RERANKER):
    if nome not in _RERANKERS:
        from sentence_transformers import CrossEncoder
        _RERANKERS[nome] = CrossEncoder(nome)
    return _RERANKERS[nome]


@dataclass
class Trecho:
    id: str
    texto: str
    arquivo: str
    pagina: int = 1
    secao: str = ""
    tipo: str = "detalhe"
    distancia: float | None = None
    nota_bm25: float | None = None
    nota_rerank: float | None = None


@dataclass
class ResultadoBusca:
    trechos: list
    melhor_distancia: float | None = None
    melhor_rerank: float | None = None
    latencias_ms: dict = field(default_factory=dict)


@dataclass
class Decisao:
    responder: bool
    motivo: str


def decidir(res: ResultadoBusca, limiar_distancia: float = 0.17, limiar_rerank: float | None = None) -> Decisao:
    """"Modo não sei": com reranker usa a nota dele (mais nítida); sem, a distância do melhor bloco vetorial."""
    if not res.trechos:
        return Decisao(False, "nenhum trecho encontrado")
    if limiar_rerank is not None and res.melhor_rerank is not None:
        ok = res.melhor_rerank >= limiar_rerank
        return Decisao(ok, f"nota do reranker {res.melhor_rerank:.2f} {'>=' if ok else '<'} corte {limiar_rerank:.2f}")
    if res.melhor_distancia is not None:
        ok = res.melhor_distancia <= limiar_distancia
        return Decisao(ok, f"distância {res.melhor_distancia:.4f} {'<=' if ok else '>'} corte {limiar_distancia:.2f}")
    return Decisao(True, "sem métrica de corte para este modo")


class Recuperador:
    def __init__(self, colecao, modo: str = "hibrido_rerank", candidatos: int = 20, rrf_k: int = 60, reranker=None):
        if modo not in MODOS:
            raise ValueError(f"modo inválido: {modo}")
        self.colecao, self.modo, self.candidatos, self.rrf_k = colecao, modo, candidatos, rrf_k
        self._reranker = reranker
        self._assinatura = None
        self._corpus = {}

    # --- índice BM25 em memória, refeito quando o conteúdo da coleção muda ---------------------------------------
    def _preparar_bm25(self):
        ids = self.colecao.get(include=[])["ids"]
        assinatura = (len(ids), hash(tuple(sorted(ids))))
        if assinatura != self._assinatura:
            dados = self.colecao.get(include=["documents", "metadatas"])
            self._corpus = {"ids": dados["ids"], "documentos": dados["documents"], "metas": dados["metadatas"]}
            self._bm25 = BM25(dados["documents"])
            self._assinatura = assinatura

    def invalidar(self):
        self._assinatura = None

    def _trecho(self, identificador, texto, meta, **campos) -> Trecho:
        return Trecho(id=identificador, texto=texto, arquivo=meta["arquivo"], pagina=meta.get("pagina", 1),
                      secao=meta.get("secao", ""), tipo=meta.get("tipo", "detalhe"), **campos)

    def _vetorial(self, pergunta, n, arquivos):
        total = self.colecao.count()
        if not total:
            return []
        filtro = {"arquivo": {"$in": list(arquivos)}} if arquivos else None
        r = self.colecao.query(query_texts=[pergunta], n_results=min(n, total), where=filtro,
                               include=["documents", "metadatas", "distances"])
        return [self._trecho(i, d, m, distancia=dist)
                for i, d, m, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0])]

    def _lexical(self, pergunta, n, arquivos):
        self._preparar_bm25()
        notas = self._bm25.pontuar(pergunta)
        ordem = [i for i in np.argsort(-notas) if notas[i] > 0]
        saida = []
        for i in ordem:
            meta = self._corpus["metas"][i]
            if arquivos and meta["arquivo"] not in arquivos:
                continue
            saida.append(self._trecho(self._corpus["ids"][i], self._corpus["documentos"][i], meta, nota_bm25=float(notas[i])))
            if len(saida) == n:
                break
        return saida

    def buscar(self, pergunta: str, k: int = 5, arquivos=None) -> ResultadoBusca:
        lat, t0 = {}, time.perf_counter()
        usa_vetor = self.modo != "bm25"
        usa_bm25 = self.modo in ("bm25", "hibrido", "hibrido_rerank")
        usa_rerank = self.modo.endswith("_rerank")
        n = self.candidatos if usa_rerank or self.modo == "hibrido" else max(k, self.candidatos)

        vetor = self._vetorial(pergunta, n, arquivos) if usa_vetor else []
        lat["vetorial"] = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        lexico = self._lexical(pergunta, n, arquivos) if usa_bm25 else []
        lat["bm25"] = (time.perf_counter() - t1) * 1000

        por_id = {t.id: t for t in vetor}
        for t in lexico:
            if t.id in por_id:
                por_id[t.id].nota_bm25 = t.nota_bm25
            else:
                por_id[t.id] = t
        if self.modo in ("hibrido", "hibrido_rerank"):
            ordem = [i for i, _ in fusao_rrf([[t.id for t in vetor], [t.id for t in lexico]], self.rrf_k)]
        elif self.modo == "bm25":
            ordem = [t.id for t in lexico]
        else:
            ordem = [t.id for t in vetor]
        candidatos = [por_id[i] for i in ordem[:self.candidatos if usa_rerank else max(k, 1)]]

        melhor_rerank = None
        t2 = time.perf_counter()
        if usa_rerank and candidatos:
            modelo = self._reranker or obter_reranker()
            notas = modelo.predict([(pergunta, t.texto) for t in candidatos])
            for t, nota in zip(candidatos, notas):
                t.nota_rerank = float(nota)
            candidatos.sort(key=lambda t: -t.nota_rerank)
            melhor_rerank = candidatos[0].nota_rerank
        lat["rerank"] = (time.perf_counter() - t2) * 1000
        lat["total"] = (time.perf_counter() - t0) * 1000

        melhor_distancia = min((t.distancia for t in vetor), default=None)
        return ResultadoBusca(candidatos[:k], melhor_distancia, melhor_rerank, lat)
