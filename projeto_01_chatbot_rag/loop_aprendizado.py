"""
Harness de Aprendizado Contínuo & Avaliação de Estilo:
Mede a fidelidade do tom de voz e atualiza o banco de memória sempre que houver
uma nova conversa ou quando o usuário corrigir a resposta da IA.
"""
import re
from pathlib import Path
from ingestao_whatsapp import ParConversa
from motor_persona import MotorPersona, salvar_perfil_estilo

CLICHES_ROBOTICOS = (
    "como posso te ajudar hoje",
    "como posso ajudar",
    "certamente!",
    "com certeza, aqui está",
    "espero ter ajudado",
    "qualquer dúvida estou à disposição",
    "qualquer dúvida é só chamar",
    "sinta-se à vontade para perguntar",
    "não hesite em perguntar",
    "espero que esta resposta seja útil",
)


def avaliar_fidelidade_estilo(resposta: str, perfil: dict) -> dict:
    """
    Avalia em 0 a 100 quão fiel a resposta gerada está do estilo natural do autor:
    1. Penaliza clichês corporativos e robóticos de IA.
    2. Avalia proporção de tamanho em relação à média habitual.
    3. Verifica presença orgânica de termos frequentes.
    """
    t = resposta.strip().lower()
    pontos = 100
    alertas = []

    # 1. Penalidade severa para clichês de IA
    for cliche in CLICHES_ROBOTICOS:
        if cliche in t:
            pontos -= 28
            alertas.append(f"Usou clichê robótico de IA: '{cliche}'")

    # 2. Avaliação de tamanho (evita 'textão' artificial)
    palavras = len(resposta.split())
    media = perfil.get("media_palavras", 14)
    if palavras > media * 3.5:
        pontos -= 22
        alertas.append(f"Mensagem muito longa ({palavras} palavras vs média habitual de {media})")
    elif palavras < max(2, media * 0.25) and media > 6:
        pontos -= 10
        alertas.append(f"Mensagem muito curta ({palavras} palavras)")

    # 3. Termos frequentes e naturalidade
    termos = perfil.get("termos_frequentes", [])
    achou_termo = any(re.search(rf"\b{re.escape(termo.lower())}\b", t) for termo in termos)
    if achou_termo:
        pontos = min(100, pontos + 5)
    else:
        # Não é obrigatório ter o termo, mas avisa se o tom parecer genérico
        pass

    score = max(10, min(100, pontos))
    return {
        "score_estilo": score,
        "aprovado": score >= 75,
        "alertas": alertas,
        "palavras": palavras,
        "media_esperada": media
    }


def aprender_com_correcao(motor: MotorPersona, pergunta: str, resposta_corrigida: str, autor: str = "Usuário") -> dict:
    """
    Loop de Auto-Atualização:
    Quando o usuário diz 'Eu não responderia assim, responderia X',
    o Harness pega o par (pergunta -> resposta_corrigida) e indexa no ChromaDB imediatamente.
    """
    resposta_limpa = resposta_corrigida.strip()
    if not resposta_limpa or not pergunta.strip():
        return {"sucesso": False, "motivo": "Pergunta ou resposta em branco"}

    par = ParConversa(
        pergunta=pergunta.strip(),
        resposta=resposta_limpa,
        interlocutor="Interlocutor",
        autor_resposta=autor
    )

    qtd = motor.indexar_pares([par], atualizar_estilo=False)
    total_memoria = motor.colecao.count()

    return {
        "sucesso": True,
        "exemplos_adicionados": qtd,
        "total_exemplos_memoria": total_memoria,
        "mensagem": f"Memória atualizada com sucesso! Total de exemplos acumulados: {total_memoria}."
    }


def loop_geracao_com_guardrail(motor: MotorPersona, pergunta: str, historico: list = None,
                              client=None, api_key: str = "", max_tentativas: int = 2) -> dict:
    """
    Loop reativo com inspeção: gera a resposta e, se detectar clichê robótico,
    refaz a chamada com reforço anti-robô automático.
    """
    tentativa = 0
    while tentativa < max_tentativas:
        tentativa += 1
        resultado = motor.gerar_resposta(pergunta, historico=historico, client=client, api_key=api_key)
        avaliacao = avaliar_fidelidade_estilo(resultado["resposta"], motor.perfil)

        if avaliacao["aprovado"] or resultado.get("degradado"):
            return {**resultado, "avaliacao": avaliacao, "tentativas": tentativa}

        # Se falhou por clichê robótico, ajusta a temperatura e tenta mais uma vez
    return {**resultado, "avaliacao": avaliacao, "tentativas": tentativa}


def sincronizar_banco_wpp_summarizer(motor: MotorPersona, caminho_sqlite=None, nome_usuario: str = "Usuário") -> dict:
    """
    Harness de Sincronização Contínua:
    Puxa todas as conversas do banco SQLite do bot wpp-ai-summarizer e indexa no ChromaDB da persona.

    Só calcula vetor dos pares que ainda não estão na memória (o ID é o hash do
    par): o servidor_bridge chama isto de tempos em tempos, e reindexar tudo a
    cada vez custava ~20s de CPU. O perfil de estilo é recalculado sobre todas
    as conversas, não só sobre as novas.

    Também processa feedbacks (reações 👍👎) do bot e atualiza prioridades no ChromaDB.
    """
    import hashlib
    import sqlite3
    from ingestao_whatsapp import carregar_conversas_sqlite, CAMINHO_PADRAO_WPP_SQLITE
    from pathlib import Path

    pares, total_msgs, total_usuario = carregar_conversas_sqlite(caminho_sqlite, nome_usuario=nome_usuario)
    if not pares:
        return {"sucesso": False, "motivo": "Nenhuma conversa encontrada ou banco SQLite inexistente", "pares_indexados": 0}

    existentes = set(motor.colecao.get(include=[])["ids"])
    novos = [
        p for p in pares
        if hashlib.sha1(f"{p.pergunta}\x1f{p.resposta}".encode("utf-8")).hexdigest()[:20] not in existentes
    ]
    salvos = motor.indexar_pares(novos, atualizar_estilo=False) if novos else 0
    if salvos:
        motor.atualizar_perfil_estilo([p.resposta for p in pares])

    # Processa feedbacks (reações 👍👎) das respostas do clone
    stats_feedback = {"atualizados": 0, "media_rating": 0, "por_contato": {}}
    try:
        caminho_banco = caminho_sqlite or CAMINHO_PADRAO_WPP_SQLITE
        if caminho_banco:
            path_bot_db = Path(caminho_banco)
            if path_bot_db.exists():
                conn = sqlite3.connect(str(path_bot_db))
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                # Lê feedbacks que têm rating (não NULL)
                feedbacks = cur.execute("""
                    SELECT message_id, sender_name, response_text, rating
                    FROM clone_responses_feedback
                    WHERE rating IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 100
                """).fetchall()

            if feedbacks:
                feedbacks_lista = [dict(fb) for fb in feedbacks]
                stats_feedback = motor.aprender_com_feedback(feedbacks_lista)

            conn.close()
    except Exception as e:
        import logging
        logging.getLogger("loop_aprendizado").warning("Erro ao processar feedbacks: %s", e)

    return {
        "sucesso": True,
        "total_mensagens_banco": total_msgs,
        "mensagens_usuario": total_usuario,
        "pares_indexados": salvos,
        "total_memoria": motor.colecao.count(),
        "feedback": stats_feedback
    }
