"""
Onde estão os golpes e os cortes de cena de um clipe — para os efeitos caírem no lugar certo, e não a cada
N segundos.

Editor de vídeo curto põe flash, tremida e quadro de impacto no *golpe*: no som que explode e no corte de
cena que vem junto. Aqui isso é medido, sem IA e sem gastar chamada:

- **golpe** = subida brusca de volume (≥ 8 dB em 100 ms) que chega a volume alto de verdade (≥ -20 dBFS). O
  limite absoluto importa: a primeira versão comparava com a mediana do próprio clipe, e a despedida do
  Rengoku — cena triste, quase sussurrada — deu 50 "golpes" por minuto: cada começo de fala contava. Com o
  limite absoluto, deu zero. Funciona porque o YouTube normaliza o volume dos vídeos (~-14 LUFS).
- **corte de cena** = diferença média grande entre dois quadros seguidos (12 por segundo, em miniatura).
- golpe que coincide com corte de cena ganha peso: no anime, a pancada e a troca de plano vêm juntas.

Medido em 14 clipes reais de 5 vídeos (4 lutas e um monólogo): as lutas tiveram 36 a 59 cortes por minuto,
exceto um trecho mais lento (13); o monólogo do Aizen, 16 a 30; a despedida do Rengoku, 24 — e volume bem
mais baixo que o resto (95% do tempo abaixo de -29 dBFS, contra -14 a -19 nos outros). Daí a sugestão de
receita: é um palpite com base em 14 clipes, e a tela diz que é palpite.
"""
import subprocess

import numpy as np

TAXA, JANELA, PASSO = 16000, 0.05, 0.025       # áudio em janelas de 50 ms, andando de 25 em 25
SUBIDA_MINIMA = 8.0                             # dB em 100 ms
VOLUME_MINIMO = -20.0                           # dBFS depois da subida
ESPACO_MINIMO = 0.4                             # dois golpes mais perto que isso são o mesmo
PERTO_DO_CORTE = 0.15                           # golpe a até isso de um corte de cena ganha peso
FPS_CORTES, CORTE_MINIMO = 12, 25.0             # diferença média (0-255) que conta como troca de plano


def energia(clipe, ffmpeg: str) -> np.ndarray:
    """Volume em dBFS, uma medida a cada 25 ms."""
    bruto = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(clipe), "-vn", "-ac", "1", "-ar", str(TAXA),
                            "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(bruto, np.int16).astype(np.float32) / 32768
    return volume_por_janela(x)


_volume_por_janela = energia


def volume_por_janela(amostras: np.ndarray, taxa: int = TAXA) -> np.ndarray:
    janela, passo = int(JANELA * taxa), int(PASSO * taxa)
    if len(amostras) < janela:
        return np.zeros(0, np.float32)
    quadros = np.lib.stride_tricks.sliding_window_view(amostras, janela)[::passo]
    return 20 * np.log10(np.sqrt((quadros ** 2).mean(axis=1)) + 1e-5)


def _ler_quadros_miniatura(clipe, ffmpeg: str) -> np.ndarray:
    """Quadros em escala de cinza 96x54 a 12 fps para medir cortes de cena e centro de ação."""
    bruto = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(clipe), "-vf",
                            f"fps={FPS_CORTES},scale=96:54,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True).stdout
    n = len(bruto) // (96 * 54)
    if n < 1:
        return np.zeros((0, 54, 96), np.float32)
    return np.frombuffer(bruto[:n * 96 * 54], np.uint8).reshape(n, 54, 96).astype(np.float32)


def cortes_de_cena(clipe, ffmpeg: str) -> tuple:
    """(instantes das trocas de plano, duração lida)."""
    quadros = _ler_quadros_miniatura(clipe, ffmpeg)
    n = len(quadros)
    if n < 2:
        return [], n / FPS_CORTES
    return trocas_de_plano(np.abs(np.diff(quadros, axis=0)).mean(axis=(1, 2))), n / FPS_CORTES


def centros_de_acao(quadros: np.ndarray, cortes: list, duracao: float, fps: int = FPS_CORTES) -> list[dict]:
    """
    Auto-Reframe por tomada (estilo OpusClip / Framedrop): para cada plano entre dois cortes de cena, mede em
    qual faixa horizontal (`x_rel` de 0.0 a 1.0, onde 0.5 é o centro) está o maior movimento e detalhe visual.
    A posição fica travada durante a tomada inteira para a câmera vertical nunca deslizar nem tremer.
    """
    duracao = float(max(0.1, duracao))
    limites = [0.0] + [float(c) for c in cortes if 0.05 < float(c) < duracao - 0.05] + [duracao]
    n, _, larg = quadros.shape if quadros.ndim == 3 else (0, 54, 96)
    xs = np.linspace(0.0, 1.0, larg)
    tomadas = []
    for ini, fim in zip(limites[:-1], limites[1:]):
        if fim - ini < 0.04:
            continue
        if n < 2:
            tomadas.append({"inicio": round(ini, 3), "fim": round(fim, 3), "x_rel": 0.5})
            continue
        i0 = max(0, min(n - 1, int(round(ini * fps))))
        i1 = max(i0 + 1, min(n, int(round(fim * fps))))
        fatia = quadros[i0:i1]
        mov = np.abs(np.diff(fatia, axis=0)).mean(axis=(0, 1)) if len(fatia) >= 2 else np.zeros(larg, np.float32)
        quadro_medio = fatia.mean(axis=0)
        borda = np.pad(np.abs(np.diff(quadro_medio, axis=1)).mean(axis=0), (0, 1), mode="edge")
        atividade = mov * 0.75 + borda * 0.25
        if float(atividade.max() - atividade.min()) < 1.0:
            x_rel = 0.5
        else:
            util = np.clip(atividade - np.percentile(atividade, 55), 0.0, None)
            soma = float(util.sum())
            x_rel = float(np.sum(xs * util) / soma) if soma > 1e-6 else 0.5
            x_rel = max(0.12, min(0.88, x_rel))
        tomadas.append({"inicio": round(ini, 3), "fim": round(fim, 3), "x_rel": round(x_rel, 3)})
    return tomadas or [{"inicio": 0.0, "fim": round(duracao, 3), "x_rel": 0.5}]


