"""
Embedding function multilíngue (intfloat/multilingual-e5-small) para o RAG.

O modelo e5 foi treinado com prefixos diferentes para o que é indexado
("passage: ") e para a pergunta de busca ("query: "). Sem esses prefixos
as distâncias ficam achatadas e o "modo não sei" para de discriminar
pergunta dentro/fora dos documentos. `embed_query` é o hook que o Chroma
chama automaticamente para textos de busca, então isso funciona com
`collection.query(query_texts=[...])` normalmente.
"""
from typing import Any, Dict

from chromadb import Documents, EmbeddingFunction, Embeddings

MODELO_EMBEDDING = "intfloat/multilingual-e5-small"
_modelos: Dict[str, Any] = {}


class _ModeloFallbackHash:
    """Fallback determinístico em numpy puro para quando DLLs do torch/sklearn forem bloqueadas pelo Windows App Control."""
    def encode(self, textos, normalize_embeddings=True):
        import hashlib
        import numpy as np
        vecs = []
        for t in textos:
            v = np.zeros(384, dtype=np.float32)
            palavras = str(t).lower().split()
            for i, p in enumerate(palavras):
                h = int(hashlib.sha256(p.encode("utf-8")).hexdigest(), 16)
                v[h % 384] += 1.0
                if i + 1 < len(palavras):
                    par = f"{p}_{palavras[i+1]}"
                    h2 = int(hashlib.sha256(par.encode("utf-8")).hexdigest(), 16)
                    v[h2 % 384] += 1.8
            norm = np.linalg.norm(v)
            if norm > 0:
                v = v / norm
            else:
                v[0] = 1.0
            vecs.append(v)
        return np.array(vecs)


def _obter_modelo(nome: str):
    if nome not in _modelos:
        try:
            from sentence_transformers import SentenceTransformer
            _modelos[nome] = SentenceTransformer(nome)
        except (ImportError, OSError) as e:
            # Avisa: vetor do fallback e vetor do modelo real não são comparáveis.
            # Indexar com um e buscar com o outro devolve resultado aleatório.
            import logging
            logging.getLogger(__name__).warning(
                "Embeddings: '%s' não carregou (%s); usando fallback de hash", nome, e)
            _modelos[nome] = _ModeloFallbackHash()
    return _modelos[nome]


class EmbeddingFunctionMultilingue(EmbeddingFunction):
    def __init__(self, model_name: str = MODELO_EMBEDDING):
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        modelo = _obter_modelo(self.model_name)
        textos = [f"passage: {t}" for t in input]
        return modelo.encode(textos, normalize_embeddings=True).tolist()

    def embed_query(self, input: Documents) -> Embeddings:
        modelo = _obter_modelo(self.model_name)
        textos = [f"query: {t}" for t in input]
        return modelo.encode(textos, normalize_embeddings=True).tolist()

    @staticmethod
    def name() -> str:
        return "multilingual_e5_prefixed"

    def get_config(self) -> Dict[str, Any]:
        return {"model_name": self.model_name}

    @staticmethod
    def build_from_config(config: Dict[str, Any]) -> "EmbeddingFunctionMultilingue":
        return EmbeddingFunctionMultilingue(model_name=config["model_name"])


def embed_textos(textos, prefixo="query"):
    """
    Vetores normalizados (numpy) para comparar textos entre si. O e5 recomenda o prefixo "query: "
    nos dois lados quando a tarefa é similaridade simétrica (texto x texto), sem indexar nada.
    """
    modelo = _obter_modelo(MODELO_EMBEDDING)
    return modelo.encode([f"{prefixo}: {t}" for t in textos], normalize_embeddings=True)


def similaridade_cosseno(a: str, b: str) -> float:
    va, vb = embed_textos([a, b])
    return float(va @ vb)
