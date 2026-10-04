"""
Registro das consultas e feedback (👍/👎), para medir o sistema em uso e para transformar erros reais em perguntas
de teste. Fica só na sua máquina (registros/consultas.jsonl, fora do git) e guarda as PERGUNTAS que você digitou:
desligue com RAG_LOG=0. Arquivo só de acréscimo: o feedback vira uma nova linha ligada ao id da consulta.
"""
import json
import os
import statistics
import time
import uuid
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "registros"


def ativo() -> bool:
    return os.environ.get("RAG_LOG", "1") != "0"


def _arquivo() -> Path:
    return PASTA / "consultas.jsonl"


def _gravar(linha: dict) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    with open(_arquivo(), "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def registrar_consulta(dados: dict) -> str:
    """Grava a consulta e devolve o id (para ligar o feedback). Sem efeito se RAG_LOG=0."""
    identificador = uuid.uuid4().hex[:12]
    if ativo():
        _gravar({"tipo": "consulta", "id": identificador, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **dados})
    return identificador


def registrar_feedback(identificador: str, valor: int, comentario: str = "") -> None:
    if ativo() and valor in (-1, 1):
        _gravar({"tipo": "feedback", "id": identificador, "valor": valor, "comentario": comentario,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%S")})


def carregar() -> list:
    try:
        with open(_arquivo(), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


def _percentil(valores: list, p: float) -> float:
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, int(p * len(ordenados)))]


def resumo_metricas(registros: list) -> dict:
    consultas = {r["id"]: r for r in registros if r["tipo"] == "consulta"}
    if not consultas:
        return {"consultas": 0}
    feedback = {}
    for r in registros:
        if r["tipo"] == "feedback" and r["id"] in consultas:
            feedback[r["id"]] = r["valor"]                     # o último voto vale
    latencias = [c["latencias_ms"]["total"] for c in consultas.values() if c.get("latencias_ms", {}).get("total") is not None]
    respondidas = [c for c in consultas.values() if c.get("decisao") == "respondeu"]
    return {
        "consultas": len(consultas),
        "pct_nao_sei": round(100 * (1 - len(respondidas) / len(consultas))),
        "latencia_mediana_ms": round(statistics.median(latencias)) if latencias else None,
        "latencia_p95_ms": round(_percentil(latencias, 0.95)) if latencias else None,
        "com_feedback": len(feedback),
        "pct_positivo": round(100 * sum(v == 1 for v in feedback.values()) / len(feedback)) if feedback else None,
    }


def candidatos_a_gabarito(registros: list) -> list:
    """
    Consultas com 👎 respondidas (possível erro do sistema) e 👍 (possível acerto), para a pessoa revisar e, se fizer
    sentido, copiar para o gabarito. Nada entra no gabarito sozinho.
    """
    consultas = {r["id"]: r for r in registros if r["tipo"] == "consulta"}
    votos = {r["id"]: r["valor"] for r in registros if r["tipo"] == "feedback" and r["id"] in consultas}
    saida = []
    for identificador, valor in votos.items():
        c = consultas[identificador]
        saida.append({
            "pergunta": c.get("pergunta", ""), "decisao": c.get("decisao"), "voto": "positivo" if valor == 1 else "negativo",
            "arquivo_do_melhor_trecho": (c.get("trechos") or [{}])[0].get("arquivo"),
            "revisar": "verificar se o trecho certo estava entre os recuperados" if valor == -1 else "",
        })
    return sorted(saida, key=lambda x: x["voto"])
