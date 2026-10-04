"""
Reconhecimento de fala no próprio computador (faster-whisper): o tempo de cada palavra medido no áudio.

Por que existe: a legenda do YouTube vem em pedaços de ~3 s, e o tempo de cada palavra dentro do pedaço era
estimado pelo tamanho dela. Medido contra um gabarito (voz neural que informa o instante exato de cada
palavra, 55 palavras, pedaços de 3 s como os do YouTube):

    estimativa   erro médio 0,118 s | 90% das palavras até 0,230 s | pior 0,952 s
    whisper      erro médio 0,048 s | 90% das palavras até 0,090 s | pior 0,303 s   (0,050 s com ruído forte)

Por que o texto NÃO vem do whisper: nos clipes reais dublados, o modelo `small` errou nomes e palavras que a
legenda do YouTube acerta ("Lengoku", "Chugue as lágrimas", "rio Harabara" no lugar de Yhwach). Então o texto
continua sendo o do YouTube (ou do .srt, ou da IA), e do whisper vem só o relógio: as duas sequências de
palavras são alinhadas, e cada palavra do texto herda o tempo da palavra ouvida que corresponde a ela.

Custo: zero em dinheiro; em tempo, ~0,5x a duração do áudio num processador de 12 núcleos (43 s de fala
em 24 s). O modelo (~480 MB) é baixado uma vez, no primeiro uso, para a pasta do Hugging Face do usuário.
"""
import difflib
import subprocess
import unicodedata
from functools import lru_cache

import numpy as np

MODELO = "small"
TAXA = 16000
COBERTURA_MINIMA = 0.4      # menos que isso de palavras casadas: texto e áudio não falam a mesma coisa


def disponivel() -> bool:
    import importlib.util
    return (importlib.util.find_spec("faster_whisper") is not None or
            importlib.util.find_spec("transformers") is not None)


@lru_cache(maxsize=1)
def _modelo(nome: str = MODELO):
    try:
        from faster_whisper import WhisperModel
        return ("faster_whisper", WhisperModel(nome, device="cpu", compute_type="int8"))
    except Exception:
        from transformers import pipeline
        modelo_hf = f"openai/whisper-{nome}" if not str(nome).startswith("openai/") else nome
        pipe = pipeline("automatic-speech-recognition", model=modelo_hf, return_timestamps="word", device="cpu")
        return ("transformers", pipe)


def audio_do_clipe(clipe, ffmpeg: str) -> np.ndarray:
    bruto = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(clipe), "-vn", "-ac", "1", "-ar", str(TAXA),
                            "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(bruto, np.float32)