def trocas_de_plano(diferencas, fps: int = FPS_CORTES) -> list:
    d = np.asarray(diferencas, dtype=np.float32)
    if not len(d):
        return []
    limiar = max(CORTE_MINIMO, 4 * float(np.median(d)))
    return [round((i + 1) / fps, 3) for i in range(len(d))
            if d[i] > limiar and d[i] >= d[max(0, i - 1)] and d[i] >= d[min(len(d) - 1, i + 1)]]


def golpes(volume, cortes=(), passo: float = PASSO) -> list:
    """
    [{"t", "forca"}] em ordem de tempo. `forca` soma a subida, quanto o volume passou do mínimo e um bônus
    se há corte de cena junto — é por ela que a receita escolhe os N golpes mais fortes.
    """
    db = np.asarray(volume, dtype=np.float32)
    if len(db) < 8:
        return []
    subida = db[4:] - db[:-4]
    depois = np.maximum.reduce([db[4:], np.r_[db[5:], db[-1]], np.r_[db[6:], db[-1], db[-1]]])
    candidatos = []
    for i in np.flatnonzero((subida >= SUBIDA_MINIMA) & (depois >= VOLUME_MINIMO)):
        t = (i + 4) * passo
        junto = any(abs(t - c) <= PERTO_DO_CORTE for c in cortes)
        candidatos.append((float(subida[i]) + 0.5 * float(depois[i] - VOLUME_MINIMO) + (6.0 if junto else 0.0), t))
    escolhidos = []
    # empate de força (a subida inteira de um estouro passa no limite por vários passos seguidos): fica o
    # primeiro instante, que é quando o som estoura — o último atrasava o efeito em até 75 ms
    for forca, t in sorted(candidatos, key=lambda c: (-c[0], c[1])):
        if all(abs(t - e["t"]) >= ESPACO_MINIMO for e in escolhidos):
            escolhidos.append({"t": round(float(t), 3), "forca": round(float(forca), 1)})
    return sorted(escolhidos, key=lambda g: g["t"])


def analisar(clipe, ffmpeg: str) -> dict:
    volume = energia(clipe, ffmpeg)
    quadros = _ler_quadros_miniatura(clipe, ffmpeg)
    n = len(quadros)
    cortes = trocas_de_plano(np.abs(np.diff(quadros, axis=0)).mean(axis=(1, 2))) if n >= 2 else []
    duracao = max(n / FPS_CORTES, len(volume) * PASSO, 0.1)
    return {"golpes": golpes(volume, cortes), "cortes": cortes, "duracao": round(duracao, 2),
            "cortes_por_minuto": round(len(cortes) / duracao * 60, 1),
            "volume_alto": round(float(np.percentile(volume, 95)), 1) if len(volume) else -90.0,
            "tomadas_acao": centros_de_acao(quadros, cortes, duracao)}



def mais_fortes(lista_de_golpes, por_minuto: float, duracao: float, espaco: float = 1.0) -> list:
    """
    Os golpes que vão ganhar efeito: os mais fortes, até `por_minuto` (proporcional à duração), e com pelo
    menos `espaco` segundos entre eles — flash colado em flash vira pisca-pisca, não ênfase.
    """
    if por_minuto <= 0:
        return []
    limite = max(1, int(round(por_minuto * duracao / 60)))
    escolhidos = []
    for g in sorted(lista_de_golpes, key=lambda g: -g["forca"]):
        if len(escolhidos) >= limite:
            break
        if all(abs(g["t"] - e["t"]) >= espaco for e in escolhidos):
            escolhidos.append(g)
    return sorted(escolhidos, key=lambda g: g["t"])


def sugerir_receita(ritmo: dict) -> tuple:
    """(receita, motivo). Palpite medido em 14 clipes (veja o topo do módulo), não classificação."""
    if ritmo["volume_alto"] < -25:
        return "emocao", f"trecho baixo e calmo (95% do tempo abaixo de {ritmo['volume_alto']:.0f} dBFS)"
    if ritmo["cortes_por_minuto"] >= 35:
        return "luta", f"{ritmo['cortes_por_minuto']:.0f} trocas de plano por minuto e {len(ritmo['golpes'])} golpes"
    return "dialogo", (f"{ritmo['cortes_por_minuto']:.0f} trocas de plano por minuto — ritmo de fala. Se for a "
                       "entrada de um personagem, experimente Aura")
