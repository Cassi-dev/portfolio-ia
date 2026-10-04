import os
import re
import subprocess
import sys
from pathlib import Path

import yt_dlp

from core.degradacao import MOTIVO_FORMATO, MOTIVO_SEM_CHAVE, motivo_falha
from core.llm import FalhaLLM, RespostaInvalida, gerar_estruturado
from core.midia import localizar_ffmpeg
import legendas
from esquemas_video import SugestaoCortes
from transcricao_youtube import texto_para_prompt

MAX_CHARS_TRANSCRICAO = 300_000

# ==========================================================
# MÓDULO DE CORTES VIRAIS (REELS / TIKTOK / SHORTS)
# ==========================================================

QUANTOS_CORTES = 5
# O corte anda para cair numa fronteira de frase. No começo, recuar até 10 s traz contexto barato; passar
# disso arrasta assunto que a IA não escolheu. No fim não há limite fixo — vale ir até a frase fechar, porque
# terminar o raciocínio foi exatamente o que faltou em uso real ("cortou antes de falar do contexto"); quem
# segura é a duração máxima. Medido nesta transcrição: a mediana entre fins de frase é 6 s, o maior é 18,7 s.
FOLGA_INICIO = 10.0
TRUNCAR_NO_MAXIMO = 2.0      # encurtar o fim corta conteúdo: só se a fronteira estiver logo ali atrás
DURACAO_MAXIMA = 90.0        # teto do Reels e do TikTok


def cortes_heuristicos(blocos, quantos=QUANTOS_CORTES):
    """Posições espalhadas pelo vídeo: um palpite mecânico, não uma análise de conteúdo."""
    disponiveis = max(1, len(blocos) - 1)
    quantos = max(1, min(quantos, disponiveis))
    indices = sorted({round(i * (disponiveis - 1) / max(1, quantos - 1)) for i in range(quantos)})
    cortes = []
    for i, idx in enumerate(indices, 1):
        b = blocos[idx]
        ini = int(b["timestamp_segundos"])
        cortes.append({
            "titulo": f"Corte #{i}: {b['texto'][:40]}...",
            "inicio_segundos": ini,
            "fim_segundos": ini + 45,
            "motivo_viral": "Posição escolhida pela minutagem do vídeo (sem análise de conteúdo).",
        })
    return cortes


def fronteiras_de_frase(palavras) -> tuple:
    """(instantes em que uma frase começa, instantes em que uma frase termina)."""
    aberturas = [p["inicio"] for i, p in enumerate(palavras)
                 if i == 0 or legendas.fecha_frase(palavras[i - 1]["texto"])]
    fechamentos = [p["fim"] for p in palavras if legendas.fecha_frase(p["texto"])]
    return aberturas, fechamentos


def ajustar_ao_limite_da_frase(inicio: float, fim: float, palavras, duracao: float | None = None,
                               duracao_maxima: float = DURACAO_MAXIMA) -> tuple:
    """
    Puxa o começo para o início da frase e empurra o fim para o fim da frase.

    A IA escolhe o corte lendo a transcrição, mas acerta o segundo por aproximação — e o resultado entrava no
    meio de uma oração e saía antes de a pessoa terminar o raciocínio. Esta função não depende do modelo:
    vale também para os cortes mecânicos do modo degradado.
    """
    if not palavras:
        return inicio, fim
    aberturas, fechamentos = fronteiras_de_frase(palavras)

    # No começo, preferimos recuar: perder o início da frase é pior do que trazer alguns segundos a mais.
    antes = [t for t in aberturas if inicio - FOLGA_INICIO <= t <= inicio]
    depois = [t for t in aberturas if inicio < t <= inicio + FOLGA_INICIO]
    novo_inicio = max(antes) if antes else (min(depois) if depois else inicio)

    # No fim, avançamos até a frase fechar, com a duração máxima no lugar de um limite de tempo arbitrário;
    # recuar corta conteúdo, então é o último recurso e por pouco.
    adiante = [t for t in fechamentos if t >= fim and t - novo_inicio <= duracao_maxima]
    atras = [t for t in fechamentos if fim - TRUNCAR_NO_MAXIMO <= t < fim]
    novo_fim = min(adiante) if adiante else (max(atras) if atras else fim)

    if duracao is not None:
        novo_fim = min(novo_fim, duracao)
    if novo_fim - novo_inicio < 1:
        return inicio, fim
    return round(novo_inicio, 1), round(novo_fim, 1)


