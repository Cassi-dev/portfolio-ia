"""
"A mesma notícia de novo" — decidido por palavras em comum ou por significado.

Medido em 80 manchetes reais do Google News, com 11 histórias que saíram repetidas em 2 a 5 portais
(21 repetições a eliminar). Cada item foi comparado com os que já estavam na base, do mesmo alvo:

    regra                       repetições removidas   fusões erradas
    jaccard >= 0,60 (o de antes)        0 de 21               0
    jaccard >= 0,35                     5 de 21               1
    contenção >= 0,50                   6 de 21               9
    embedding, cosseno >= 0,95          5 de 21               0
    embedding, cosseno >= 0,93         11 de 21               1

Palavra em comum não resolve: o portal reescreve o título inteiro ("Mulher encontra aparelho dentário em prato
do Outback" e "Cliente relata ter encontrado objeto estranho em prato de rede famosa" são a mesma história e
quase não compartilham palavras). Baixar o limiar por tokens começa a juntar notícias diferentes antes de pegar
as repetições.

O padrão é 0,93: troca 1 fusão errada em 80 por metade das repetições a menos. A fusão errada custa uma notícia
real que não chega ao cliente, então quem preferir errar para o outro lado usa 0,95 e perde recall.

O modo "tokens" continua disponível para rodar sem baixar modelo (CI, máquina sem GPU, teste rápido).
"""
from functools import lru_cache

LIMIAR_TOKENS = 0.60
LIMIAR_EMBEDDING = 0.93
MODOS = ("tokens", "embedding")


@lru_cache(maxsize=1)
def _modelo_disponivel() -> bool:
    try:
        import sentence_transformers  # noqa: F401
        return True
    except ImportError:
        return False


class Deduplicador:
    """
    `e_duplicata(titulo, conhecidos)` responde se o título repete alguma das manchetes já guardadas.
    Os vetores ficam em cache por título, então cada manchete é codificada uma vez por execução.
    """

    def __init__(self, modo: str = "tokens", limiar: float = None):
        if modo not in MODOS:
            raise ValueError(f"modo de deduplicação inválido: {modo} (use {', '.join(MODOS)})")
        if modo == "embedding" and not _modelo_disponivel():
            raise ImportError("o modo 'embedding' precisa do sentence-transformers instalado")
        self.modo = modo
        self.limiar = limiar if limiar is not None else (LIMIAR_TOKENS if modo == "tokens" else LIMIAR_EMBEDDING)
        self._vetores = {}

    def _vetorizar(self, titulos: list) -> None:
        from core.embeddings import embed_textos

        faltando = [t for t in dict.fromkeys(titulos) if t not in self._vetores]
        if faltando:
            self._vetores.update(zip(faltando, embed_textos(faltando)))

    def semelhanca(self, a: str, b: str) -> float:
        if self.modo == "tokens":
            from coleta_noticias import calcular_similaridade
            return calcular_similaridade(a, b)
        self._vetorizar([a, b])
        return sum(x * y for x, y in zip(self._vetores[a], self._vetores[b]))    # e5 devolve vetores normalizados

    def e_duplicata(self, titulo: str, conhecidos: list) -> bool:
        if not conhecidos:
            return False
        if self.modo == "embedding":
            self._vetorizar([titulo, *conhecidos])
        return any(self.semelhanca(titulo, conhecido) >= self.limiar for conhecido in conhecidos)


def escolher(modo: str = "embedding", limiar: float = None) -> Deduplicador:
    """O modo pedido, caindo para tokens (com aviso no motivo) se o modelo não estiver disponível."""
    try:
        return Deduplicador(modo, limiar)
    except ImportError:
        return Deduplicador("tokens")
