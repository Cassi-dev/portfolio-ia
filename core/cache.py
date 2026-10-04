"""Cache em disco para respostas de LLM (evita pagar/esperar de novo pelo mesmo prompt)."""
import hashlib
import os
from pathlib import Path

from core.config import RAIZ

PASTA = RAIZ / ".cache" / "llm"


def ativo() -> bool:
    return os.environ.get("LLM_CACHE", "1") != "0"


def chave(*partes: str) -> str:
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()


def obter(k: str) -> str | None:
    if not ativo():
        return None
    try:
        return (PASTA / f"{k}.json").read_text(encoding="utf-8")
    except OSError:
        return None


def guardar(k: str, texto: str) -> None:
    if not ativo():
        return
    PASTA.mkdir(parents=True, exist_ok=True)
    destino = Path(PASTA / f"{k}.json")
    temporario = destino.with_suffix(".tmp")
    temporario.write_text(texto, encoding="utf-8")
    temporario.replace(destino)