def _falas_com_tempo_fino(dados_transcricao) -> str:
    """
    A marcação de tempo que vai no prompt. Os blocos trazem uma a cada ~44 s, e a IA tinha que escolher o
    segundo do corte por aproximação dentro dessa janela — daí os cortes entrando e saindo no meio da frase.
    As falas soltas da transcrição trazem uma marcação a cada ~4 s.
    """
    falas = dados_transcricao.get("falas")
    if falas:
        return texto_para_prompt(
            falas, MAX_CHARS_TRANSCRICAO,
            lambda f: f"[{f['start']:.0f}s] {legendas.sem_marcadores(f['texto'])}")[0]
    return texto_para_prompt(
        dados_transcricao["blocos"], MAX_CHARS_TRANSCRICAO,
        lambda b: f"[{b['timestamp_segundos']:.0f}s - {b['timestamp_formatado']}] {b['texto']}")[0]


_GATILHOS_GANCHO = (
    "segredo", "erro", "nunca", "verdade", "como", "por que", "porque", "ninguem", "ninguém",
    "forte", "poder", "morte", "luta", "batalha", "impossivel", "impossível", "melhor", "pior",
    "chocante", "revelado", "momento", "épico", "epico", "absurdo", "proibido", "final",
)


def calcular_score_viral(corte: dict, palavras: list = (), duracao_video: float | None = None) -> dict:
    """
    Calcula um Score de Viralidade Híbrido (0 a 100) inspirado no OpusClip, avaliando:
    1. Janela ideal de retenção de Reels/Shorts (28s a 62s)
    2. Força do gancho magnético nos primeiros segundos / título
    3. Densidade e ritmo de fala (palavras por segundo sem pausas mortas)
    4. Fechamento limpo de raciocínio em fronteira de frase
    """
    ini = float(corte.get("inicio_segundos", 0))
    fim = float(corte.get("fim_segundos", ini + 45))
    dur = max(1.0, fim - ini)
    fatores = []
    pontos = 0

    # 1. Janela ideal de retenção (até 28 pts)
    if 28 <= dur <= 62:
        pontos += 28
        fatores.append("Duração ideal (30–60s)")
    elif 20 <= dur < 28 or 62 < dur <= 78:
        pontos += 20
        fatores.append("Boa janela de retenção")
    else:
        pontos += 12

    # 2. Força do gancho (até 26 pts)
    titulo = str(corte.get("titulo", ""))
    motivo = str(corte.get("motivo_viral", ""))
    abertura_txt = " ".join(
        p["texto"] for p in palavras if ini <= float(p.get("inicio", -1)) <= ini + 6.0
    )
    texto_gancho = f"{titulo} {abertura_txt}".lower()
    pts_gancho = 14
    if "?" in texto_gancho or "!" in texto_gancho:
        pts_gancho += 5
    if re.search(r"\b\d+\b", texto_gancho):
        pts_gancho += 3
    achados = sum(1 for g in _GATILHOS_GANCHO if g in texto_gancho)
    pts_gancho += min(8, achados * 4)
    pontos += min(26, pts_gancho)
    if pts_gancho >= 20:
        fatores.append("Gancho forte na abertura")

    # 3. Ritmo e densidade de fala (até 24 pts)
    palavras_trecho = [p for p in palavras if ini <= float(p.get("inicio", -1)) <= fim]
    if palavras_trecho:
        pps = len(palavras_trecho) / dur
        if 1.8 <= pps <= 3.8:
            pontos += 24
            fatores.append("Ritmo dinâmico")
        elif 1.1 <= pps < 1.8 or pps > 3.8:
            pontos += 18
        else:
            pontos += 12
    else:
        pontos += 18

    # 4. Fechamento limpo de frase e análise semântica (até 22 pts)
    if palavras_trecho and legendas.fecha_frase(palavras_trecho[-1]["texto"]):
        pontos += 22
        fatores.append("Fechamento de frase limpo")
    else:
        pontos += 15

    if "Posição escolhida pela minutagem" in motivo:
        pontos -= 12

    score = max(45, min(99, int(round(pontos))))
    if score >= 88:
        selo = "🔥 Altíssimo potencial"
    elif score >= 76:
        selo = "⚡ Forte retenção"
    else:
        selo = "📈 Potencial moderado"

    return {"score_viral": score, "selo_viral": selo, "fatores_virais": fatores}


def _arrumar_cortes(cortes, dados_transcricao):
    """Encaixa cada corte em fronteiras de frase e calcula o score de potencial viral."""
    palavras = legendas.palavras_com_tempo(dados_transcricao.get("falas"))
    duracao = dados_transcricao.get("duracao_segundos")
    for corte in cortes:
        inicio, fim = ajustar_ao_limite_da_frase(corte["inicio_segundos"], corte["fim_segundos"], palavras,
                                                 duracao=duracao)
        corte["inicio_segundos"], corte["fim_segundos"] = int(inicio), int(round(fim))
        corte.update(calcular_score_viral(corte, palavras, duracao))
    return cortes


