import pytest
try:
    from chromadb import EmbeddingFunction
except ImportError:
    EmbeddingFunction = object


class RespostaFalsa:
    def __init__(self, text):
        self.text = text


class ModelosFalsos:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def generate_content(self, model, contents, config=None):
        self.chamadas.append({"contents": contents, "config": config})
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, Exception):
            raise r
        return RespostaFalsa(r)


class ClienteFalso:
    """Imita client.models.generate_content(...) do google-genai. Aceita textos ou exceções."""

    def __init__(self, *respostas):
        self.models = ModelosFalsos(respostas)


class ErroApi(Exception):
    """Imita google.genai.errors.APIError, que traz o código HTTP em `.code`."""

    def __init__(self, code, msg="erro"):
        super().__init__(f"{code} {msg}")
        self.code = code


@pytest.fixture(autouse=True)
def sem_cache_de_llm(monkeypatch):
    monkeypatch.setenv("LLM_CACHE", "0")


@pytest.fixture(autouse=True)
def sem_bloqueio_de_cota():
    """O bloqueio por cota é global ao processo: sem limpar, um teste de 429 contaminaria os seguintes."""
    from core import llm
    llm.liberar()
    yield
    llm.liberar()


class EmbeddingPalavras(EmbeddingFunction):
    """
    Embedding falso, determinístico e sem modelo: cada palavra vira uma posição num vetor de 256 dimensões
    (saco de palavras normalizado). Textos com palavras em comum ficam próximos; serve para testar o encanamento
    da busca, não a qualidade semântica.
    """

    def __init__(self):
        pass

    def _vetor(self, texto):
        from recuperacao import tokenizar
        v = [0.0] * 256
        for t in tokenizar(texto):
            v[hash(t) % 256] += 1.0
        norma = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norma for x in v]

    def __call__(self, input):
        return [self._vetor(t) for t in input]

    @staticmethod
    def name():
        return "embedding_palavras_de_teste"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return EmbeddingPalavras()


class RerankerFalso:
    """Nota = quantas palavras da pergunta aparecem no trecho (imita um cross-encoder sem baixar nada)."""

    def predict(self, pares):
        from recuperacao import tokenizar
        return [float(len(set(tokenizar(p)) & set(tokenizar(t)))) - 2.0 for p, t in pares]


@pytest.fixture
def embedding_palavras():
    return EmbeddingPalavras


@pytest.fixture
def reranker_falso():
    return RerankerFalso()


@pytest.fixture
def banco_temp(tmp_path, monkeypatch):
    """SQLite de exemplo recém-semeado num arquivo temporário (não toca o banco do projeto)."""
    import banco_dados
    monkeypatch.setattr(banco_dados, "CAMINHO_BANCO", str(tmp_path / "teste.db"))
    banco_dados.inicializar_banco()
    return banco_dados


@pytest.fixture
def cliente_falso():
    return ClienteFalso


@pytest.fixture
def erro_api():
    return ErroApi


@pytest.fixture
def blocos_video():
    return [
        {"timestamp_segundos": i * 50.0, "timestamp_formatado": f"{i * 50 // 60:02d}:{i * 50 % 60:02d}",
         "texto": f"Trecho número {i} do vídeo sobre inteligência artificial aplicada."}
        for i in range(10)
    ]
