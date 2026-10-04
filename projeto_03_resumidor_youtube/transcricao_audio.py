"""
Transcrição do áudio de um clipe pela IA, para vídeo que não veio do YouTube e não tem .srt.

O YouTube entrega a legenda pronta; um arquivo do computador ou um vídeo do TikTok, não. Aqui o áudio do
clipe (só o trecho escolhido, em mono e taxa baixa: um minuto dá ~360 KB) vai para o Gemini, que devolve a
fala em pedaços com início e fim. O resultado sai no mesmo formato da transcrição do YouTube e segue pela
mesma montagem de legenda (legendas.py).

Limite conhecido e não medido: o tempo de cada pedaço é o que o modelo diz ter ouvido. Não há como conferir
aqui sem uma chave; se a legenda sair adiantada ou atrasada, o próximo passo é um reconhecedor de fala local
com tempo por palavra (faster-whisper), que é preciso e gratuito, mas pesa ~500 MB de modelo.
"""
import subprocess

from pydantic import BaseModel, Field

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado


class TrechoFalado(BaseModel):
    inicio: float = Field(ge=0, description="Segundos desde o começo do áudio em que a fala começa")
    fim: float = Field(ge=0, description="Segundos desde o começo do áudio em que a fala termina")
    texto: str = Field(description="O que foi dito, no idioma falado")


class TranscricaoDoAudio(BaseModel):
    trechos: list[TrechoFalado]


def extrair_audio(clipe, ffmpeg: str) -> bytes:
    proc = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(clipe), "-vn", "-ac", "1", "-ar", "16000",
                           "-b:a", "48k", "-f", "mp3", "-"], capture_output=True)
    return proc.stdout if proc.returncode == 0 else b""


PROMPT = (
    "Transcreva a fala deste áudio, no idioma em que ela é dita (não traduza).\n"
    "Devolva a fala em trechos curtos, de uma frase ou de até uns 5 segundos, cada um com o início e o fim "
    "em segundos contados do começo do áudio, na ordem em que acontecem.\n\n"
    "DIRETRIZES DE QUALIDADE DE DIÁLOGOS E EXPRESSÕES:\n"
    "- Pontue com expressividade dramática (vírgulas, exclamações, pontos), pois o público assiste sem som no celular.\n"
    "- NOMES DE TÉCNICAS E TERMOS EM JAPONÊS (ex: Bankai, Getsuga Tensho, Rasengan, etc.): escreva o nome correto da habilidade em romaji e não traduza literalmente nem invente palavras parecidas em português.\n"
    "- Transcreva só a fala: música, ruído e silêncio ficam de fora.\n"
    "- Se não houver fala nenhuma, devolva a lista de trechos vazia."
)


def validar(trechos, duracao: float) -> list:
    """Na ordem, dentro do clipe, com fim depois do início. Trecho fora disso é descartado, não consertado."""
    falas = []
    for t in sorted(trechos, key=lambda t: t.inicio):
        texto = " ".join(t.texto.split())
        fim = min(float(t.fim), float(duracao))
        if texto and t.inicio < duracao and fim > t.inicio:
            falas.append({"texto": texto, "start": round(float(t.inicio), 3), "dur": round(fim - float(t.inicio), 3)})
    return falas


def transcrever(clipe, duracao: float, client, ffmpeg: str) -> dict:
    """Devolve {"falas", "degradado", "motivo_degradado"}. Sem IA não há transcrição: `falas` sai vazia."""
    if client is None:
        return {"falas": [], "degradado": True, "motivo_degradado": MOTIVO_SEM_CHAVE}
    audio = extrair_audio(clipe, ffmpeg)
    if not audio:
        return {"falas": [], "degradado": True, "motivo_degradado": "não consegui extrair o áudio do clipe"}
    from google.genai import types
    try:
        resposta = gerar_estruturado(client, [types.Part.from_bytes(data=audio, mime_type="audio/mp3"), PROMPT],
                                     TranscricaoDoAudio, temperatura=0.0)
    except RespostaInvalida:
        return {"falas": [], "degradado": True, "motivo_degradado": MOTIVO_FORMATO}
    except FalhaLLM as erro:
        return {"falas": [], "degradado": True, "motivo_degradado": motivo_falha(erro)}
    falas = validar(resposta.trechos, duracao)
    if resposta.trechos and not falas:
        return {"falas": [], "degradado": True,
                "motivo_degradado": f"{MOTIVO_FORMATO} (os tempos devolvidos caíram fora do clipe)"}
    return {"falas": falas, "degradado": False, "motivo_degradado": None}
