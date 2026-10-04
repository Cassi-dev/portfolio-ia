"""
Estúdio de áudio para edições dinâmicas: trilha sonora com Auto-Ducking, efeitos sonoros (SFX) sincronizados
nos golpes/transições e corte automático de silêncios (jump-cut de respiração).

Decisões de projeto:
- Zero dependência de arquivos externos obrigatórios: os efeitos sonoros (`bass_drop.wav`, `whoosh.wav`,
  `glitch.wav`) e as trilhas-base de clima (`luta`, `aura`, `emocao`) são sintetizados matematicamente com
  NumPy na primeira execução e guardados em `sons_estudio/`. O usuário também pode fornecer qualquer `.mp3`
  ou `.wav` próprio.
- Auto-Ducking por envelope de tempo: onde há fala (intervalos da legenda ou voz ativa), a trilha sonora cai
  suavemente para ~30% do volume escolhido (`volume_trilha * 0.30`), voltando ao volume cheio nas pausas e
  nos golpes de ação.
- A mixagem final usa `-c:v copy` no ffmpeg: o vídeo H.264 já renderizado não é recodificado, levando menos
  de 0,2 s para mixar trilha e múltiplos efeitos sonoros.
"""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import wave

import numpy as np

import momentos as mo

DIRETORIO = Path(__file__).resolve().parent
PASTA_SONS = DIRETORIO / "sons_estudio"
TAXA_AMOSTRAGEM = 44100

TRILHAS = {
    "nenhuma": ("Sem trilha de fundo", ""),
    "luta": ("Phonk / Batalha (ritmo tenso e grave)", "trilha_luta.wav"),
    "aura": ("Dark Synth / Aura (grave atmosférico)", "trilha_aura.wav"),
    "emocao": ("Ambient / Emoção (acordes suaves)", "trilha_emocao.wav"),
}


@dataclass(frozen=True)
class ConfigAudio:
    trilha: str = "nenhuma"             # chave de TRILHAS ou caminho para arquivo .mp3/.wav
    volume_trilha: float = 0.28         # volume base da música quando não há fala (0.0 a 1.0)
    auto_ducking: bool = True           # reduz a música automaticamente durante as falas
    sfx_impacto: bool = False           # injeta bass_drop, whoosh e glitch nos golpes e no card
    cortar_silencios: bool = False      # remove pausas mortas (> 0,45 s abaixo de -32 dBFS)
    limiar_silencio_db: float = -32.0
    min_silencio: float = 0.45

    @property
    def usa_mixagem(self) -> bool:
        return (bool(self.trilha) and self.trilha != "nenhuma") or self.sfx_impacto


SEM_AUDIO_EXTRA = ConfigAudio()


