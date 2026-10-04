import math
import re
import sys
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, criar_cliente, gerar_estruturado

# ==========================================================
# PROCESSO 2: NLP DE SENTIMENTO FINANCEIRO & DECAIMENTO TEMPORAL
# ==========================================================


class ManchetePontuada(BaseModel):
    indice: int = Field(ge=0, description="Número da manchete, como aparece entre colchetes")
    score: float = Field(ge=-1.0, le=1.0, description="-1.0 (pânico) a +1.0 (euforia)")
    classificacao: Literal["Otimista", "Neutro", "Pessimista"]
    motivo: str = Field(description="Justificativa curta")


# --- Léxico de fallback (offline/grátis) ---------------------------------
# Casa palavras inteiras (com plural) e expressões que invertem o sentido,
# como "cai menos que o esperado" (positivo) ou "abaixo do consenso" (negativo).
TERMOS_POSITIVOS = ["alta", "lucro", "dividendo", "recorde", "compra", "sobe", "turbinado", "supera", "otimista", "expansão", "forte"]
TERMOS_NEGATIVOS = ["queda", "prejuízo", "cai", "despenca", "investigação", "rebaixamento", "risco", "crise", "processo", "corte", "multa"]

FRASES_POSITIVAS = [
    r"(?:cai|queda|recua|recuo|perde)\w*\s+(?:menos|menor)\s+que\s+(?:[oa]s?\s+)?(?:esperad\w+|previst\w+|projetad\w+)",
    r"acima\s+d[oa]s?\s+(?:consenso|expectativas?|estimativas?)",
    r"supera(?:m|ndo)?\s+(?:as\s+)?(?:expectativas|estimativas)",
]
FRASES_NEGATIVAS = [
    r"abaixo\s+d[oa]s?\s+(?:consenso|expectativas?|estimativas?)",
    r"decepciona\w*",
]

PESO_TERMO = 0.40


def _regex_termos(termos):
    return re.compile(r"\b(" + "|".join(termos) + r")s?\b")


_RE_POS, _RE_NEG = _regex_termos(TERMOS_POSITIVOS), _regex_termos(TERMOS_NEGATIVOS)
_RE_FRASES_POS = re.compile("|".join(FRASES_POSITIVAS))
_RE_FRASES_NEG = re.compile("|".join(FRASES_NEGATIVAS))


def pontuar_por_lexico(titulo):
    texto = titulo.lower()
    score = 0.0

    for regex, sinal in ((_RE_FRASES_POS, 1), (_RE_FRASES_NEG, -1)):
        achados = regex.findall(texto)
        score += sinal * PESO_TERMO * len(achados)
        texto = regex.sub(" ", texto)

    score += PESO_TERMO * len({m for m in _RE_POS.findall(texto)})
    score -= PESO_TERMO * len({m for m in _RE_NEG.findall(texto)})
    return round(max(-1.0, min(1.0, score)), 2)


def classificar_score(score):
    if score > 0.20:
        return "Otimista"
    if score < -0.20:
        return "Pessimista"
    return "Neutro"


def _montar_prompt(noticias):
    manchetes = "\n".join(f"[{i}] {n['titulo']}" for i, n in enumerate(noticias))
    return (
        "Você é um analista financeiro quantitativo sênior. Avalie o sentimento de mercado "
        "de cada manchete a seguir para as ações da empresa, devolvendo uma entrada por manchete.\n\n"
        "Regras financeiras fundamentais:\n"
        "- score varia de -1.0 (pânico/forte pessimismo) a +1.0 (euforia/forte otimismo).\n"
        "- Fórmulas como 'queda menor que a esperada' ou 'lucro acima do consenso' são OTIMISTAS (+0.5 a +0.8).\n"
        "- Notícias corporativas neutras ficam entre -0.2 e +0.2.\n\n"
        f"MANCHETES:\n{manchetes}"
    )


def pontuar_sentimento_llm(noticias, api_key="", client=None):
    """
    Pontua manchetes com IA (saída estruturada validada, -1.0 a +1.0).
    Toda manchete sai com "motor" ("gemini" ou "lexico"). As que caírem no léxico de
    fallback também levam "motivo_motor", para a interface poder avisar o usuário.
    """
    motivo = MOTIVO_SEM_CHAVE

    if client is None and api_key.strip():
        try:
            client = criar_cliente(api_key)
        except FalhaLLM as e:
            motivo = motivo_falha(e)

    if client is not None:
        try:
            pontuadas = gerar_estruturado(client, _montar_prompt(noticias), list[ManchetePontuada], temperatura=0.0)
            for r in pontuadas:
                if r.indice < len(noticias):
                    noticias[r.indice].update(score=r.score, classificacao=r.classificacao, motivo=r.motivo, motor="gemini")
            motivo = "a IA não devolveu pontuação para esta manchete"
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            print(f"[Aviso] Erro na API do Gemini ({e}). Usando classificador financeiro de fallback.")
            motivo = motivo_falha(e)

    for n in noticias:
        if n.get("motor") == "gemini":
            continue
        score = pontuar_por_lexico(n["titulo"])
        n["score"] = score
        n["classificacao"] = classificar_score(score)
        n["motivo"] = "Análise de termos financeiros"
        n["motor"] = "lexico"
        n["motivo_motor"] = motivo

    return noticias


def aplicar_decaimento_temporal(noticias, meia_vida_dias=5):
    """
    Notícia de 15 dias atrás não move o preço de hoje.
    Peso exponencial relativo a HOJE: peso = 0.5 ^ (dias / meia_vida). Serve para o sinal
    atual e para o feed; a série histórica usa média móvel exponencial por dia (ver cruzamento_precos).
    """
    hoje = datetime.now().date()

    for n in noticias:
        try:
            data_noticia = datetime.strptime(n["data"], "%Y-%m-%d").date()
            dias_passados = max(0, (hoje - data_noticia).days)
        except Exception:
            dias_passados = 0

        peso = math.pow(0.5, dias_passados / meia_vida_dias)
        n["dias_atras"] = dias_passados
        n["peso_temporal"] = round(peso, 3)
        n["score_ponderado"] = round(n["score"] * peso, 3)

    return noticias


if __name__ == "__main__":
    manchetes_exemplo = [
        {"titulo": "Petrobras anuncia dividendos extraordinários de R$ 17 bilhões", "data": "2026-09-18", "fonte": "Valor"},
        {"titulo": "Lucro da Petrobras cai menos que o esperado pelo mercado", "data": "2026-09-15", "fonte": "InfoMoney"},
        {"titulo": "Petrobras enfrenta investigação sobre contratos de refino", "data": "2026-09-01", "fonte": "G1"},
    ]

    print("Testando pontuação de sentimento...")
    resultado = aplicar_decaimento_temporal(pontuar_sentimento_llm(manchetes_exemplo))

    print("\n" + "=" * 70)
    print("RESULTADO DO NLP FINANCEIRO COM DECAIMENTO TEMPORAL:")
    print("=" * 70)
    for r in resultado:
        print(f"Manchete: \"{r['titulo']}\"")
        print(f"  -> Score Bruto: {r['score']} ({r['classificacao']}) [{r['motor']}]")
        print(f"  -> Idade: {r['dias_atras']} dias | Peso Temporal: {r['peso_temporal']}")
        print(f"  -> Score Ponderado: {r['score_ponderado']}")
        print("-" * 70)
