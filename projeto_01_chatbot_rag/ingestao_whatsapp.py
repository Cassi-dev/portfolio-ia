"""
Módulo de ingestão, sanitização e análise de estilo de conversas do WhatsApp.
Converte exportações .txt e trechos colados em pares estruturados de aprendizado para o banco vetorial.
"""
import os
import re
import json
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Carrega .env do projeto
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from persona_config import carregar_config_privada



PADRAO_IOS = re.compile(
    r"^\[(?P<data>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2}(?::\d{2})?)\]\s+(?P<autor>[^:]+):\s+(?P<texto>.*)$"
)
PADRAO_ANDROID = re.compile(
    r"^(?P<data>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2})\s+-\s+(?P<autor>[^:]+):\s+(?P<texto>.*)$"
)
MENSAGENS_IGNORAR = (
    "as mensagens e as chamadas são protegidas",
    "mensagens e chamadas são protegidas com a criptografia",
    "<mídia oculta>",
    "<arquivo de mídia oculto>",
    "imagem ocultada",
    "áudio ocultado",
    "vídeo ocultado",
    "figurinha omitida",
    "mensagem apagada",
    "você apagou esta mensagem",
    "chamada de voz perdida",
    "chamada de vídeo perdida",
)


@dataclass
class MensagemWhatsApp:
    data: str
    hora: str
    autor: str
    texto: str


@dataclass
class ParConversa:
    pergunta: str
    resposta: str
    interlocutor: str
    autor_resposta: str
    timestamp: str = ""
    contexto_anterior: str = ""
    sensivel: bool = False


def limpar_texto_mensagem(texto: str) -> str:
    """Remove caracteres invisíveis do WhatsApp (como LTR marks) e normaliza espaços."""
    t = texto.replace("\u200e", "").replace("\u200f", "").replace("\xa0", " ").strip()
    return t


def linha_de_sistema(texto: str) -> bool:
    t = texto.lower()
    return any(p in t for p in MENSAGENS_IGNORAR) or len(t) == 0


def parsear_exportacao_whatsapp(conteudo: str) -> list[MensagemWhatsApp]:
    """Lê o texto bruto do WhatsApp (.txt) nos formatos padrão iOS ou Android."""
    linhas = conteudo.splitlines()
    mensagens = []
    msg_atual = None

    for linha in linhas:
        linha_limpa = limpar_texto_mensagem(linha)
        if not linha_limpa:
            continue

        match_ios = PADRAO_IOS.match(linha_limpa)
        match_android = PADRAO_ANDROID.match(linha_limpa)
        m = match_ios or match_android

        if m:
            if msg_atual:
                if not linha_de_sistema(msg_atual.texto):
                    mensagens.append(msg_atual)
            msg_atual = MensagemWhatsApp(
                data=m.group("data"),
                hora=m.group("hora"),
                autor=m.group("autor").strip(),
                texto=m.group("texto").strip()
            )
        else:
            if msg_atual:
                msg_atual.texto += "\n" + linha_limpa

    if msg_atual and not linha_de_sistema(msg_atual.texto):
        mensagens.append(msg_atual)

    return mensagens


def identificar_autores(mensagens: list[MensagemWhatsApp]) -> Counter:
    """Devolve a contagem de mensagens por autor no chat."""
    return Counter(m.autor for m in mensagens)


def extrair_pares_conversa(mensagens: list[MensagemWhatsApp], nome_usuario: str) -> list[ParConversa]:
    """
    Agrupa o diálogo em pares de (Pergunta/Comentário da outra pessoa -> Sua Resposta).
    Se você mandar várias mensagens seguidas, junta em uma resposta coesa.
    """
    nome_alvo = nome_usuario.lower().strip()
    pares = []
    buffer_outro = []
    buffer_usuario = []
    ultimo_autor_outro = "Interlocutor"

    for msg in mensagens:
        eh_usuario = (nome_alvo in msg.autor.lower())
        if not eh_usuario:
            if buffer_usuario and buffer_outro:
                pergunta = "\n".join(buffer_outro).strip()
                resposta = "\n".join(buffer_usuario).strip()
                if pergunta and resposta:
                    pares.append(ParConversa(
                        pergunta=pergunta,
                        resposta=resposta,
                        interlocutor=ultimo_autor_outro,
                        autor_resposta=nome_usuario,
                        timestamp=f"{msg.data} {msg.hora}"
                    ))
                buffer_outro = []
                buffer_usuario = []
            buffer_outro.append(msg.texto)
            ultimo_autor_outro = msg.autor
        else:
            buffer_usuario.append(msg.texto)

    if buffer_usuario and buffer_outro:
        pergunta = "\n".join(buffer_outro).strip()
        resposta = "\n".join(buffer_usuario).strip()
        if pergunta and resposta:
            pares.append(ParConversa(
                pergunta=pergunta,
                resposta=resposta,
                interlocutor=ultimo_autor_outro,
                autor_resposta=nome_usuario
            ))

    return pares