# ==============================================================================
# SÍNTESE DOS EFEITOS SONOROS E TRILHAS NATIVAS (NumPy -> WAV 16-bit estéreo)
# ==============================================================================
def _gravar_wav(caminho: Path, sinal: np.ndarray, taxa: int = TAXA_AMOSTRAGEM) -> Path:
    """Grava um array float [-1, 1] como WAV estéreo de 16 bits."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    sinal = np.clip(sinal, -1.0, 1.0)
    if sinal.ndim == 1:
        sinal = np.column_stack((sinal, sinal))
    pcm = (sinal * 32767.0).astype(np.int16)
    with wave.open(str(caminho), "wb") as arq:
        arq.setnchannels(2)
        arq.setsampwidth(2)
        arq.setframerate(taxa)
        arq.writeframes(pcm.tobytes())
    return caminho


def _sintetizar_bass_drop() -> np.ndarray:
    """Impacto sub-grave de anime: queda exponencial de 145 Hz para 36 Hz em 0,45 s com ataque percussivo."""
    dur = 0.45
    t = np.linspace(0, dur, int(TAXA_AMOSTRAGEM * dur), endpoint=False)
    freq = 36.0 + 109.0 * np.exp(-t * 9.5)
    fase = 2.0 * np.pi * np.cumsum(freq) / TAXA_AMOSTRAGEM
    env = np.exp(-t * 5.2)
    ataque = np.sin(2.0 * np.pi * 240.0 * t) * np.exp(-t * 38.0) * 0.45
    onda = np.tanh((np.sin(fase) * env + ataque) * 1.6) * 0.88
    return onda


def _sintetizar_whoosh() -> np.ndarray:
    """Sopro rápido de transição / zoom punch / entrada de card (0,32 s)."""
    dur = 0.32
    n = int(TAXA_AMOSTRAGEM * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    rng = np.random.default_rng(42)
    ruido = rng.normal(0, 1, n)
    # média móvel curta para amaciar o ruído branco em sopro de ar
    janela = np.hanning(36)
    janela /= janela.sum()
    ar = np.convolve(ruido, janela, mode="same")
    varredura = np.sin(2.0 * np.pi * (160.0 + 520.0 * np.sin(np.pi * t / dur)) * t) * 0.45
    env = np.sin(np.pi * t / dur) ** 1.8
    canal_e = (ar * 0.7 + varredura) * env * 0.75
    canal_d = (np.roll(ar, 18) * 0.7 + varredura) * env * 0.75
    return np.column_stack((canal_e, canal_d))


def _sintetizar_glitch() -> np.ndarray:
    """Falha digital curta (0,22 s) com pulsos quadrados picotados para transições e RGB shift."""
    dur = 0.22
    t = np.linspace(0, dur, int(TAXA_AMOSTRAGEM * dur), endpoint=False)
    portao = (np.sin(2.0 * np.pi * 28.0 * t) > -0.1).astype(float)
    onda = (np.sign(np.sin(2.0 * np.pi * 660.0 * t)) * 0.4
            + np.sign(np.sin(2.0 * np.pi * 1320.0 * t)) * 0.25)
    env = np.exp(-t * 6.0) * portao
    return onda * env * 0.65


def _sintetizar_trilha_luta() -> np.ndarray:
    """Loop de 4,8 s (125 BPM) estilo Phonk/Batalha: baixo distorcido pulsante + cowbell metálico."""
    dur = 4.8
    t = np.linspace(0, dur, int(TAXA_AMOSTRAGEM * dur), endpoint=False)
    batida = 0.48  # 125 BPM
    pos = np.mod(t, batida)
    # Sub-baixo em Ré menor (D1 = 36.7 Hz, F1 = 43.65 Hz)
    nota_baixo = np.where(np.mod(t, batida * 4) < batida * 3, 36.71, 43.65)
    baixo = np.tanh(np.sin(2.0 * np.pi * nota_baixo * t) * 2.2) * np.exp(-pos * 4.5) * 0.55
    # Pulso sintético de oitava (lead escuro)
    pos_meio = np.mod(t, batida / 2.0)
    notas_lead = np.select(
        [pos < batida * 0.25, pos < batida * 0.5, pos < batida * 0.75],
        [146.83, 174.61, 220.0],
        default=164.81,
    )
    lead = (np.sin(2.0 * np.pi * notas_lead * t) + 0.5 * np.sin(2.0 * np.pi * notas_lead * 1.5 * t))
    lead = np.tanh(lead * 1.4) * np.exp(-pos_meio * 11.0) * 0.22
    return baixo + lead


def _sintetizar_trilha_aura() -> np.ndarray:
    """Loop atmosférico sombrio de 6,0 s: drone grave com batimento lento e harmônicos de quinta."""
    dur = 6.0
    t = np.linspace(0, dur, int(TAXA_AMOSTRAGEM * dur), endpoint=False)
    env_ciclo = 0.65 + 0.35 * np.sin(2.0 * np.pi * t / dur)
    drone = (np.sin(2.0 * np.pi * 41.20 * t) * 0.50
             + np.sin(2.0 * np.pi * 61.74 * t) * 0.28
             + np.sin(2.0 * np.pi * 82.41 * t + np.sin(2.0 * np.pi * 0.5 * t)) * 0.18)
    pulso = np.sin(2.0 * np.pi * 41.20 * t) * np.exp(-np.mod(t, 1.5) * 3.5) * 0.30
    return np.tanh((drone * env_ciclo + pulso) * 1.2) * 0.65


def _sintetizar_trilha_emocao() -> np.ndarray:
    """Loop melancólico suave de 6,0 s: pad quente em Lá menor (A2, C3, E3, G3)."""
    dur = 6.0
    t = np.linspace(0, dur, int(TAXA_AMOSTRAGEM * dur), endpoint=False)
    acorde = (np.sin(2.0 * np.pi * 110.00 * t) * 0.35
              + np.sin(2.0 * np.pi * 130.81 * t) * 0.28
              + np.sin(2.0 * np.pi * 164.81 * t) * 0.24
              + np.sin(2.0 * np.pi * 196.00 * t) * 0.16)
    respiracao = 0.75 + 0.25 * np.sin(2.0 * np.pi * t / 3.0)
    return acorde * respiracao * 0.55


def garantir_banco_de_sons(pasta: Path = PASTA_SONS) -> dict[str, Path]:
    """Cria os arquivos WAV de SFX e trilhas na pasta se ainda não existirem e devolve seus caminhos."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    geradores = {
        "bass_drop": ("bass_drop.wav", _sintetizar_bass_drop),
        "whoosh": ("whoosh.wav", _sintetizar_whoosh),
        "glitch": ("glitch.wav", _sintetizar_glitch),
        "luta": ("trilha_luta.wav", _sintetizar_trilha_luta),
        "aura": ("trilha_aura.wav", _sintetizar_trilha_aura),
        "emocao": ("trilha_emocao.wav", _sintetizar_trilha_emocao),
    }
    caminhos = {}
    for chave, (nome_arq, fn) in geradores.items():
        alvo = pasta / nome_arq
        if not alvo.exists() or alvo.stat().st_size < 100:
            _gravar_wav(alvo, fn())
        caminhos[chave] = alvo
    return caminhos


