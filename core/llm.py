"""
Cliente LLM compartilhado pelos projetos.

- retry com backoff exponencial só para erros transitórios (429/5xx), decidido pelo código HTTP
- timeout por chamada (definido ao criar o cliente)
- saída estruturada: o schema Pydantic vai para o Gemini (response_schema) e a resposta é
  validada de volta; se vier inválida, uma única tentativa de reparo devolve o erro ao modelo
- cache em disco por (modelo, schema, temperatura, prompt)
- log e histórico de latência e tokens de cada chamada
"""
import json
import logging
import re
import time
from collections import deque
from typing import Any, Callable

from pydantic import TypeAdapter, ValidationError

from core import cache, cota, preco
from core.config import MODELO_GEMINI

log = logging.getLogger("core.llm")

TIMEOUT_MS = 60_000
CODIGOS_TRANSITORIOS = {429, 500, 502, 503, 504}
ESPERA_MAXIMA = 65.0           # o limite por minuto do Gemini pede esperas na casa dos 30 a 60 segundos
historico: deque = deque(maxlen=200)

# Cota estourada vale para a chave inteira, não para uma chamada. Sem isto, cada etapa seguinte do
# map-reduce repetiria as tentativas e a espera por nada — o usuário esperaria minutos para ver 4 erros iguais.
_bloqueado_ate = 0.0
_motivo_do_bloqueio = ""


class FalhaLLM(Exception):
    """
    A chamada falhou (rede, cota, servidor) mesmo depois das tentativas.

    `amigavel` marca a mensagem que já está escrita para o usuário ler — quem for exibi-la não deve
    embrulhar de novo nem cortar. Sem isso, a explicação da cota aparecia dentro de "falha na chamada da
    IA (...)" e truncada no meio de uma palavra.
    """

    def __init__(self, mensagem, *, amigavel: bool = False):
        super().__init__(mensagem)
        self.amigavel = amigavel


class RespostaInvalida(Exception):
    """A IA respondeu, mas fora do schema esperado, mesmo após a tentativa de reparo."""


def criar_cliente(api_key: str):
    try:
        from google import genai
        from google.genai import types
        return genai.Client(api_key=api_key.strip(), http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    except Exception as e:
        raise FalhaLLM(f"{type(e).__name__}: {str(e)[:200]}") from e


def _transitorio(erro: Exception) -> bool:
    if getattr(erro, "code", None) in CODIGOS_TRANSITORIOS:
        return True
    texto = str(erro)
    return any(marca in texto for marca in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))


def _registrar(resp: Any, segundos: float, do_cache: bool) -> None:
    uso = getattr(resp, "usage_metadata", None)
    registro = {
        "modelo": MODELO_GEMINI,
        "latencia_ms": round(segundos * 1000),
        "tokens_entrada": getattr(uso, "prompt_token_count", None),
        "tokens_saida": getattr(uso, "candidates_token_count", None),
        # Cobrados como saída, à mesma tarifa. Ficavam de fora da conta, e são o grosso dela.
        "tokens_pensamento": getattr(uso, "thoughts_token_count", None),
        "cache": do_cache,
    }
    historico.append(registro)
    log.info("llm %s", registro)


def estatisticas() -> dict:
    """`custo_usd` é None quando o modelo não está na tabela de preços — melhor nada do que um número inventado."""
    api = [h for h in historico if not h["cache"]]
    entrada = sum(h["tokens_entrada"] or 0 for h in api)
    saida = sum(h["tokens_saida"] or 0 for h in api)
    pensamento = sum(h.get("tokens_pensamento") or 0 for h in api)
    return {
        "chamadas_api": len(api),
        "cache_hits": len(historico) - len(api),
        "latencia_media_ms": round(sum(h["latencia_ms"] for h in api) / len(api)) if api else 0,
        "tokens_entrada": entrada,
        "tokens_saida": saida,
        "tokens_pensamento": pensamento,
        "custo_usd": preco.custo_usd(entrada, saida + pensamento),
    }


def bloquear(segundos: float, motivo: str = "") -> None:
    """Segura as próximas chamadas: a cota acabou e insistir só gasta tempo."""
    global _bloqueado_ate, _motivo_do_bloqueio
    _bloqueado_ate = max(_bloqueado_ate, time.monotonic() + segundos)
    _motivo_do_bloqueio = motivo


def liberar() -> None:
    global _bloqueado_ate, _motivo_do_bloqueio
    _bloqueado_ate, _motivo_do_bloqueio = 0.0, ""


def bloqueio_restante() -> float:
    return max(0.0, _bloqueado_ate - time.monotonic())


def _espera_do_erro(erro, espera_base: float, n: int) -> float:
    """A espera que a própria API sugeriu, quando houver; senão o backoff exponencial de sempre."""
    sugerida = cota.detalhes(erro)["espera"]
    return min(ESPERA_MAXIMA, max(sugerida or 0.0, espera_base * 2 ** (n - 1)))


