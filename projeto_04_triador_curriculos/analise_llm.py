"""
Camada de IA: reordena os melhores com critérios explícitos, explica lacunas e escreve a carta de retorno.
Tudo tem versão por regras (sem chave), sempre marcada como tal. Só texto com dados pessoais redigidos vai para a API.
"""
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado
from pontuacao import Avaliacao, Curriculo, numerar
from privacidade import redigir_pii
from vaga import Vaga

PESO_LLM = 0.4
LIMITE_TEXTO = 12_000


class AvaliacaoLLM(BaseModel):
    nota: int = Field(ge=0, le=100, description="Aderência do candidato à vaga, de 0 a 100")
    justificativa: str = Field(description="2 a 3 frases, citando evidências do currículo")
    pontos_fortes: list[str] = Field(max_length=3)
    lacunas: list[str] = Field(max_length=3, description="O que falta ou é fraco em relação à vaga")
    recomendacao: str = Field(description="Exatamente duas frases: o que fazer com este candidato e por quê")


class CartaRetorno(BaseModel):
    assunto: str
    corpo: str = Field(description="Carta curta, cordial e honesta, sem prometer nada")


def _fatos(av: Avaliacao) -> str:
    return (
        f"Anos de experiência calculados dos períodos: {av.anos:g}. Formação: {av.formacao}. "
        f"Requisitos atendidos: {', '.join(av.atendidos) or 'nenhum'}. "
        f"Desejáveis ausentes: {', '.join(av.ausentes_desejaveis) or 'nenhum'}."
    )


def recomendacao_por_regras(av: Avaliacao, vaga: Vaga) -> str:
    """Duas frases montadas dos fatos; sem IA."""
    if not av.aprovado:
        return (
            f"Não seguir no processo: {av.motivos_reprovacao[0].rstrip('.')}. "
            "Guardar no banco de talentos apenas se o requisito faltante mudar."
        )
    total_desej = len(vaga.requisitos_desejaveis)
    ok_desej = total_desej - len(av.ausentes_desejaveis)
    primeira = (
        f"Atende a todos os {len(vaga.requisitos_obrigatorios)} requisitos obrigatórios, com {av.anos:g} ano(s) de experiência "
        f"e {ok_desej} de {total_desej} desejáveis."
    )
    if av.ausentes_desejaveis:
        segunda = "Vale a entrevista, investigando " + ", ".join(av.ausentes_desejaveis[:3]) + "."
    else:
        segunda = "Vale a entrevista: não há lacuna aparente em relação à vaga."
    return f"{primeira} {segunda}"


def carta_por_regras(av: Avaliacao, vaga: Vaga) -> dict:
    faltas = av.ausentes_obrigatorios or av.ausentes_desejaveis
    estudo = "\n".join(f"- {f}: busque projetos práticos e cursos para demonstrar essa competência." for f in faltas[:4])
    corpo = (
        f"Olá, {av.nome}.\n\nObrigado pelo seu interesse na vaga de {vaga.titulo}. "
        "Depois de analisar o seu currículo, não seguiremos com a sua candidatura neste momento.\n\n"
        "O que pesou na decisão:\n" + "\n".join(f"- {m}" for m in av.motivos_reprovacao) +
        (f"\n\nO que recomendamos estudar para as próximas oportunidades:\n{estudo}" if estudo else "") +
        "\n\nDesejamos sucesso na sua trajetória."
    )
    return {"assunto": f"Sua candidatura para {vaga.titulo}", "corpo": corpo}


def _prompt_avaliacao(av: Avaliacao, curriculo: Curriculo, vaga: Vaga) -> str:
    texto = redigir_pii(curriculo.texto, curriculo.nome)[:LIMITE_TEXTO]
    return (
        "Você avalia a aderência de um candidato a uma vaga, com critérios explícitos e sem viés.\n"
        "CRITÉRIOS: 90-100 excede o pedido; 70-89 atende bem; 50-69 atende o mínimo com lacunas; abaixo de 50 é fraco. "
        "Considere requisitos obrigatórios, tempo e profundidade da experiência e senioridade. "
        "Não penalize a ausência de uma palavra-chave se o texto mostra experiência equivalente. Não invente nada que "
        "não esteja no currículo. Ignore nome, gênero, idade, foto, estado civil e local de moradia.\n\n"
        f"VAGA: {vaga.titulo}\nObrigatórios: {', '.join(vaga.requisitos_obrigatorios)}\n"
        f"Desejáveis: {', '.join(vaga.requisitos_desejaveis)}\nMínimo de anos: {vaga.anos_experiencia_minimos}\n"
        f"Formação mínima: {vaga.formacao_minima}\n\n"
        f"FATOS JÁ VERIFICADOS: {_fatos(av)}\n\nCURRÍCULO (dados pessoais removidos):\n{texto}"
    )