def sugerir_cortes_virais(dados_transcricao, client=None, quantos=QUANTOS_CORTES):
    """
    Usa IA para analisar a transcrição inteira e identificar os trechos de maior impacto (30 a 60 segundos)
    com maior potencial de gancho para Reels/Shorts. Os tempos escolhidos são encaixados em fronteiras de
    frase antes de sair daqui.
    Devolve {"cortes": [...], "degradado": bool, "motivo_degradado": str | None}.
    """
    blocos = dados_transcricao["blocos"]
    duracao = dados_transcricao.get("duracao_segundos")
    motivo = MOTIVO_SEM_CHAVE

    if client:
        prompt = (
            "Você é um editor de vídeos virais especialista em YouTube Shorts, TikTok e Instagram Reels.\n"
            f"Analise as falas a seguir e selecione OS {quantos} MELHORES CORTES (momentos de 30 a 60 segundos) "
            "que tenham um gancho magnético, ensinamento forte ou momento impactante.\n\n"
            "REGRAS\n"
            "- Use os tempos em segundos indicados entre colchetes; o corte não pode passar do fim do vídeo.\n"
            "- O corte começa no INÍCIO de uma frase e termina no FIM de uma frase, com o raciocínio completo: "
            "quem assistir sozinho precisa entender sem ter visto o resto do vídeo.\n"
            "- Prefira terminar depois da conclusão da ideia, mesmo que passe um pouco dos 60 segundos, a cortar "
            "a pessoa no meio do argumento.\n"
            "- Os cortes não se sobrepõem nem saem todos do mesmo trecho do vídeo.\n\n"
            f"FALAS DO VÍDEO:\n{_falas_com_tempo_fino(dados_transcricao)}"
        )
        try:
            sugestao = gerar_estruturado(client, prompt, SugestaoCortes)
            cortes = [
                c.model_dump() for c in sugestao.cortes
                if duracao is None or c.fim_segundos <= duracao + 5
            ]
            if cortes:
                return {"cortes": _arrumar_cortes(cortes, dados_transcricao), "degradado": False,
                        "motivo_degradado": None}
            motivo = f"{MOTIVO_FORMATO} (os cortes passavam da duração do vídeo)"
        except RespostaInvalida:
            motivo = MOTIVO_FORMATO
        except FalhaLLM as e:
            motivo = motivo_falha(e)

    return {"cortes": _arrumar_cortes(cortes_heuristicos(blocos, quantos), dados_transcricao),
            "degradado": True, "motivo_degradado": motivo}

class FalhaNoCorte(RuntimeError):
    """Não deu para gerar o clipe; a mensagem diz o motivo em português."""


ALTURAS = (2160, 1440, 1080, 720, 480, 360)
ALTURA_PADRAO = 1440
ROTULOS_ALTURA = {2160: "A melhor disponível (até 4K, mais lento)", 1440: "Até 1440p (recomendado)"}
PASTA_CORTES = Path(__file__).resolve().parent / "cortes_gerados"

# Reconectar é o que salva um corte longo de uma queda momentânea no meio do trecho.
RECONEXAO = ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"]


def formato_para(altura_max=ALTURA_PADRAO):
    """
    Seletor de formato do yt-dlp para até `altura_max` pixels de altura.

    Vídeo e áudio separados vêm primeiro de propósito: no YouTube, os formatos que já trazem os dois juntos
    param em 360p. Preferimos streams https (o m3u8 não aceita bem a busca por faixa que fazemos aqui).

    Sem preferência de codec: o H.264 do YouTube para em 1080p, então pedi-lo primeiro jogaria fora o 1440p
    e o 4K, que só existem em VP9 e AV1. Como recodificamos o trecho de qualquer jeito, o codec de origem
    importa menos do que a resolução.
    """
    h = int(altura_max)
    return (f"bestvideo[height<={h}][protocol=https]+bestaudio[protocol=https]/"
            f"bestvideo[height<={h}]+bestaudio/"
            f"best[height<={h}]/best")


def _extrair_com_yt_dlp(url, formato):
    """
    Sem forçar player_client: essa é a diferença entre 1080p e 360p. O cliente `android` responde mesmo quando
    o web falha, mas só oferece o formato 18 (360p), então ele é a segunda tentativa, não a primeira.
    """
    erro_final = None
    for extra in ({}, {"extractor_args": {"youtube": {"player_client": ["android"]}}}):
        try:
            with yt_dlp.YoutubeDL({"format": formato, "quiet": True, "no_warnings": True, **extra}) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as erro:
            erro_final = erro
    raise erro_final


