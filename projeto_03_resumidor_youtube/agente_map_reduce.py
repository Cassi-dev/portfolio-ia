import sys
from concurrent.futures import ThreadPoolExecutor

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado, gerar_texto
from esquemas_video import Quiz, SinteseVideo

LIMITE_FATIA_CHARS = 12_000

# ==========================================================
# PROCESSO 2 & 3: MAP-REDUCE & QUIZ COM SAÍDA ESTRUTURADA (Pydantic)
# Toda etapa devolve "degradado" (bool) e "motivo_degradado" (str | None)
# para a interface avisar quando o resultado NÃO veio da IA.
# ==========================================================

def avisos_de_degradacao(res):
    """Lista de avisos legíveis, um por (etapa, motivo), para etapas que caíram em fallback."""
    etapas = {
        "Resumos parciais (map)": res.get("resumos_map", []),
        "Síntese (reduce)": [res.get("sintese", {})],
        "Quiz": [res.get("quiz", {})],
        "Cortes": [res.get("cortes", {})],
        "Roteiro": [res.get("roteiro", {})],
    }
    avisos = []
    for nome, itens in etapas.items():
        motivos = {i.get("motivo_degradado") for i in itens if i.get("degradado")}
        avisos += [f"**{nome}**: {m}" for m in sorted(m for m in motivos if m)]
    return avisos

def montar_fatias(blocos, limite_chars=LIMITE_FATIA_CHARS):
    """Agrupa blocos consecutivos até ~limite_chars, sem cortar nenhum texto no meio."""
    fatias, atual, tamanho = [], [], 0
    for b in blocos:
        if atual and tamanho + len(b["texto"]) > limite_chars:
            fatias.append(atual)
            atual, tamanho = [], 0
        atual.append(b)
        tamanho += len(b["texto"]) + 1
    if atual:
        fatias.append(atual)
    return fatias

def _resumir_fatia(fatia, client, contexto):
    inicio, fim = fatia[0]["timestamp_formatado"], fatia[-1]["timestamp_formatado"]
    texto = " ".join(b["texto"] for b in fatia)
    base = {"inicio": inicio, "fim": fim}

    if not client:
        return {**base, "resumo": texto[:250] + "...", "degradado": True, "motivo_degradado": MOTIVO_SEM_CHAVE}

    prompt = (
        f"{contexto}Sintetize os pontos factuais deste trecho do vídeo (intervalo de tempo {inicio} até {fim}) "
        f"em 2 ou 3 tópicos diretos e objetivos:\n\n{texto}"
    )
    try:
        return {**base, "resumo": gerar_texto(client, prompt, temperatura=0.2), "degradado": False, "motivo_degradado": None}
    except FalhaLLM as e:
        return {**base, "resumo": texto[:250], "degradado": True, "motivo_degradado": motivo_falha(e)}

def etapa_map(blocos, client=None, limite_chars=LIMITE_FATIA_CHARS, contexto="", max_workers=4):
    """
    ETAPA MAP:
    Divide a transcrição em fatias temporais (por tamanho, sem descartar texto) e resume
    cada uma isoladamente e em paralelo. Assim a IA não esquece o meio de vídeos longos.
    """
    fatias = montar_fatias(blocos, limite_chars)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(lambda f: _resumir_fatia(f, client, contexto), fatias))

def etapa_reduce(resumos_parciais, titulo_video="Vídeo", client=None, canal=""):
    """
    ETAPA REDUCE:
    Junta os resumos parciais da etapa Map e pede uma síntese final coesa
    com tópicos por minutagem e conclusão, validada por schema Pydantic.
    """
    texto_combinado = "\n\n".join([
        f"[{r['inicio']} a {r['fim']}]: {r['resumo']}"
        for r in resumos_parciais
    ])

    motivo = MOTIVO_SEM_CHAVE
    if client:
        origem = f"'{titulo_video}'" + (f", do canal {canal}" if canal else "")
        prompt = (
            f"Você é um especialista em síntese de conteúdo. Abaixo estão os resumos cronológicos do vídeo {origem}.\n"
            "Crie um resumo executivo de altíssimo nível, seguido por tópicos navegáveis com marcação de tempo. "
            "Cada timestamp de tópico deve ser um dos inícios de trecho informados entre colchetes.\n\n"
            f"CONTEÚDO:\n{texto_combinado}"
        )
        try:
            resultado = gerar_estruturado(client, prompt, SinteseVideo).model_dump()
            return {**resultado, "degradado": False, "motivo_degradado": None}
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)

    # Fallback honesto: trechos brutos, sem texto genérico fingindo ser síntese
    return {
        "resumo_executivo": "Sem síntese por IA. Trechos iniciais de cada parte do vídeo:\n\n" + "\n\n".join(
            f"[{r['inicio']}] {r['resumo'][:200]}" for r in resumos_parciais[:3]
        ),
        "topicos_com_minutagem": [
            {"timestamp": r["inicio"], "titulo": f"Trecho a partir de {r['inicio']}", "descricao": r["resumo"][:120]}
            for r in resumos_parciais[:5]
        ],
        "conclusao": "",
        "degradado": True,
        "motivo_degradado": motivo,
    }

def gerar_quiz(resumo_sintese, client=None):
    """
    ETAPA 4: Gera um Quiz de 5 questões de múltipla escolha com gabarito.
    Sem IA, devolve lista vazia (uma pergunta genérica inventada não testaria nada).
    """
    if not client:
        return {"perguntas": [], "degradado": True, "motivo_degradado": MOTIVO_SEM_CHAVE}

    prompt = (
        "Com base no resumo e nos tópicos a seguir, crie um QUIZ DE 5 PERGUNTAS de múltipla escolha, com 4 "
        "alternativas cada, para testar o aprendizado do usuário. Só use fatos presentes no conteúdo.\n\n"
        f"RESUMO: {resumo_sintese.get('resumo_executivo', '')}\n\n"
        "TÓPICOS:\n" + "\n".join(
            f"- [{t['timestamp']}] {t['titulo']}: {t['descricao']}"
            for t in resumo_sintese.get("topicos_com_minutagem", [])
        )
    )
    try:
        quiz = gerar_estruturado(client, prompt, Quiz)
    except RespostaInvalida:
        return {"perguntas": [], "degradado": True, "motivo_degradado": MOTIVO_FORMATO}
    except FalhaLLM as e:
        return {"perguntas": [], "degradado": True, "motivo_degradado": motivo_falha(e)}
    return {"perguntas": [p.model_dump() for p in quiz.perguntas], "degradado": False, "motivo_degradado": None}

if __name__ == "__main__":
    print("Módulo Map-Reduce e Quiz carregado com sucesso!")
