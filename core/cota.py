"""
Leitura do erro 429 da API do Gemini.

O 429 chega como um texto longo com o JSON do erro dentro. Ele traz duas coisas que mudam o que fazer, e as
duas ficavam escondidas: **quanto esperar** (`retryDelay`) e **qual cota** estourou. Bater o limite por minuto
se resolve esperando; bater o limite por dia não se resolve esperando — só amanhã, ou ativando faturamento.
"""
import re

_RETRY_DELAY = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")
_QUOTA_ID = re.compile(r"quotaId['\"]?\s*:\s*['\"]([^'\"]+)")
_MARCAS = ("RESOURCE_EXHAUSTED", "exceeded your current quota", "429")
ESPERA_PADRAO = 60.0


def e_cota(erro) -> bool:
    if getattr(erro, "code", None) == 429:
        return True
    texto = str(erro)
    return any(marca in texto for marca in _MARCAS)


def detalhes(erro) -> dict:
    """{"cota", "por_dia", "espera", "limite"} — `espera` em segundos, None quando a API não sugeriu nenhuma."""
    texto = str(erro)
    achado = _RETRY_DELAY.search(texto)
    quota = _QUOTA_ID.search(texto)
    limite = quota.group(1) if quota else ""
    return {
        "cota": e_cota(erro),
        "por_dia": "perday" in limite.lower().replace("_", ""),
        "espera": float(achado.group(1)) if achado else None,
        "limite": limite,
    }


def explicar(erro) -> str:
    """Frase em português dizendo o que estourou e o que fazer. Vazia quando não é problema de cota."""
    info = detalhes(erro)
    if not info["cota"]:
        return ""
    if info["por_dia"]:
        return ("a cota diária da sua chave do Gemini acabou. Esperar não resolve hoje: use outra chave, "
                "ative o faturamento no Google AI Studio ou continue amanhã")
    espera = info["espera"]
    quando = f"Espere cerca de {espera:.0f}s e tente de novo" if espera else "Espere um minuto e tente de novo"
    return (f"você bateu o limite de chamadas por minuto da sua chave do Gemini. {quando} — "
            "ou ative o faturamento para subir o limite")