def reconhecer_audio(audio: np.ndarray, idioma: str | None = None, progresso=None,
                     prompt_inicial: str | None = None) -> dict:
    """
    {"palavras": [{"texto", "inicio", "fim"}], "falas": [{"texto", "start", "dur"}], "idioma"}. As falas
    saem no formato da transcrição do YouTube, para o vídeo sem legenda seguir pela mesma análise.
    `progresso(fração)` é chamado a cada trecho reconhecido.
    `prompt_inicial` passa termos ou contexto (ex: nomes de personagens, jargões) para guiar o Whisper na CPU.
    """
    duracao = max(len(audio) / TAXA, 0.1)
    tipo_backend, engine = _modelo()
    palavras, falas = [], []
    idioma_detectado = idioma or "pt"

    if tipo_backend == "faster_whisper":
        kw = {"initial_prompt": prompt_inicial.strip()} if prompt_inicial and prompt_inicial.strip() else {}
        segmentos, info = engine.transcribe(audio, language=idioma or None, word_timestamps=True, vad_filter=True,
                                            beam_size=5, **kw)
        idioma_detectado = getattr(info, "language", idioma or "pt")
        for s in segmentos:
            texto = " ".join(s.text.split())
            if texto:
                falas.append({"texto": texto, "start": round(float(s.start), 3), "dur": round(float(s.end - s.start), 3)})
            for w in s.words or ():
                if w.word.strip():
                    palavras.append({"texto": w.word.strip(), "inicio": round(float(w.start), 3), "fim": round(float(w.end), 3)})
            if progresso:
                progresso(min(1.0, s.end / duracao))
    else:
        gen_kwargs = {}
        if idioma:
            gen_kwargs["language"] = idioma
        if prompt_inicial and prompt_inicial.strip():
            try:
                tokenizer = engine.tokenizer
                prompt_ids = tokenizer.get_prompt_ids(prompt_inicial.strip(), return_tensors="pt")
                if hasattr(prompt_ids, "squeeze"):
                    prompt_ids = prompt_ids.squeeze().tolist()
                gen_kwargs["prompt_ids"] = prompt_ids
            except Exception:
                pass

        dados_audio = {"sampling_rate": TAXA, "raw": audio}
        res = engine(dados_audio, generate_kwargs=gen_kwargs if gen_kwargs else None)
        chunks = res.get("chunks") or []
        bloco_atual_palavras = []
        bloco_inicio = 0.0

        for c in chunks:
            txt = (c.get("text") or "").strip()
            ts = c.get("timestamp")
            if not txt or not ts:
                continue
            t_ini = float(ts[0]) if ts[0] is not None else bloco_inicio
            t_fim = float(ts[1]) if ts[1] is not None else t_ini + 0.3
            t_fim = max(t_fim, t_ini + 0.05)
            palavras.append({"texto": txt, "inicio": round(t_ini, 3), "fim": round(t_fim, 3)})
            bloco_atual_palavras.append(txt)

            if t_fim - bloco_inicio >= 4.0 or txt.endswith((".", "!", "?", "…")):
                fala_txt = " ".join(bloco_atual_palavras)
                falas.append({"texto": fala_txt, "start": round(bloco_inicio, 3), "dur": round(t_fim - bloco_inicio, 3)})
                bloco_atual_palavras = []
                bloco_inicio = t_fim

        if bloco_atual_palavras:
            fala_txt = " ".join(bloco_atual_palavras)
            t_fim = palavras[-1]["fim"] if palavras else round(duracao, 3)
            falas.append({"texto": fala_txt, "start": round(bloco_inicio, 3), "dur": round(max(0.1, t_fim - bloco_inicio), 3)})

        if progresso:
            progresso(1.0)

    return {"palavras": palavras, "falas": falas, "idioma": idioma_detectado}


NOMES_DOS_IDIOMAS = {"pt": "Português", "en": "Inglês", "ja": "Japonês", "es": "Espanhol", "fr": "Francês",
                     "de": "Alemão", "it": "Italiano", "ko": "Coreano", "zh": "Chinês"}