def analisar_candidato(av: Avaliacao, curriculo: Curriculo, vaga: Vaga, client) -> dict:
    """Análise do candidato: da IA se possível, por regras caso contrário (com o motivo)."""
    motivo = MOTIVO_SEM_CHAVE
    if client is not None:
        try:
            r = gerar_estruturado(client, _prompt_avaliacao(av, curriculo, vaga), AvaliacaoLLM, temperatura=0.0)
            return {**r.model_dump(), "origem": "llm", "degradado": False, "motivo_degradado": None}
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)
    return {
        "nota": None, "justificativa": "", "pontos_fortes": [], "lacunas": av.ausentes_desejaveis[:3],
        "recomendacao": recomendacao_por_regras(av, vaga), "origem": "regras", "degradado": True, "motivo_degradado": motivo,
    }


def reordenar_com_llm(avaliacoes: list, curriculos: dict, vaga: Vaga, client, top_n: int = 10, peso_llm: float = PESO_LLM) -> list:
    """
    Os `top_n` melhores pela nota das regras são reavaliados pela IA; a nota deles vira a mistura das duas
    (regras 60%, IA 40%) e eles são reordenados entre si. Quem está abaixo do top_n mantém a nota das regras.
    Análise por regras (marcada) para todos os que não passaram pela IA, inclusive reprovados.
    """
    aprovados = [a for a in avaliacoes if a.aprovado]
    aprovados.sort(key=lambda a: (-a.nota, a.nome))
    finalistas = aprovados[:top_n] if client is not None else []

    with ThreadPoolExecutor(max_workers=4) as pool:
        analises = list(pool.map(lambda a: analisar_candidato(a, curriculos[a.arquivo], vaga, client), finalistas))
    for av, analise in zip(finalistas, analises):
        av.analise = analise
        if analise["origem"] == "llm":
            av.notas_secoes["ia"] = float(analise["nota"])
            av.nota = round((1 - peso_llm) * av.nota + peso_llm * analise["nota"], 1)

    for av in avaliacoes:
        if not av.analise:
            av.analise = analisar_candidato(av, curriculos[av.arquivo], vaga, None)

    finalistas.sort(key=lambda a: (-a.nota, a.nome))
    resto = [a for a in aprovados if a not in finalistas]
    reprovados = [a for a in avaliacoes if not a.aprovado]
    numerar(finalistas + resto + reprovados)
    return finalistas + resto + sorted(reprovados, key=lambda a: (len(a.motivos_reprovacao), a.nome))


def gerar_carta(av: Avaliacao, curriculo: Curriculo, vaga: Vaga, client=None):
    """(carta, degradado, motivo). A carta por regras já cita os motivos reais da reprovação."""
    motivo = MOTIVO_SEM_CHAVE
    if client is not None:
        prompt = (
            "Escreva uma carta de retorno para um candidato que não seguirá no processo. Seja cordial, específico e honesto: "
            "cite os motivos reais abaixo, sugira o que estudar ou praticar para cada lacuna e não prometa nada.\n\n"
            f"VAGA: {vaga.titulo}\nNome do candidato: {av.nome}\nMotivos: {'; '.join(av.motivos_reprovacao) or 'aderência menor que a dos demais finalistas'}\n"
            f"Lacunas: {', '.join(av.ausentes_obrigatorios + av.ausentes_desejaveis) or 'nenhuma específica'}"
        )
        try:
            return gerar_estruturado(client, prompt, CartaRetorno, temperatura=0.3).model_dump(), False, None
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)
    return carta_por_regras(av, vaga), True, motivo
