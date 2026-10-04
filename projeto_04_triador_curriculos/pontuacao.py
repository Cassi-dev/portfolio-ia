"""
Pontuação de currículos contra uma vaga.

1. FILTRO: requisito obrigatório, anos mínimos e formação mínima reprovam ANTES de qualquer nota
   (senão o ranking mente: alguém sem o requisito principal ficaria "quase aprovado").
2. NOTA por seção (competências, experiência, formação), cada uma de 0 a 100, e a nota final é a média
   ponderada, também de 0 a 100. Ninguém em RH sabe interpretar um cosseno de 0,78, então ele nunca aparece.
3. O cosseno entra só como um componente (25% de competências, 30% de experiência). Ele não distingue
   2 anos de experiência de 10; quem distingue é o tempo calculado dos períodos.
"""
from dataclasses import asdict, dataclass, field
from datetime import date

from experiencia import calcular_experiencia
from formacao import NIVEIS, PONTOS, atende_formacao, nivel_formacao
from habilidades import avaliar_requisito
from secoes import dividir_secoes
from vaga import Vaga

PESOS_PADRAO = {"competencias": 0.45, "experiencia": 0.40, "formacao": 0.15}
TOLERANCIA_ANOS = 0.25                # 3 meses: períodos só com ano são estimados de forma conservadora
SIM_MIN, SIM_MAX = 0.85, 0.95         # calibrado no e5-small: vaga x experiência dos currículos de dev fica em 0,92-0,95, marketing em 0,89


@dataclass
class Curriculo:
    nome: str
    arquivo: str
    texto: str


@dataclass
class Avaliacao:
    nome: str
    arquivo: str
    aprovado: bool = True
    motivos_reprovacao: list = field(default_factory=list)
    nota: float | None = None
    notas_secoes: dict = field(default_factory=dict)
    anos: float = 0.0
    fonte_anos: str = "nenhuma"
    formacao: str = "nenhuma"
    atendidos: list = field(default_factory=list)
    ausentes_obrigatorios: list = field(default_factory=list)
    ausentes_desejaveis: list = field(default_factory=list)
    evidencias: dict = field(default_factory=dict)
    estrutura_reconhecida: bool = True
    posicao: int | None = None
    analise: dict = field(default_factory=dict)

    def para_dict(self) -> dict:
        return asdict(self)


def _cosseno_para_pontos(cosseno: float) -> float:
    return 100 * min(1.0, max(0.0, (cosseno - SIM_MIN) / (SIM_MAX - SIM_MIN)))


def _cosseno_padrao(a: str, b: str) -> float:
    from core.embeddings import similaridade_cosseno
    return similaridade_cosseno(a, b)


def texto_dos_requisitos(vaga: Vaga) -> str:
    partes = []
    if vaga.requisitos_obrigatorios:
        partes.append("Requisitos: " + ", ".join(vaga.requisitos_obrigatorios) + ".")
    if vaga.requisitos_desejaveis:
        partes.append("Desejável: " + ", ".join(vaga.requisitos_desejaveis) + ".")
    return " ".join(partes) or vaga.titulo


