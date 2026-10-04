"""
De onde vem o vídeo quando ele não é um vídeo do YouTube analisado: um arquivo do computador, ou um link de
outra rede (TikTok, Instagram, X, Vimeo, Facebook...).

O link é lido pelo mesmo yt-dlp do fatiador (versão 2026.08.19, 1.751 extratores). Testado em 21/09/2026,
só lendo título e duração, com vídeos públicos que o próprio yt-dlp usa nos testes dele:
- abriram: Dailymotion, Reddit, clipes da Twitch e vídeo público do Facebook;
- pediram login: Vimeo e Instagram;
- TikTok: "seu IP está bloqueado para este post" nos 2 posts testados, desta conexão.
O yt-dlp consegue usar os cookies do navegador para os que pedem login, mas isso entrega a sessão da sua conta
a um programa — não está ligado aqui de propósito. O caminho para esses é baixar pelo app da rede e enviar
como arquivo. Download de verdade só foi testado com o YouTube; os sites mudam, e o que abre hoje pode
fechar amanhã.

Do link, só o trecho escolhido é baixado (o mesmo corte por faixa do fatiador). Do arquivo, o trecho é
recortado localmente e recodificado com folga de qualidade, como no corte do YouTube.
"""
import hashlib
import re
import subprocess
from pathlib import Path

import renderizador_generico as rg
from cortador_video import ALTURA_PADRAO, FalhaNoCorte, baixar_e_cortar_clipe

PASTA_LOCAL = Path(__file__).resolve().parent / "videos_locais"
EXTENSOES = ("mp4", "mov", "mkv", "webm", "m4v", "avi")


class FalhaNaFonte(RuntimeError):
    """Não deu para ler o arquivo ou o link; a mensagem diz o que fazer."""


def salvar_envio(nome: str, conteudo: bytes, pasta=PASTA_LOCAL) -> Path:
    """
    Grava o arquivo enviado pela tela. O nome leva um pedaço do hash do conteúdo: enviar o mesmo vídeo de novo
    não duplica nada, e dois vídeos com o mesmo nome não se sobrescrevem.
    """
    extensao = Path(nome).suffix.lower().lstrip(".")
    if extensao not in EXTENSOES:
        raise FalhaNaFonte(f"formato .{extensao or '?'} não suportado (use {', '.join(EXTENSOES)})")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    base = rg.nome_de_arquivo(Path(nome).stem)[:-4]
    destino = pasta / f"{base}_{hashlib.sha1(conteudo).hexdigest()[:10]}.{extensao}"
    if not destino.exists():
        destino.write_bytes(conteudo)
    return destino


class _Calado:
    """O yt-dlp imprime "ERROR: ..." no terminal mesmo em modo quieto; o erro já volta como exceção."""
    def debug(self, msg):
        pass

    warning = info = error = debug


def e_link(texto: str) -> bool:
    return bool(re.match(r"https?://\S+$", str(texto).strip()))


def informacoes_do_link(url: str, extrair=None) -> dict:
    """Título, duração e site, sem baixar nada. `extrair` troca o yt-dlp nos testes."""
    if not e_link(url):
        raise FalhaNaFonte("isso não parece um link (tem que começar com http:// ou https://)")
    if extrair is None:
        import yt_dlp

        def extrair(endereco):
            opcoes = {"quiet": True, "no_warnings": True, "skip_download": True, "logger": _Calado()}
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                return ydl.extract_info(endereco, download=False)
    try:
        info = extrair(url.strip())
    except Exception as erro:                                      # o yt-dlp levanta tipos variados
        texto = str(erro)
        if any(p in texto.lower() for p in ("login", "cookies", "sign in", "private")):
            raise FalhaNaFonte("esse site pediu login para mostrar o vídeo. Baixe o arquivo pelo próprio app "
                               "da rede e envie aqui como arquivo do computador.") from erro
        raise FalhaNaFonte(f"não consegui abrir o link: {texto[-200:]}") from erro
    if info.get("_type") == "playlist" or "entries" in info:
        raise FalhaNaFonte("o link é de uma lista ou perfil; cole o link de um vídeo só")
    duracao = float(info.get("duration") or 0)
    if duracao <= 0:
        raise FalhaNaFonte("o site não informou a duração do vídeo (transmissão ao vivo?)")
    return {"titulo": info.get("title") or "video", "duracao": duracao,
            "site": info.get("extractor_key") or info.get("extractor") or "site", "url": url.strip()}


def cortar_arquivo(origem, inicio: float, fim: float, saida, ffmpeg: str) -> Path:
    """Recorta o trecho do arquivo local, recodificando (o corte fica no ponto exato, não no quadro-chave)."""
    if fim <= inicio:
        raise FalhaNaFonte(f"intervalo inválido: {inicio}s a {fim}s")
    proc = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{fim - inicio:.3f}",
                           "-i", str(origem), "-map", "0:v:0", "-map", "0:a:0?",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(saida)],
                          capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0 or not Path(saida).exists():
        raise FalhaNaFonte(f"o ffmpeg não conseguiu recortar o arquivo: {proc.stderr.strip()[-300:]}")
    return Path(saida)


def clipe_da_fonte(fonte: dict, inicio: float, fim: float, ffmpeg: str, altura: int = ALTURA_PADRAO,
                   pasta=PASTA_LOCAL, baixar=baixar_e_cortar_clipe) -> Path:
    """
    O trecho [inicio, fim] como um .mp4 pronto para o compositor, guardado para não refazer: montar de novo
    depois de trocar só a cor não recorta nem baixa nada.

    `fonte` é {"tipo": "arquivo", "caminho": ...} ou {"tipo": "link", "url": ..., "titulo": ...}.
    """
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    if fonte["tipo"] == "arquivo":
        base = Path(fonte["caminho"]).stem
        saida = pasta / f"trecho_{base}_{inicio:.1f}_{fim:.1f}.mp4"
        return saida if saida.exists() else cortar_arquivo(fonte["caminho"], inicio, fim, saida, ffmpeg)
    chave = hashlib.sha1(fonte["url"].encode()).hexdigest()[:10]
    saida = pasta / f"link_{chave}_{inicio:.1f}_{fim:.1f}_{altura}p.mp4"
    if not saida.exists():
        try:
            baixar(fonte["url"], inicio, fim, saida, ffmpeg=ffmpeg, altura_max=altura)
        except FalhaNoCorte as erro:
            raise FalhaNaFonte(f"não consegui baixar o trecho: {erro}") from erro
    return saida