def _chamar(client, prompt: str, config, tentativas: int, espera_base: float, dormir: Callable[[float], None]):
    if (restante := bloqueio_restante()) > 0:
        raise FalhaLLM(f"{_motivo_do_bloqueio} (tente de novo em {restante:.0f}s)", amigavel=True)
    esperas_de_cota = 0
    for n in range(1, tentativas + 1):
        inicio = time.perf_counter()
        try:
            resp = client.models.generate_content(model=MODELO_GEMINI, contents=prompt, config=config)
        except Exception as e:
            info = cota.detalhes(e)
            if info["cota"]:
                esperas_de_cota += 1
                # Cota diária não volta esperando; a por minuto volta, mas só depois do tempo que a API disse —
                # e uma espera dessas já basta: insistir mais só congela a tela por minutos, sem ganho.
                espera = ESPERA_MAXIMA if info["por_dia"] else _espera_do_erro(e, espera_base, n)
                explicacao = cota.explicar(e)
                bloquear(espera, explicacao)
                if info["por_dia"] or esperas_de_cota > 1 or n >= tentativas:
                    # A explicação sai daqui, do erro inteiro; quem só vê a FalhaLLM não teria o JSON original.
                    log.warning("llm cota estourada: %s", str(e)[:400])
                    raise FalhaLLM(explicacao, amigavel=True) from e
            elif not (_transitorio(e) and n < tentativas):
                raise FalhaLLM(f"{type(e).__name__}: {str(e)[:200]}") from e
            espera = _espera_do_erro(e, espera_base, n)
            log.warning("llm erro transitório (%s); nova tentativa em %.1fs", type(e).__name__, espera)
            dormir(espera)
            continue
        _registrar(resp, time.perf_counter() - inicio, do_cache=False)
        liberar()
        return resp
    raise FalhaLLM("tentativas esgotadas")


def _sem_cerca(texto: str) -> str:
    t = (texto or "").strip()
    m = re.match(r"^```[a-zA-Z]*\s*\n(.*?)\n?```$", t, re.S)
    return m.group(1).strip() if m else t


def _resumo_erro(erro: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'raiz'}: {e['msg']}" for e in erro.errors()[:3])


def gerar_texto(client, prompt: str, *, temperatura: float | None = None, usar_cache: bool = True,
                tentativas: int = 3, espera_base: float = 2.0,
                dormir: Callable[[float], None] = time.sleep) -> str:
    # `prompt` pode ser uma lista (ex.: [PDF, instrução] no OCR); esses casos não usam cache
    k = cache.chave(MODELO_GEMINI, "texto", str(temperatura), prompt) if usar_cache else None
    if k and (guardado := cache.obter(k)) is not None:
        _registrar(None, 0.0, do_cache=True)
        return guardado

    config = None
    if temperatura is not None:
        from google.genai import types
        config = types.GenerateContentConfig(temperature=temperatura)
    resp = _chamar(client, prompt, config, tentativas, espera_base, dormir)
    texto = (resp.text or "").strip()
    if not texto:
        raise FalhaLLM("a IA devolveu uma resposta vazia")
    if k:
        cache.guardar(k, texto)
    return texto


def gerar_estruturado(client, prompt, schema: Any, *, temperatura: float = 0.2, reparar: bool = True,
                      usar_cache: bool = True, tentativas: int = 3, espera_base: float = 2.0,
                      dormir: Callable[[float], None] = time.sleep):
    """
    `schema` pode ser um modelo Pydantic ou algo como list[Modelo]. Devolve o valor já validado.
    `prompt` é texto ou, como em gerar_texto, uma lista ([imagem, instrução]); lista não usa cache.
    """
    adaptador = TypeAdapter(schema)
    e_texto = isinstance(prompt, str)
    k = cache.chave(MODELO_GEMINI, json.dumps(adaptador.json_schema(), sort_keys=True), str(temperatura),
                    prompt) if e_texto else None

    if k and usar_cache and (guardado := cache.obter(k)) is not None:
        try:
            valor = adaptador.validate_json(guardado)
            _registrar(None, 0.0, do_cache=True)
            return valor
        except ValidationError:
            pass

    from google.genai import types
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=temperatura
    )

    erro = None
    for _ in range(2 if reparar else 1):
        correcao = (f"Sua resposta anterior foi rejeitada: {erro}\n"
                    "Responda de novo, apenas com o JSON válido conforme o schema.")
        if erro is None:
            conteudo = prompt
        else:
            conteudo = f"{prompt}\n\n{correcao}" if e_texto else [*prompt, correcao]
        resp = _chamar(client, conteudo, config, tentativas, espera_base, dormir)
        texto = _sem_cerca(resp.text)
        try:
            valor = adaptador.validate_json(texto)
        except ValidationError as e:
            erro = _resumo_erro(e)
            log.warning("llm resposta fora do schema: %s", erro)
            continue
        if k:
            cache.guardar(k, texto)
        return valor
    raise RespostaInvalida(erro)
