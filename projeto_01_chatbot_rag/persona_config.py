"""
Módulo de configuração privada da Persona.
Isola contatos íntimos, termos sensíveis e padrões regex de bloqueio em arquivo local
não versionado (persona_privado.json), com fallback gracioso em modo degradado.
"""
import json
import logging
from pathlib import Path

log = logging.getLogger("persona_config")

DIRETORIO_PERSONA = Path(__file__).resolve().parent
CAMINHO_CONFIG_PRIVADA = DIRETORIO_PERSONA / "persona_privado.json"
CAMINHO_CONFIG_EXEMPLO = DIRETORIO_PERSONA / "persona_privado.exemplo.json"

_caminho_override: Path | None = None


def definir_caminho_config_privada(caminho: Path | str | None) -> None:
    """Permite apontar para um arquivo de configuração temporário (ex.: em testes)."""
    global _caminho_override
    _caminho_override = Path(caminho) if caminho else None


def obter_caminho_config_privada() -> Path:
    """Retorna o caminho atual do arquivo de configuração privada."""
    return _caminho_override or CAMINHO_CONFIG_PRIVADA


def config_privada_existe() -> bool:
    """Verifica se o arquivo de configuração privada existe."""
    return obter_caminho_config_privada().exists()


def carregar_config_privada(caminho: Path | str | None = None) -> dict:
    """
    Lê a configuração privada da persona.
    Se o arquivo não existir, devolve listas vazias (modo degradado).

    Retorna:
        dict com chaves:
            - contatos_intimos: list[str] (em minúsculas)
            - termos_sensiveis: list[str] (em minúsculas)
            - padroes_bloqueados: list[str] (padrões regex preservados)
    """
    c = Path(caminho) if caminho else obter_caminho_config_privada()
    if not c.exists():
        return {
            "contatos_intimos": [],
            "termos_sensiveis": [],
            "padroes_bloqueados": []
        }

    try:
        conteudo = c.read_text(encoding="utf-8")
        dados = json.loads(conteudo)
        return {
            "contatos_intimos": [str(x).lower().strip() for x in dados.get("contatos_intimos", []) if str(x).strip()],
            "termos_sensiveis": [str(x).lower().strip() for x in dados.get("termos_sensiveis", []) if str(x).strip()],
            "padroes_bloqueados": [str(x).strip() for x in dados.get("padroes_bloqueados", []) if str(x).strip()]
        }
    except Exception as e:
        log.warning("Falha ao ler configuração privada em %s: %s", c, e)
        return {
            "contatos_intimos": [],
            "termos_sensiveis": [],
            "padroes_bloqueados": []
        }
