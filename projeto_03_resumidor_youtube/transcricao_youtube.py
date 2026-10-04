import sys
import os
import re
import json
import math
import urllib.parse
import urllib.request

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from youtube_transcript_api import YouTubeTranscriptApi

# ==========================================================
# PROCESSO 1: EXTRAÇÃO & LIMPEZA DE TRANSCRIÇÃO COM TIMESTAMPS
# ==========================================================

def extrair_id_video(url_ou_id):
    """
    Extrai o ID de 11 caracteres do YouTube a partir de qualquer formato:
    - https://www.youtube.com/watch?v=M7lc1UVf-VE
    - https://youtu.be/M7lc1UVf-VE
    - https://www.youtube.com/shorts/M7lc1UVf-VE
    """
    url_limpa = url_ou_id.strip()
    padroes = [
        r'[?&]v=([0-9A-Za-z_-]{11})',
        r'youtu\.be/([0-9A-Za-z_-]{11})',
        r'youtube\.com/(?:shorts|embed|live|v)/([0-9A-Za-z_-]{11})'
    ]
    for p in padroes:
        match = re.search(p, url_limpa)
        if match:
            return match.group(1)
            
    if len(url_limpa) == 11 and re.match(r'^[0-9A-Za-z_-]{11}$', url_limpa):
        return url_limpa
        
    return None

def segundos_para_tempo(segundos):
    seg = int(segundos)
    horas = seg // 3600
    minutos = (seg % 3600) // 60
    s = seg % 60
    if horas > 0:
        return f"{horas:02d}:{minutos:02d}:{s:02d}"
    return f"{minutos:02d}:{s:02d}"