def _descrever(formatos):
    alturas = [f.get("height") for f in formatos if f.get("height")]
    ids = "+".join(str(f.get("format_id", "?")) for f in formatos)
    return f"{max(alturas)}p ({ids})" if alturas else ids


def fontes_do_video(url_video, extrair=None, altura_max=ALTURA_PADRAO):
    """
    Devolve (urls de mídia, descrição do formato): duas urls quando vídeo e áudio vêm separados (o caso normal
    acima de 360p), uma quando já vêm juntos. O vídeo sempre vem primeiro na lista.
    `extrair` é injetável para testar sem rede.
    """
    formato = formato_para(altura_max)
    try:
        info = extrair(url_video) if extrair else _extrair_com_yt_dlp(url_video, formato)
    except Exception as erro:
        raise FalhaNoCorte(f"não consegui ler o vídeo no YouTube: {str(erro)[:200]}") from erro

    pedidos = (info or {}).get("requested_formats")
    if pedidos:
        pedidos = sorted(pedidos, key=lambda f: f.get("vcodec", "none") in (None, "none"))   # vídeo antes do áudio
        return [f["url"] for f in pedidos], _descrever(pedidos)
    if (info or {}).get("url"):
        return [info["url"]], _descrever([info])
    raise FalhaNoCorte("o YouTube não devolveu nenhum stream para este vídeo (pode ser restrito ou privado)")


def baixar_e_cortar_clipe(url_video, inicio_seg, fim_seg, arquivo_saida, extrair=None, ffmpeg=None,
                          altura_max=ALTURA_PADRAO):
    """
    Gera um .mp4 só com o intervalo pedido, sem baixar o vídeo inteiro: o ffmpeg busca o trecho direto
    do stream por faixa HTTP.

    Por que não usamos o download parcial do próprio yt-dlp: ele verifica a existência do ffmpeg com
    `FFmpegFD.available()`, que monta um objeto sem parâmetros e por isso ignora o `ffmpeg_location` que
    passaríamos — o próprio código do yt-dlp tem um "Fixme" reconhecendo isso. Sem ffmpeg no PATH do sistema,
    a checagem dá falso e ele aborta, mesmo com o ffmpeg empacotado ali do lado.
    """
    duracao = fim_seg - inicio_seg
    if duracao <= 0:
        raise FalhaNoCorte(f"intervalo inválido: {inicio_seg}s a {fim_seg}s")
    try:
        executavel = ffmpeg or localizar_ffmpeg()
    except RuntimeError as erro:
        raise FalhaNoCorte(str(erro)) from erro

    for tentativa in (1, 2):
        urls, formato = fontes_do_video(url_video, extrair, altura_max)
        erro = _cortar_com_ffmpeg(executavel, urls, inicio_seg, duracao, arquivo_saida, formato)
        if erro is None:
            return arquivo_saida
        # O YouTube às vezes recusa uma url recém-emitida (403). Quase sempre outra extração resolve: as urls
        # são assinadas e ligadas ao cliente que as gerou, e a segunda vem com assinatura nova.
        if tentativa == 2 or "403" not in erro:
            raise FalhaNoCorte(erro)
    raise FalhaNoCorte(erro)


def _cortar_com_ffmpeg(executavel, urls, inicio_seg, duracao, arquivo_saida, formato):
    """Roda o corte e devolve None se deu certo, ou a mensagem de erro em português."""
    comando = [executavel, "-y", "-loglevel", "error"]
    for url in urls:
        comando += [*RECONEXAO, "-ss", str(inicio_seg), "-t", str(duracao), "-i", url]   # -ss antes do -i: busca rápida
    if len(urls) > 1:
        comando += ["-map", "0:v:0", "-map", "1:a:0"]
    # Este arquivo ainda vai ser recodificado pelo montador, então ele é gravado com folga de qualidade:
    # crf 16 aqui e 18 na peça final deixam as duas gerações praticamente sem perda visível.
    comando += ["-c:v", "libx264", "-preset", "medium", "-crf", "16",        # recodifica: corte no ponto exato
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(arquivo_saida)]

    try:
        processo = subprocess.run(comando, capture_output=True, text=True, errors="ignore")
    except OSError as erro:
        raise FalhaNoCorte(f"não consegui executar o ffmpeg ({erro})") from erro
    if processo.returncode != 0:
        return f"o ffmpeg falhou ao cortar (formato {formato}): {processo.stderr.strip()[-300:]}"
    if not os.path.exists(arquivo_saida) or os.path.getsize(arquivo_saida) == 0:
        return "o ffmpeg terminou sem erro, mas não gerou arquivo. O trecho existe dentro do vídeo?"
    return None
