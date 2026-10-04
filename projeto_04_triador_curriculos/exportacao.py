"""Exportação do ranking para o time de RH."""
import csv
import io

COLUNAS = [
    "posicao", "candidato", "arquivo", "situacao", "nota", "nota_competencias", "nota_experiencia", "nota_formacao",
    "anos_experiencia", "formacao", "requisitos_atendidos", "ausentes_obrigatorios", "ausentes_desejaveis",
    "motivos_reprovacao", "recomendacao", "origem_da_analise",
]


def rotulo_anonimo(indice: int) -> str:
    return f"Candidato {indice:02d}"


def ranking_para_csv(avaliacoes: list, anonimo: bool = False) -> bytes:
    """
    CSV com ';' e BOM UTF-8: é o que o Excel em português abre sem estragar acentos e colunas.
    No modo anônimo o nome e o arquivo (que costuma ter o nome) são trocados por "Candidato NN".
    """
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=COLUNAS, delimiter=";", lineterminator="\r\n")
    escritor.writeheader()
    for i, a in enumerate(avaliacoes, 1):
        s = a.notas_secoes
        escritor.writerow({
            "posicao": a.posicao or "",
            "candidato": rotulo_anonimo(i) if anonimo else a.nome,
            "arquivo": "" if anonimo else a.arquivo,
            "situacao": "Aprovado" if a.aprovado else "Reprovado nos requisitos",
            "nota": f"{a.nota:.1f}".replace(".", ",") if a.nota is not None else "",
            "nota_competencias": str(s.get("competencias", "")).replace(".", ","),
            "nota_experiencia": str(s.get("experiencia", "")).replace(".", ","),
            "nota_formacao": str(s.get("formacao", "")).replace(".", ","),
            "anos_experiencia": f"{a.anos:g}".replace(".", ","),
            "formacao": a.formacao,
            "requisitos_atendidos": ", ".join(a.atendidos),
            "ausentes_obrigatorios": ", ".join(a.ausentes_obrigatorios),
            "ausentes_desejaveis": ", ".join(a.ausentes_desejaveis),
            "motivos_reprovacao": " | ".join(a.motivos_reprovacao),
            "recomendacao": (a.analise or {}).get("recomendacao", ""),
            "origem_da_analise": (a.analise or {}).get("origem", ""),
        })
    return ("﻿" + saida.getvalue()).encode("utf-8")