def resolver_caminho_trilha(trilha: str, pasta: Path = PASTA_SONS) -> Path | None:
    """Devolve o Path da trilha escolhida (nativa ou personalizada) ou None se desligada."""
    if not trilha or trilha == "nenhuma":
        return None
    sons = garantir_banco_de_sons(pasta)
    if trilha in sons:
        return sons[trilha]
    caminho = Path(trilha)
    return caminho if caminho.exists() else None


# ==============================================================================
# AUTO-DUCKING E MIXAGEM DE EFEITOS SONOROS (funções puras de filtro + execução)
# ==============================================================================
FATOR_DUCKING = 0.30        # durante a fala, a trilha cai para 30% do volume configurado
MARGEM_FALA = 0.12          # antecedência/cauda ao redor de cada bloco de legenda


def janelas_de_fala(legendas, duracao: float) -> list[tuple[float, float]]:
    """Funde blocos de legenda próximos em intervalos contínuos onde há voz ativa."""
    if not legendas:
        return []
    brutas = []
    for b in sorted(legendas, key=lambda x: float(x["inicio"])):
        ini = max(0.0, float(b["inicio"]) - MARGEM_FALA)
        fim = min(float(duracao), float(b["fim"]) + MARGEM_FALA)
        if fim > ini:
            brutas.append((round(ini, 3), round(fim, 3)))
    if not brutas:
        return []
    fundidas = [brutas[0]]
    for ini, fim in brutas[1:]:
        ant_ini, ant_fim = fundidas[-1]
        if ini <= ant_fim + 0.25:
            fundidas[-1] = (ant_ini, max(ant_fim, fim))
        else:
            fundidas.append((ini, fim))
    return fundidas


def expressao_ducking(legendas, duracao: float, volume_cheio: float = 0.28,
                      auto_ducking: bool = True) -> str:
    """
    Filtro `volume` do ffmpeg para a trilha sonora: mantém `volume_cheio` nas pausas/ação e reduz para
    `volume_cheio * FATOR_DUCKING` quando alguém está falando (`between(t,...)`).
    """
    vol_cheio = max(0.0, min(1.0, float(volume_cheio)))
    janelas = janelas_de_fala(legendas, duracao) if auto_ducking else []
    if not janelas:
        return f"volume={vol_cheio:.3f}"
    vol_baixo = round(vol_cheio * FATOR_DUCKING, 3)
    quando = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in janelas)
    return f"volume='if({quando},{vol_baixo:.3f},{vol_cheio:.3f})':eval=frame"