def obter_metadados_video(video_id, timeout=8):
    """Título e canal via oEmbed do YouTube (sem chave). Dá contexto ao LLM e falha sem quebrar nada."""
    padrao = {"titulo": f"Vídeo {video_id}", "canal": ""}
    url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(f"https://www.youtube.com/watch?v={video_id}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resposta:
            dados = json.load(resposta)
        return {"titulo": dados.get("title") or padrao["titulo"], "canal": dados.get("author_name", "")}
    except Exception:
        return padrao

def texto_para_prompt(blocos, max_chars, formatar):
    """
    Transcrição inteira em texto. Só se passar de max_chars é que amostra blocos espaçados
    de forma uniforme (cobrindo o vídeo todo, em vez de cortar tudo depois do minuto N).
    Devolve (texto, foi_amostrado).
    """
    linhas = [formatar(b) for b in blocos]
    total = sum(len(l) + 1 for l in linhas)
    if total <= max_chars:
        return "\n".join(linhas), False
    passo = math.ceil(total / max_chars)
    return "\n".join(linhas[::passo]), True

def tempo_para_segundos(texto):
    """Inverso de segundos_para_tempo: "MM:SS" ou "HH:MM:SS" -> segundos, ou None se inválido."""
    try:
        partes = [int(p) for p in str(texto).strip().split(":")]
    except ValueError:
        return None
    if not 1 < len(partes) <= 3 or any(p < 0 for p in partes):
        return None
    segundos = 0
    for p in partes:
        segundos = segundos * 60 + p
    return segundos

class SemTranscricao(Exception):
    """
    O YouTube não entregou o texto da fala. `sem_legenda` diz se o vídeo simplesmente não tem legenda (aí o
    caminho é editar sem a análise); do contrário, foi bloqueio ou vídeo indisponível.
    """

    def __init__(self, mensagem: str, sem_legenda: bool = False):
        super().__init__(mensagem)
        self.sem_legenda = sem_legenda


def explicar_falha(erro: Exception) -> tuple:
    """(mensagem em português, é falta de legenda?) a partir da exceção da youtube-transcript-api."""
    nome = type(erro).__name__
    if nome in ("TranscriptsDisabled", "NoTranscriptFound", "StopIteration"):
        return ("Este vídeo está com a legenda desativada no YouTube (nem a automática existe). A análise — "
                "resumo, cortes e roteiro — lê o texto da fala, e sem ele não tem o que ler.", True)
    if nome in ("VideoUnavailable", "VideoUnplayable", "InvalidVideoId"):
        return "O vídeo está indisponível: privado, removido ou bloqueado na sua região.", False
    if nome == "AgeRestricted":
        return ("O vídeo tem restrição de idade: o YouTube só mostra a legenda para quem está logado.", False)
    if nome in ("IpBlocked", "RequestBlocked", "PoTokenRequired", "YouTubeRequestFailed", "HTTPError"):
        return ("O YouTube recusou o pedido deste computador — acontece depois de muitas leituras seguidas. "
                "Espere alguns minutos e tente de novo.", False)
    return f"Não consegui ler a legenda do vídeo ({nome}: {str(erro)[:160]}).", False


def obter_transcricao_formatada(video_id):
    """
    Obtém a legenda (manual ou automática) em português ou inglês e agrupa
    em blocos legíveis com marcação de tempo.
    """
    api = YouTubeTranscriptApi()
    
    try:
        tl = api.list(video_id)
        
        # Tenta português (manual ou automático)
        transcript = None
        for lang in ['pt', 'pt-BR']:
            try:
                transcript = tl.find_transcript([lang])
                break
            except Exception:
                pass
                
        if not transcript:
            # Tenta inglês ou qualquer primeira disponível
            try:
                transcript = tl.find_transcript(['en'])
            except Exception:
                transcript = next(iter(tl))
                
        raw_snippets = transcript.fetch()
        idioma = transcript.language
        codigo_idioma = getattr(transcript, "language_code", "")
    except Exception as e:
        raise SemTranscricao(*explicar_falha(e)) from e

    # Normaliza snippets para dicionários limpos
    snippets = []
    for s in raw_snippets:
        txt = getattr(s, 'text', None) or (s.get('text') if isinstance(s, dict) else str(s))
        start = getattr(s, 'start', 0.0) if hasattr(s, 'start') else (s.get('start', 0.0) if isinstance(s, dict) else 0.0)
        dur = getattr(s, 'duration', 0.0) if hasattr(s, 'duration') else (s.get('duration', 0.0) if isinstance(s, dict) else 0.0)
        
        txt_limpo = " ".join(txt.split())
        if txt_limpo and txt_limpo != "[Música]":
            snippets.append({"texto": txt_limpo, "start": float(start), "dur": float(dur)})

    if not snippets:
        raise SemTranscricao("A legenda do vídeo só tem marcações como [Música], sem fala nenhuma para ler.", True)
    return transcricao_de_falas(video_id, snippets, idioma, codigo_idioma)


def transcricao_de_falas(video_id, snippets, idioma, codigo_idioma, palavras_ouvidas=None) -> dict:
    """
    As falas (~3 s cada, {"texto", "start", "dur"}) viram o dicionário que a análise usa. Serve à legenda do
    YouTube e à transcrição feita no computador (fala_local.py), que ainda manda o tempo medido de cada
    palavra (`palavras_ouvidas`) — com ele, a legenda queimada dos cortes nem precisa ouvir o áudio de novo.
    """
    # Agrupa em blocos contínuos de ~45 a 60 segundos
    blocos_agrupados = []
    bloco_atual = []
    tempo_inicio = snippets[0]['start']

    for i, item in enumerate(snippets):
        bloco_atual.append(item['texto'])
        duracao_atual = (item['start'] + item['dur']) - tempo_inicio

        if duracao_atual >= 50.0 or len(bloco_atual) >= 12 or i == len(snippets) - 1:
            texto_bloco = " ".join(bloco_atual)
            blocos_agrupados.append({
                "timestamp_segundos": tempo_inicio,
                "timestamp_formatado": segundos_para_tempo(tempo_inicio),
                "texto": texto_bloco
            })
            bloco_atual = []
            if i + 1 < len(snippets):
                tempo_inicio = snippets[i + 1]['start']

    duracao_total = snippets[-1]['start'] + snippets[-1]['dur']

    dados = {
        "video_id": video_id,
        "idioma": idioma,
        "codigo_idioma": codigo_idioma,
        "duracao_segundos": duracao_total,
        "duracao_formatada": segundos_para_tempo(duracao_total),
        "total_blocos": len(blocos_agrupados),
        "blocos": blocos_agrupados,
        # As falas soltas (~3s cada) ficam guardadas: os blocos de 50s servem para resumir, mas a legenda
        # queimada no vídeo precisa da marcação fina de cada frase.
        "falas": snippets
    }
    if palavras_ouvidas:
        dados["palavras_ouvidas"] = palavras_ouvidas
    return dados

if __name__ == "__main__":
    vid_id = "M7lc1UVf-VE"
    print(f"Testando extração do vídeo: {vid_id}...")
    dados = obter_transcricao_formatada(vid_id)
    print(f"Idioma: {dados['idioma']} | Duração Total: {dados['duracao_formatada']}")
    print(f"Total de Blocos de Minutagem: {dados['total_blocos']}")
    print(f"\nAmostra do Bloco 1 ({dados['blocos'][0]['timestamp_formatado']}):")
    print(dados['blocos'][0]['texto'][:160] + "...")
