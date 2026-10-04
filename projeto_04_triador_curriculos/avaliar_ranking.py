"""
Mede a qualidade do ranking contra o gabarito dos currículos fictícios (nota de aderência 0 a 3).

    python projeto_04_triador_curriculos/avaliar_ranking.py

Compara: (a) só cosseno, o ingênuo; (b) regras sem o filtro obrigatório; (c) regras completas.
Métricas: NDCG@10, precisão@5 (nota >= 2), quantos currículos de nota 0 ficam no top 10 e quantos
de nota 3 aparecem entre as 8 primeiras posições. Resultado em resultados/avaliacao_ranking.json.
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent


def ndcg_em_k(notas_na_ordem: list, k: int = 10) -> float:
    """NDCG com ganho 2^nota - 1: acertar o topo vale muito mais do que acertar o fim."""
    def dcg(notas):
        return sum((2 ** n - 1) / math.log2(i + 2) for i, n in enumerate(notas[:k]))
    ideal = dcg(sorted(notas_na_ordem, reverse=True))
    return dcg(notas_na_ordem) / ideal if ideal else 0.0


def metricas(arquivos_na_ordem: list, nota_de: dict, k: int = 10) -> dict:
    notas = [nota_de[a] for a in arquivos_na_ordem]
    topo = notas[:k]
    n3 = sum(1 for n in nota_de.values() if n == 3)
    return {
        "ndcg@10": round(ndcg_em_k(notas, k), 3),
        "precisao@5 (nota>=2)": round(sum(1 for n in notas[:5] if n >= 2) / 5, 2),
        "nota_0_no_top10": sum(1 for n in topo if n == 0),
        f"nota_3_entre_as_{n3}_primeiras": sum(1 for n in notas[:n3] if n == 3),
    }


def _traduzir_cabecalhos(texto: str) -> str:
    ingles = {
        "Experiência Profissional": "Professional Experience", "Experiência": "Experience", "Histórico Profissional": "Work Experience",
        "Formação Acadêmica": "Education", "Formação": "Education", "Educação": "Education", "Competências": "Skills",
        "Habilidades Técnicas": "Technical Skills", "Resumo Profissional": "Summary", "Perfil": "Profile", "Resumo": "Summary", "Idiomas": "Languages",
    }
    return "\n".join(ingles.get(l.strip(), l) for l in texto.splitlines())


def _sem_cabecalhos(texto: str) -> str:
    from secoes import _CABECALHO_PARA_SECAO
    from texto import chave
    return "\n".join(l for l in texto.splitlines() if chave(l).strip(" :") not in _CABECALHO_PARA_SECAO)


def perturbacoes() -> dict:
    from texto import sem_acentos
    return {
        "sem acentos": sem_acentos,
        "TUDO EM MAIÚSCULAS": str.upper,
        "cabeçalhos em inglês": _traduzir_cabecalhos,
        "sem cabeçalhos (estrutura não reconhecida)": _sem_cabecalhos,
    }


def carregar():
    from privacidade import extrair_nome
    from pontuacao import Curriculo
    from texto import extrair_texto_pdf
    from vaga import extrair_vaga_por_regras

    gabarito = json.loads((BASE / "dados" / "gabarito.json").read_text(encoding="utf-8"))
    vaga = extrair_vaga_por_regras((BASE / "dados" / "vaga_exemplo.txt").read_text(encoding="utf-8"))
    curriculos = []
    for item in gabarito["curriculos"]:
        texto = extrair_texto_pdf(BASE / "dados" / "curriculos_ficticios" / item["arquivo"])
        curriculos.append(Curriculo(nome=extrair_nome(texto, item["arquivo"]), arquivo=item["arquivo"], texto=texto))
    return vaga, curriculos, gabarito["curriculos"], date.fromisoformat(gabarito["hoje"])


def extracao(vaga, curriculos, itens, hoje) -> dict:
    """Sub-tarefas com verdade-base própria: tempo de experiência, seções e detecção dos requisitos da vaga."""
    from experiencia import calcular_experiencia
    from habilidades import avaliar_requisito
    from secoes import dividir_secoes

    por_arquivo = {i["arquivo"]: i for i in itens}
    erros_anos, reconhecidas, tp, fp, fn = [], 0, 0, 0, 0
    requisitos = vaga.requisitos_obrigatorios + vaga.requisitos_desejaveis
    for c in curriculos:
        s = dividir_secoes(c.texto)
        reconhecidas += s.reconhecida
        erros_anos.append(abs(calcular_experiencia(s.obter("experiencia", c.texto), hoje).anos - por_arquivo[c.arquivo]["anos_reais"]))
        verdade = {h.lower() for h in por_arquivo[c.arquivo]["habilidades"]}
        for r in requisitos:
            previsto, real = avaliar_requisito(r, c.texto).atendido, r.lower() in verdade
            tp += previsto and real
            fp += previsto and not real
            fn += real and not previsto
    return {
        "erro_medio_absoluto_de_anos": round(sum(erros_anos) / len(erros_anos), 2),
        "erro_maximo_de_anos": round(max(erros_anos), 1),
        "secoes_reconhecidas": f"{reconhecidas}/{len(curriculos)}",
        "requisitos_precisao": round(tp / (tp + fp), 3) if tp + fp else 0.0,
        "requisitos_revocacao": round(tp / (tp + fn), 3) if tp + fn else 0.0,
    }


def robustez(vaga, curriculos, nota_de, hoje, aprovados_base) -> dict:
    from pontuacao import Curriculo, ranquear

    saida = {}
    for nome, f in perturbacoes().items():
        pert = [Curriculo(c.nome, c.arquivo, f(c.texto)) for c in curriculos]
        ranking = ranquear(pert, vaga, hoje=hoje)
        m = metricas([a.arquivo for a in ranking], nota_de)
        m["mudou_de_aprovado_para_reprovado_ou_vice_versa"] = len(aprovados_base ^ {a.arquivo for a in ranking if a.aprovado})
        saida[nome] = m
    return saida


def avaliar() -> dict:
    from core.embeddings import similaridade_cosseno
    from pontuacao import ranquear

    vaga, curriculos, itens, hoje = carregar()
    nota_de = {i["arquivo"]: i["nota"] for i in itens}
    resultados = {}

    so_cosseno = sorted(curriculos, key=lambda c: -similaridade_cosseno(vaga.descricao, c.texto))
    resultados["so_cosseno"] = metricas([c.arquivo for c in so_cosseno], nota_de)

    sem_filtro = ranquear(curriculos, vaga, hoje=hoje, filtrar=False)
    resultados["regras_sem_filtro"] = metricas([a.arquivo for a in sem_filtro], nota_de)

    completo = ranquear(curriculos, vaga, hoje=hoje)
    resultados["regras_completas"] = metricas([a.arquivo for a in completo], nota_de)

    aprovados = {a.arquivo for a in completo if a.aprovado}
    erros = {
        "reprovados_indevidamente (nota>=1)": sorted(f for f, n in nota_de.items() if n >= 1 and f not in aprovados),
        "aprovados_indevidamente (nota=0)": sorted(f for f, n in nota_de.items() if n == 0 and f in aprovados),
    }
    resumo = {
        "curriculos": len(curriculos), "metodos": resultados, "erros_do_filtro": erros,
        "extracao": extracao(vaga, curriculos, itens, hoje),
        "robustez": robustez(vaga, curriculos, nota_de, hoje, aprovados),
    }
    destino = BASE / "resultados"
    destino.mkdir(exist_ok=True)
    (destino / "avaliacao_ranking.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return resumo


def imprimir(resumo: dict) -> None:
    print(f"\n{resumo['curriculos']} currículos fictícios, vaga de exemplo.\n")
    chaves = list(next(iter(resumo["metodos"].values())))
    print("| Método | " + " | ".join(chaves) + " |")
    print("|---|" + "---|" * len(chaves))
    nomes = {"so_cosseno": "Só cosseno (ingênuo)", "regras_sem_filtro": "Regras, sem o filtro obrigatório", "regras_completas": "Regras completas"}
    for metodo, m in resumo["metodos"].items():
        print(f"| {nomes[metodo]} | " + " | ".join(str(m[c]) for c in chaves) + " |")
    print("\nErros do filtro:")
    for nome, arquivos in resumo["erros_do_filtro"].items():
        print(f"  {nome}: {len(arquivos)} {arquivos if arquivos else ''}")
    print("\nExtração (verdade-base própria):")
    for nome, valor in resumo["extracao"].items():
        print(f"  {nome}: {valor}")
    print("\nRobustez a variações de formato (regras completas):")
    print("| Variação | ndcg@10 | nota 0 no top 10 | aprovações que mudaram |\n|---|---|---|---|")
    for nome, m in resumo["robustez"].items():
        print(f"| {nome} | {m['ndcg@10']} | {m['nota_0_no_top10']} | {m['mudou_de_aprovado_para_reprovado_ou_vice_versa']} |")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    imprimir(avaliar())