def avaliar_curriculo(curriculo: Curriculo, vaga: Vaga, pesos: dict | None = None, hoje: date | None = None,
                      similaridade=None, filtrar: bool = True) -> Avaliacao:
    pesos = pesos or PESOS_PADRAO
    similaridade = similaridade or _cosseno_padrao
    texto = curriculo.texto
    secoes = dividir_secoes(texto)
    av = Avaliacao(nome=curriculo.nome, arquivo=curriculo.arquivo, estrutura_reconhecida=secoes.reconhecida)

    texto_exp = secoes.obter("experiencia", texto)
    texto_comp = secoes.obter("competencias", texto)
    texto_form = secoes.obter("formacao", texto)

    exp = calcular_experiencia(texto_exp, hoje)
    av.anos, av.fonte_anos = exp.anos, exp.fonte
    av.formacao = nivel_formacao(texto_form)

    # --- 1. filtro -------------------------------------------------------------------------------
    for req in vaga.requisitos_obrigatorios:
        r = avaliar_requisito(req, texto)
        if r.atendido:
            av.atendidos.append(req)
            if r.evidencia:
                av.evidencias[req] = r.evidencia
        else:
            av.ausentes_obrigatorios.append(req)
    if av.ausentes_obrigatorios:
        av.motivos_reprovacao.append("Não atende ao(s) requisito(s) obrigatório(s): " + ", ".join(av.ausentes_obrigatorios))
    if vaga.anos_experiencia_minimos and av.anos + TOLERANCIA_ANOS < vaga.anos_experiencia_minimos:
        av.motivos_reprovacao.append(f"Experiência de {av.anos:g} ano(s) encontrada, a vaga pede no mínimo {vaga.anos_experiencia_minimos}")
    if not atende_formacao(av.formacao, vaga.formacao_minima):
        av.motivos_reprovacao.append(f"Formação identificada: {av.formacao}; a vaga pede no mínimo {vaga.formacao_minima}")

    desejaveis_ok = []
    for req in vaga.requisitos_desejaveis:
        r = avaliar_requisito(req, texto)
        (desejaveis_ok if r.atendido else av.ausentes_desejaveis).append(req)
        if r.atendido and r.evidencia:
            av.evidencias[req] = r.evidencia
    av.atendidos += desejaveis_ok

    if av.motivos_reprovacao and filtrar:       # filtrar=False só existe para medir o que o filtro contribui
        av.aprovado = False
        return av

    # --- 2. nota por seção -----------------------------------------------------------------------
    n_obrig, n_desej = len(vaga.requisitos_obrigatorios), len(vaga.requisitos_desejaveis)
    peso_total = 2 * n_obrig + n_desej
    cobertura = 100 * (2 * n_obrig + len(desejaveis_ok)) / peso_total if peso_total else 100.0
    sim_comp = _cosseno_para_pontos(similaridade(texto_dos_requisitos(vaga), texto_comp)) if texto_comp else 0.0
    competencias = 0.75 * cobertura + 0.25 * sim_comp

    alvo_anos = max(vaga.anos_experiencia_minimos + 3, 3)
    pontos_anos = 100 * min(av.anos / alvo_anos, 1.0)
    sim_exp = _cosseno_para_pontos(similaridade(vaga.descricao or texto_dos_requisitos(vaga), texto_exp)) if texto_exp else 0.0
    experiencia = 0.7 * pontos_anos + 0.3 * sim_exp

    referencia = vaga.formacao_minima if vaga.formacao_minima != "nenhuma" else "graduacao"
    formacao = min(100.0, 100 * PONTOS[av.formacao] / PONTOS[referencia])

    av.notas_secoes = {"competencias": round(competencias, 1), "experiencia": round(experiencia, 1), "formacao": round(formacao, 1)}
    soma = sum(pesos.values()) or 1.0
    av.nota = round(sum(av.notas_secoes[s] * pesos.get(s, 0) for s in av.notas_secoes) / soma, 1)
    return av


def numerar(avaliacoes: list) -> list:
    """Aprovados por nota (desempate por nome); reprovados depois, com menos motivos primeiro."""
    aprovados = sorted((a for a in avaliacoes if a.aprovado), key=lambda a: (-a.nota, a.nome))
    reprovados = sorted((a for a in avaliacoes if not a.aprovado), key=lambda a: (len(a.motivos_reprovacao), a.nome))
    for i, a in enumerate(aprovados, 1):
        a.posicao = i
    for a in reprovados:
        a.posicao = None
    return aprovados + reprovados


def ranquear(curriculos: list, vaga: Vaga, pesos: dict | None = None, hoje: date | None = None, similaridade=None,
             filtrar: bool = True) -> list:
    return numerar([avaliar_curriculo(c, vaga, pesos, hoje, similaridade, filtrar) for c in curriculos])