def audio_do_video(url: str, ffmpeg: str) -> np.ndarray:
    """
    O áudio do vídeo inteiro, direto do stream, em 16 kHz mono (a entrada do whisper). Um vídeo de 20 min
    são ~20 MB baixados e ~77 MB na memória.
    """
    from cortador_video import RECONEXAO, FalhaNoCorte, _extrair_com_yt_dlp
    try:
        info = _extrair_com_yt_dlp(url, "bestaudio/best")
    except Exception as erro:
        raise FalhaNoCorte(f"não consegui ler o áudio do vídeo: {str(erro)[:200]}") from erro
    fonte = info.get("url") or next((f["url"] for f in info.get("requested_formats", []) if f.get("acodec") != "none"), None)
    if not fonte:
        raise FalhaNoCorte("o YouTube não devolveu o áudio deste vídeo")
    proc = subprocess.run([ffmpeg, "-loglevel", "error", *RECONEXAO, "-i", fonte, "-vn", "-ac", "1", "-ar", str(TAXA),
                           "-f", "f32le", "-"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise FalhaNoCorte(f"o ffmpeg não conseguiu baixar o áudio: {proc.stderr.decode(errors='ignore')[-200:]}")
    return np.frombuffer(proc.stdout, np.float32)


def transcrever_video(video_id: str, url: str, ffmpeg: str, progresso=None,
                      prompt_inicial: str | None = None) -> dict:
    """
    A transcrição de um vídeo que está com a legenda desativada, feita no computador, no formato que a análise
    usa (transcricao_youtube.transcricao_de_falas). Leva ~metade da duração do vídeo num processador de 12
    núcleos. Levanta SemTranscricao se não houver fala nenhuma.
    """
    from transcricao_youtube import SemTranscricao, transcricao_de_falas
    audio = audio_do_video(url, ffmpeg)
    kw = {"prompt_inicial": prompt_inicial} if prompt_inicial else {}
    reconhecido = reconhecer_audio(audio, progresso=progresso, **kw)
    if not reconhecido["falas"]:
        raise SemTranscricao("O reconhecimento não ouviu fala nenhuma neste vídeo.", True)
    codigo = reconhecido["idioma"] or ""
    nome = NOMES_DOS_IDIOMAS.get(codigo, codigo) + " (reconhecido no computador)"
    return transcricao_de_falas(video_id, reconhecido["falas"], nome, codigo, reconhecido["palavras"])


def ouvidas_no_trecho(palavras_ouvidas, inicio: float, fim: float) -> list:
    """As palavras ouvidas num trecho do vídeo, com o tempo relativo ao começo do trecho."""
    return [{**p, "inicio": round(p["inicio"] - inicio, 3), "fim": round(p["fim"] - inicio, 3)}
            for p in palavras_ouvidas or () if inicio <= (p["inicio"] + p["fim"]) / 2 < fim]


_RECONHECIDOS = {}


def reconhecer_clipe(clipe, ffmpeg: str, idioma: str | None = None,
                     prompt_inicial: str | None = None) -> dict:
    """reconhecer_audio de um arquivo, guardado por arquivo: a prévia e a montagem do mesmo trecho não repetem."""
    from pathlib import Path
    caminho = Path(clipe)
    chave = (str(caminho.resolve()), caminho.stat().st_mtime, idioma, prompt_inicial)
    if chave not in _RECONHECIDOS:
        kw = {"prompt_inicial": prompt_inicial} if prompt_inicial else {}
        _RECONHECIDOS[chave] = reconhecer_audio(audio_do_clipe(clipe, ffmpeg), idioma, **kw)
    return _RECONHECIDOS[chave]


# ==============================================================================
# ALINHAMENTO: o texto de uma fonte, o tempo de outra
# ==============================================================================
def _sem_escrita_com_espaco(texto: str) -> bool:
    """Japonês e chinês não separam palavras com espaço: lá, a unidade do alinhamento é o caractere."""
    return any(0x3040 <= ord(c) <= 0x9FFF or 0xF900 <= ord(c) <= 0xFAFF for c in texto)


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if c.isalnum())


def _unidades(palavras, por_caractere: bool) -> list:
    """(texto normalizado, índice da palavra de origem, início, fim). No modo caractere, o tempo da palavra é
    repartido entre os caracteres dela."""
    saida = []
    for i, p in enumerate(palavras):
        texto = _normalizar(p["texto"])
        if not texto:
            continue
        if not por_caractere:
            saida.append((texto, i, p["inicio"], p["fim"]))
            continue
        passo = (p["fim"] - p["inicio"]) / len(texto)
        saida += [(c, i, p["inicio"] + k * passo, p["inicio"] + (k + 1) * passo) for k, c in enumerate(texto)]
    return saida


DURACAO_POR_CARACTERE, DURACAO_MINIMA, DURACAO_MAXIMA = 0.07, 0.15, 0.7


def _duracao_natural(texto: str) -> float:
    return min(DURACAO_MAXIMA, max(DURACAO_MINIMA, len(texto) * DURACAO_POR_CARACTERE))


def _espalhar(pesos: list, intervalos: list) -> list:
    """
    Reparte palavras (pelo tamanho) sobre os intervalos em que se ouviu fala, pulando os silêncios entre eles.
    Repartir o vão inteiro deu 4,3 s a "superestimando", porque o trecho atravessava 3 s de silêncio.
    """
    falado = [max(0.0, fim - ini) for ini, fim in intervalos]
    total_falado, total_peso = sum(falado), sum(pesos)
    if total_falado <= 0 or total_peso <= 0:
        return [(intervalos[0][0], intervalos[-1][1])] * len(pesos)

    def relogio(fracao):
        """(instante no relógio, índice do intervalo) de uma fração do tempo falado."""
        resto = fracao * total_falado
        for k, ((ini, fim), d) in enumerate(zip(intervalos, falado)):
            if resto <= d:
                return ini + resto, k
            resto -= d
        return intervalos[-1][1], len(intervalos) - 1
    saida, acumulado = [], 0
    for peso in pesos:
        (ini, _), (fim, _) = relogio(acumulado / total_peso), relogio((acumulado + peso) / total_peso)
        # a palavra fica presa ao intervalo onde está o meio dela: sem isso, a que cai na virada de um
        # intervalo para o outro atravessava o silêncio entre eles e ganhava segundos a mais
        _, k = relogio((acumulado + peso / 2) / total_peso)
        saida.append((max(ini, intervalos[k][0]), min(fim, intervalos[k][1])))
        acumulado += peso
    return saida


def alinhar(texto_palavras: list, ouvidas: list) -> tuple:
    """
    Devolve (palavras do texto com o tempo do áudio, cobertura). O texto manda; o áudio só dá o relógio.

    As duas sequências são comparadas unidade a unidade (palavra, ou caractere em japonês e chinês):
    - igual: a unidade do texto herda o tempo da ouvida;
    - trocada ("Ele" no texto, "Leng" no que o whisper ouviu): herda o intervalo das ouvidas daquele trecho;
    - só no texto (o whisper não ouviu "Mamãe"): fica colada na vizinha, com duração natural — colada na
      seguinte quando começa frase, na anterior quando continua. A primeira versão repartia essas palavras
      pelo vão inteiro entre as vizinhas, silêncio incluído, e "Mamãe" foi parar 8 s antes de ser dita.
    Cobertura baixa (texto e áudio não falam a mesma coisa: outra língua, outra cena) devolve o texto como veio.
    """
    if not texto_palavras or not ouvidas:
        return list(texto_palavras), 0.0
    por_caractere = _sem_escrita_com_espaco(" ".join(p["texto"] for p in texto_palavras))
    a, b = _unidades(texto_palavras, por_caractere), _unidades(ouvidas, por_caractere)
    if not a or not b:
        return list(texto_palavras), 0.0
    casador = difflib.SequenceMatcher(None, [u[0] for u in a], [u[0] for u in b], autojunk=False)
    tempo = [None] * len(a)                     # (início, fim) medido de cada unidade do texto
    iguais = 0
    for operacao, i1, i2, j1, j2 in casador.get_opcodes():
        if operacao == "equal":
            for k in range(i2 - i1):
                tempo[i1 + k] = (b[j1 + k][2], b[j1 + k][3])
            iguais += i2 - i1
        elif operacao == "replace":
            intervalos = [(b[j][2], b[j][3]) for j in range(j1, j2)]
            if i2 - i1 == j2 - j1:
                # mesma contagem dos dois lados ("superestimando R" x "superestido Rado"): uma para uma
                for i, t in zip(range(i1, i2), intervalos):
                    tempo[i] = t
            else:
                for i, t in zip(range(i1, i2), _espalhar([len(a[i][0]) for i in range(i1, i2)], intervalos)):
                    tempo[i] = t
    cobertura = iguais / len(a)
    if cobertura < COBERTURA_MINIMA:
        return list(texto_palavras), round(cobertura, 3)

    # só no texto: cola na vizinha medida
    for i in range(len(a)):
        if tempo[i] is not None:
            continue
        j = i
        while j < len(a) and tempo[j] is None:
            j += 1
        faltando = list(range(i, j))
        duracoes = [_duracao_natural(a[k][0]) if not por_caractere else 0.12 for k in faltando]
        anterior = tempo[i - 1] if i > 0 else None
        seguinte = tempo[j] if j < len(a) else None
        palavra_anterior = texto_palavras[a[i - 1][1]]["texto"] if i > 0 else ""
        continua_frase = anterior is not None and not palavra_anterior.rstrip("\"')»”’").endswith(tuple(".!?…"))
        if seguinte is not None and not continua_frase:
            t = seguinte[0] - sum(duracoes)
            if anterior is not None:
                t = max(t, anterior[1])
        elif anterior is not None:
            t = anterior[1]
        else:
            continue                                   # nada medido em volta: fica o tempo estimado
        for k, d in zip(faltando, duracoes):
            tempo[k] = (t, t + d)
            t += d

    saida = [dict(p) for p in texto_palavras]
    por_palavra = {}
    for (_, origem, _, _), t in zip(a, tempo):
        if t is None:
            continue
        atual = por_palavra.get(origem)
        por_palavra[origem] = (min(t[0], atual[0]), max(t[1], atual[1])) if atual else t
    for i, (ini, fim) in por_palavra.items():
        saida[i]["inicio"], saida[i]["fim"] = round(ini, 3), round(fim, 3)
    return saida, round(cobertura, 3)