def planejar_eventos_sfx(golpes, arte, duracao: float, inicio_card_ml: float | None = None) -> list[dict]:
    """
    Lista de efeitos sonoros que devem tocar no vídeo, com `{"tipo", "t", "volume"}`:
    - `bass_drop` em cada golpe escolhido
    - `whoosh` quando há zoom no golpe ou na subida do card flutuante do Mercado Livre
    - `glitch` quando a direção de arte tem `glitch` ou `separacao_rgb`
    """
    eventos = []
    for g in golpes or []:
        t = round(max(0.0, float(g["t"])), 3)
        if t >= duracao:
            continue
        eventos.append({"tipo": "bass_drop", "t": t, "volume": 0.65})
        if getattr(arte, "zoom_no_golpe", 1.0) > 1.0 or getattr(arte, "tremida", 0) > 0:
            eventos.append({"tipo": "whoosh", "t": max(0.0, round(t - 0.04, 3)), "volume": 0.50})
        if getattr(arte, "glitch", False) or getattr(arte, "separacao_rgb", False):
            eventos.append({"tipo": "glitch", "t": t, "volume": 0.48})
    if inicio_card_ml is not None and 0.0 <= inicio_card_ml < duracao:
        eventos.append({"tipo": "whoosh", "t": round(float(inicio_card_ml), 3), "volume": 0.60})
    return eventos


def filtro_mixagem_audio(tem_trilha: bool, eventos_sfx: list[dict], legendas, duracao: float,
                         volume_trilha: float = 0.28, auto_ducking: bool = True) -> str:
    """
    Monta o `-filter_complex` de áudio:
    - Entrada `0:a` é o áudio original do clipe.
    - Se `tem_trilha`, a entrada `1:a` é a música em loop, aparada em `duracao` e com Auto-Ducking.
    - As entradas seguintes são os arquivos WAV de cada evento em `eventos_sfx`, posicionados com `adelay`.
    - Todas as faixas são somadas com `amix=normalize=0` para o `0:a` nunca perder volume quando um SFX entra.
    """
    partes = [f"[0:a]aresample={TAXA_AMOSTRAGEM},aformat=sample_fmts=fltp:channel_layouts=stereo[a_voz]"]
    etiquetas = ["[a_voz]"]
    idx_entrada = 1

    if tem_trilha:
        vol = expressao_ducking(legendas, duracao, volume_trilha, auto_ducking)
        fade_out = max(0.0, float(duracao) - 0.8)
        partes.append(
            f"[{idx_entrada}:a]aresample={TAXA_AMOSTRAGEM},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{duracao:.3f},asetpts=PTS-STARTPTS,{vol},"
            f"afade=t=out:st={fade_out:.3f}:d=0.800[a_trilha]"
        )
        etiquetas.append("[a_trilha]")
        idx_entrada += 1

    for k, ev in enumerate(eventos_sfx):
        atraso_ms = max(0, int(round(float(ev["t"]) * 1000)))
        vol_sfx = float(ev.get("volume", 0.55))
        partes.append(
            f"[{idx_entrada}:a]aresample={TAXA_AMOSTRAGEM},aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={vol_sfx:.3f},adelay={atraso_ms}|{atraso_ms}[sfx{k}]"
        )
        etiquetas.append(f"[sfx{k}]")
        idx_entrada += 1

    if len(etiquetas) == 1:
        partes.append("[a_voz]anull[a_mix]")
    else:
        partes.append(
            f"{''.join(etiquetas)}amix=inputs={len(etiquetas)}:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.95[a_mix]"
        )
    return ";".join(partes)