def analisar_estilo_escrita(mensagens_usuario: list[str]) -> dict:
    """
    Extrai o DNA de estilo do autor:
    - Média de caracteres e palavras por mensagem
    - Pontuação e caixa baixa/alta
    - Emojis mais comuns
    - Expressões e termos frequentes
    """
    if not mensagens_usuario:
        return {
            "total_mensagens": 0,
            "media_palavras": 0,
            "media_chars": 0,
            "usa_pontuacao_final": 0.0,
            "usa_maiuscula_inicial": 0.0,
            "termos_frequentes": [],
            "emojis_frequentes": []
        }

    total = len(mensagens_usuario)
    tamanhos_palavras = [len(m.split()) for m in mensagens_usuario]
    tamanhos_chars = [len(m) for m in mensagens_usuario]

    termina_ponto = sum(1 for m in mensagens_usuario if m.rstrip().endswith((".", "!", "?")))
    comeca_maiuscula = sum(1 for m in mensagens_usuario if m and m[0].isupper())

    palavras_todas = []
    emojis = []
    padrao_emoji = re.compile(r"[\U00010000-\U0010ffff]", flags=re.UNICODE)

    for m in mensagens_usuario:
        palavras_todas.extend(re.findall(r"\b[a-zA-ZÀ-ÿ0-9_]{3,}\b", m.lower()))
        emojis.extend(padrao_emoji.findall(m))

    stopwords = {"para", "com", "uma", "você", "voce", "que", "não", "nao", "mais", "mas", "por", "isso", "ele", "ela", "está", "esta", "pra"}
    palavras_filtradas = [p for p in palavras_todas if p not in stopwords]

    termos_top = [termo for termo, _ in Counter(palavras_filtradas).most_common(15)]
    emojis_top = [emoji for emoji, _ in Counter(emojis).most_common(8)]

    return {
        "total_mensagens": total,
        "media_palavras": round(sum(tamanhos_palavras) / max(1, total), 1),
        "media_chars": round(sum(tamanhos_chars) / max(1, total), 1),
        "usa_pontuacao_final_pct": round((termina_ponto / max(1, total)) * 100, 1),
        "usa_maiuscula_inicial_pct": round((comeca_maiuscula / max(1, total)) * 100, 1),
        "termos_frequentes": termos_top,
        "emojis_frequentes": emojis_top
    }


_env_wpp = os.getenv("WPP_SQLITE_PATH", "").strip()
CAMINHO_PADRAO_WPP_SQLITE = Path(_env_wpp) if _env_wpp else None


def carregar_conversas_sqlite(caminho_sqlite=None, nome_usuario: str = "Usuário", config_privada: dict | None = None) -> tuple[list[ParConversa], int, int]:
    """
    Importa diretamente do banco SQLite do bot.
    Agrupa as mensagens cronologicamente por chat e extrai pares de (Pergunta -> Resposta do usuário).
    Devolve (pares_de_conversa, total_mensagens, total_mensagens_do_usuario).
    """
    import sqlite3
    caminho_alvo = caminho_sqlite or CAMINHO_PADRAO_WPP_SQLITE
    if not caminho_alvo:
        return [], 0, 0

    caminho = Path(caminho_alvo)
    if not caminho.exists():
        return [], 0, 0

    cfg = config_privada or carregar_config_privada()
    sensiveis = set(cfg.get("contatos_intimos", []) + cfg.get("termos_sensiveis", []))

    conn = sqlite3.connect(str(caminho))
    cur = conn.cursor()
    
    # O que o clone do Modo Foco mandou fica na tabela clone_sent do bot. Isso não
    # é o usuário escrevendo: se entrasse aqui, o clone aprenderia com ele mesmo
    # e cada repetição viraria "estilo".
    tem_clone_sent = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='clone_sent'"
    ).fetchone() is not None
    filtro_clone = "AND id NOT IN (SELECT message_id FROM clone_sent)" if tem_clone_sent else ""
    query = f"""
        SELECT remote_jid, sender, sender_name, text, timestamp
        FROM messages
        WHERE text IS NOT NULL AND TRIM(text) != '' {filtro_clone}
        ORDER BY remote_jid, timestamp ASC
    """
    linhas = cur.execute(query).fetchall()
    conn.close()

    total_mensagens = len(linhas)
    total_usuario = 0
    pares = []
    
    # Agrupa por chat (remote_jid)
    por_chat = {}
    for rjid, sender, sname, texto, ts in linhas:
        por_chat.setdefault(rjid, []).append((sender, sname or "Contato", texto, ts))

    nome_alvo = nome_usuario.lower().strip()

    for rjid, msgs in por_chat.items():
        buffer_outro = []
        buffer_usuario = []
        ultimo_autor_outro = "Contato"

        for sender, sname, texto, ts in msgs:
            t_limpo = limpar_texto_mensagem(texto)
            if linha_de_sistema(t_limpo):
                continue

            eh_usuario = (nome_alvo in str(sname).lower()) or (nome_alvo in str(sender).lower())
            if eh_usuario:
                total_usuario += 1
                buffer_usuario.append(t_limpo)
            else:
                if buffer_usuario and buffer_outro:
                    p = "\n".join(buffer_outro).strip()
                    r = "\n".join(buffer_usuario).strip()
                    if p and r:
                        eh_sensivel = any(c in str(ultimo_autor_outro).lower() for c in sensiveis) if sensiveis else False
                        pares.append(ParConversa(
                            pergunta=p,
                            resposta=r,
                            interlocutor=ultimo_autor_outro,
                            autor_resposta=nome_usuario,
                            timestamp=str(ts),
                            sensivel=eh_sensivel
                        ))
                    buffer_outro = []
                    buffer_usuario = []
                buffer_outro.append(t_limpo)
                ultimo_autor_outro = sname

        if buffer_usuario and buffer_outro:
            p = "\n".join(buffer_outro).strip()
            r = "\n".join(buffer_usuario).strip()
            if p and r:
                eh_sensivel = any(c in str(ultimo_autor_outro).lower() for c in sensiveis) if sensiveis else False
                pares.append(ParConversa(
                    pergunta=p,
                    resposta=r,
                    interlocutor=ultimo_autor_outro,
                    autor_resposta=nome_usuario,
                    sensivel=eh_sensivel
                ))

    return pares, total_mensagens, total_usuario