def aplicar_audio_estudio(video_entrada, video_saida, ffmpeg: str, config: ConfigAudio, *,
                          duracao: float, legendas=(), golpes=(), arte=None,
                          inicio_card_ml: float | None = None, pasta_sons: Path = PASTA_SONS) -> Path:
    """
    Mixa trilha sonora (com Auto-Ducking) e efeitos sonoros de impacto sobre `video_entrada` sem recodificar
    o vídeo (`-c:v copy`). Se nenhuma opção de áudio estiver ativa, apenas copia/mantém o arquivo.
    """
    video_entrada, video_saida = Path(video_entrada), Path(video_saida)
    caminho_trilha = resolver_caminho_trilha(config.trilha, pasta_sons)
    eventos = planejar_eventos_sfx(golpes, arte, duracao, inicio_card_ml) if config.sfx_impacto else []
    if caminho_trilha is None and not eventos:
        if video_entrada.resolve() != video_saida.resolve():
            video_saida.write_bytes(video_entrada.read_bytes())
        return video_saida

    sons = garantir_banco_de_sons(pasta_sons)
    filtro = filtro_mixagem_audio(
        tem_trilha=caminho_trilha is not None,
        eventos_sfx=eventos,
        legendas=legendas,
        duracao=duracao,
        volume_trilha=config.volume_trilha,
        auto_ducking=config.auto_ducking,
    )
    comando = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video_entrada)]
    if caminho_trilha is not None:
        comando += ["-stream_loop", "-1", "-i", str(caminho_trilha)]
    for ev in eventos:
        comando += ["-i", str(sons[ev["tipo"]])]

    mesmo_arquivo = video_entrada.resolve() == video_saida.resolve()
    alvo_temp = video_saida.with_name(video_saida.stem + "_mix_tmp.mp4") if mesmo_arquivo else video_saida
    comando += [
        "-filter_complex", filtro,
        "-map", "0:v:0", "-map", "[a_mix]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-ar", str(TAXA_AMOSTRAGEM),
        "-t", f"{duracao:.3f}", "-movflags", "+faststart", str(alvo_temp),
    ]
    proc = subprocess.run(comando, capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise RuntimeError(f"o ffmpeg falhou ao mixar o áudio do estúdio: {proc.stderr.strip()[-300:]}")
    if mesmo_arquivo:
        alvo_temp.replace(video_saida)
    return video_saida


# ==============================================================================
# CORTE AUTOMÁTICO DE SILÊNCIOS (JUMP-CUT DE RESPIRAÇÃO)
# ==============================================================================
MARGEM_CORTE = 0.08         # folga preservada antes e depois de cada trecho falado


def detectar_intervalos_ativos(db: np.ndarray, duracao: float, limiar_db: float = -32.0,
                               min_silencio: float = 0.45, passo: float = mo.PASSO) -> list[tuple[float, float]]:
    """
    A partir da curva de volume em dBFS (passo de 20 ms), devolve os intervalos `[inicio, fim]` com som ativo,
    eliminando apenas os silêncios contínuos maiores ou iguais a `min_silencio`. Se o clipe inteiro for
    silencioso ou nenhum silêncio longo for achado, devolve `[(0.0, duracao)]`.
    """
    duracao = float(duracao)
    if db.size == 0 or duracao <= min_silencio:
        return [(0.0, round(duracao, 3))]

    silencioso = db < limiar_db
    # Acha corridas de True em `silencioso`
    mudancas = np.diff(silencioso.astype(int), prepend=0, append=0)
    inicios_sil = np.where(mudancas == 1)[0]
    fins_sil = np.where(mudancas == -1)[0]

    silencios_longos = []
    for i_ini, i_fim in zip(inicios_sil, fins_sil):
        t_ini = i_ini * passo
        t_fim = min(duracao, i_fim * passo)
        if t_fim - t_ini >= min_silencio:
            # Encolhe o silêncio pelas margens para não engolir o final/início das palavras
            corte_ini = min(duracao, t_ini + MARGEM_CORTE)
            corte_fim = max(0.0, t_fim - MARGEM_CORTE)
            if corte_fim - corte_ini >= 0.15:
                silencios_longos.append((round(corte_ini, 3), round(corte_fim, 3)))

    if not silencios_longos:
        return [(0.0, round(duracao, 3))]

    ativos = []
    cursor = 0.0
    for s_ini, s_fim in silencios_longos:
        if s_ini - cursor >= 0.15:
            ativos.append((round(cursor, 3), round(s_ini, 3)))
        cursor = s_fim
    if duracao - cursor >= 0.15:
        ativos.append((round(cursor, 3), round(duracao, 3)))

    return ativos or [(0.0, round(duracao, 3))]


def remapear_tempo_cortes(t: float, intervalos: list[tuple[float, float]]) -> float:
    """Converte um instante `t` do clipe original para o instante correspondente após remover os silêncios."""
    if not intervalos:
        return t
    acumulado = 0.0
    for ini, fim in intervalos:
        if t <= ini:
            return round(acumulado, 3)
        if t <= fim:
            return round(acumulado + (t - ini), 3)
        acumulado += fim - ini
    return round(acumulado, 3)


def remapear_legendas_cortes(legendas, intervalos: list[tuple[float, float]]) -> list[dict]:
    """Ajusta os tempos das legendas e palavras para a nova linha do tempo sem silêncios."""
    if not intervalos or (len(intervalos) == 1 and intervalos[0][0] == 0.0):
        return list(legendas)
    saida = []
    for bloco in legendas:
        ini = remapear_tempo_cortes(float(bloco["inicio"]), intervalos)
        fim = remapear_tempo_cortes(float(bloco["fim"]), intervalos)
        if fim - ini < 0.08:
            continue
        novo = {**bloco, "inicio": ini, "fim": fim}
        if bloco.get("palavras"):
            palavras = []
            for p in bloco["palavras"]:
                p_ini = remapear_tempo_cortes(float(p["inicio"]), intervalos)
                p_fim = remapear_tempo_cortes(float(p["fim"]), intervalos)
                if p_fim > p_ini:
                    palavras.append({**p, "inicio": p_ini, "fim": p_fim})
            novo["palavras"] = palavras
        saida.append(novo)
    return saida


def cortar_silencios_clipe(clipe_entrada, clipe_saida, ffmpeg: str, duracao: float,
                           tem_audio: bool = True, limiar_db: float = -32.0,
                           min_silencio: float = 0.45) -> tuple[Path, list[tuple[float, float]], float]:
    """
    Analisa o volume do clipe, remove os silêncios longos e grava o vídeo enxuto em `clipe_saida`.
    Devolve `(caminho_usado, intervalos_ativos, nova_duracao)`. Se não houver silêncio para cortar,
    devolve o próprio `clipe_entrada` sem recodificar.
    """
    clipe_entrada, clipe_saida = Path(clipe_entrada), Path(clipe_saida)
    if not tem_audio:
        return clipe_entrada, [(0.0, round(float(duracao), 3))], float(duracao)

    db = mo._volume_por_janela(clipe_entrada, ffmpeg)
    intervalos = detectar_intervalos_ativos(db, duracao, limiar_db=limiar_db, min_silencio=min_silencio)
    if len(intervalos) == 1 and intervalos[0][0] == 0.0 and abs(intervalos[0][1] - duracao) < 0.1:
        return clipe_entrada, intervalos, float(duracao)

    n = len(intervalos)
    partes = [f"[0:v]split={n}" + "".join(f"[vc{i}]" for i in range(n))]
    for i, (ini, fim) in enumerate(intervalos):
        partes.append(f"[vc{i}]trim={ini:.3f}:{fim:.3f},setpts=PTS-STARTPTS[vs{i}]")
    partes.append(f"[0:a]asplit={n}" + "".join(f"[ac{i}]" for i in range(n)))
    for i, (ini, fim) in enumerate(intervalos):
        partes.append(f"[ac{i}]atrim={ini:.3f}:{fim:.3f},asetpts=PTS-STARTPTS[as{i}]")
    entradas = "".join(f"[vs{i}][as{i}]" for i in range(n))
    partes.append(f"{entradas}concat=n={n}:v=1:a=1[v_cut][a_cut]")

    comando = [
        ffmpeg, "-y", "-loglevel", "error", "-i", str(clipe_entrada),
        "-filter_complex", ";".join(partes),
        "-map", "[v_cut]", "-map", "[a_cut]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(clipe_saida),
    ]
    proc = subprocess.run(comando, capture_output=True, text=True, errors="ignore")
    if proc.returncode != 0:
        raise RuntimeError(f"o ffmpeg falhou ao cortar silêncios: {proc.stderr.strip()[-300:]}")
    nova_duracao = round(sum(fim - ini for ini, fim in intervalos), 3)
    return clipe_saida, intervalos, nova_duracao
