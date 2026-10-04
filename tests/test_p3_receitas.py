"""Receitas de edição por situação: onde estão os golpes, os efeitos que caem neles e a câmera lenta."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

import editor_reels as ed
import efeitos as ef
import momentos as mo
import publicacao as pub
import renderizador_generico as rg
from core.midia import localizar_ffmpeg
from temas_video import PRESETS, TEMA_PADRAO

CATALOGO_ML = Path(__file__).resolve().parents[1] / "corte_otakubr" / "dados_produtos.json"
TEMA = PRESETS[TEMA_PADRAO]


def _clipe_com_golpes(tmp_path, golpes=(1.0, 2.6), segundos=4.0):
    """Vídeo de teste com som baixo e estouros curtos e altos nos instantes dados."""
    quando = "+".join(f"between(t,{g},{g + 0.15})" for g in golpes)
    saida = tmp_path / "golpes.mp4"
    subprocess.run([localizar_ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-f", "lavfi", "-i", f"aevalsrc='0.01*sin(2*PI*220*t)+0.9*sin(2*PI*180*t)*({quando})':s=44100",
                    "-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(saida)], check=True)
    return saida


# --- golpes e cortes de cena -----------------------------------------------------------------------

def _volume(eventos, duracao=4.0, base=-40.0, pico=-8.0):
    passos = int(duracao / mo.PASSO)
    db = np.full(passos, base, dtype=np.float32)
    for t in eventos:
        i = int(t / mo.PASSO)
        db[i:i + 6] = pico
    return db


def test_estouro_alto_vira_golpe_no_instante_certo():
    achados = mo.golpes(_volume([1.0, 2.5]))
    assert [round(g["t"], 1) for g in achados] == [1.0, 2.5]


def test_fala_baixa_nao_vira_golpe():
    """A despedida do Rengoku dava 50 'golpes' por minuto quando o limite era relativo ao próprio clipe."""
    assert mo.golpes(_volume([1.0, 2.0, 3.0], base=-50.0, pico=-28.0)) == []


def test_golpe_junto_de_corte_de_cena_pesa_mais():
    sem = mo.golpes(_volume([1.0]))[0]["forca"]
    com = mo.golpes(_volume([1.0]), cortes=[1.02])[0]["forca"]
    assert com > sem


def test_corte_de_cena_e_diferenca_grande_entre_quadros():
    diferencas = [2, 3, 2, 60, 3, 2, 2, 55, 2]
    assert mo.trocas_de_plano(diferencas, fps=12) == [round(4 / 12, 3), round(8 / 12, 3)]


def test_escolhe_os_mais_fortes_espacados():
    lista = [{"t": 1.0, "forca": 10}, {"t": 1.5, "forca": 30}, {"t": 5.0, "forca": 20}, {"t": 9.0, "forca": 5}]
    assert [g["t"] for g in mo.mais_fortes(lista, por_minuto=20, duracao=9.0)] == [1.5, 5.0, 9.0]
    assert [g["t"] for g in mo.mais_fortes(lista, por_minuto=7, duracao=9.0)] == [1.5]
    assert mo.mais_fortes(lista, por_minuto=0, duracao=9.0) == []


@pytest.mark.parametrize("ritmo,esperada", [
    ({"volume_alto": -29.4, "cortes_por_minuto": 23.7, "golpes": []}, "emocao"),     # despedida do Rengoku
    ({"volume_alto": -13.9, "cortes_por_minuto": 59.0, "golpes": [1] * 41}, "luta"),  # Gojo x Toji
    ({"volume_alto": -17.6, "cortes_por_minuto": 16.5, "golpes": [1] * 27}, "dialogo"),  # Aizen falando
])
def test_sugestao_de_receita_pelos_numeros_medidos(ritmo, esperada):
    assert mo.sugerir_receita(ritmo)[0] == esperada


def test_analise_de_um_clipe_de_verdade(tmp_path):
    ritmo = mo.analisar(_clipe_com_golpes(tmp_path), localizar_ffmpeg())
    assert [round(g["t"]) for g in ritmo["golpes"]] == [1, 3]
    assert abs(ritmo["golpes"][0]["t"] - 1.0) < 0.15 and abs(ritmo["golpes"][1]["t"] - 2.6) < 0.15


# --- receitas e efeitos -----------------------------------------------------------------------------

def test_toda_receita_existe_e_so_luta_aura_e_comedia_procuram_golpe():
    assert set(ef.RECEITAS) == {"luta", "aura", "emocao", "comedia", "dialogo"}
    assert {n for n in ef.RECEITAS if ef.receita(n).usa_golpes} == {"luta", "aura", "comedia"}
    assert ef.receita("inexistente") == ef.SEM_ARTE


def test_emocao_nao_tem_nada_que_distraia():
    emocao = ef.receita("emocao")
    assert not emocao.usa_golpes and emocao.fator_zoom == 1.0 and emocao.transicao == "fade"


def test_filtros_de_cor_das_receitas_rodam_no_ffmpeg():
    ffmpeg = localizar_ffmpeg()
    for nome in ("sombrio", "melancolico"):
        proc = subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=5", "-t", "0.4",
                               "-vf", ef.LOOKS[nome][1], "-f", "null", "-"], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr[-200:]


def test_quadro_de_impacto_dura_dois_quadros_e_o_flash_vem_depois():
    filtro = ef.filtros_dos_golpes([{"t": 2.0, "forca": 1}], ef.receita("luta"))
    assert "negate=enable='between(t,2.000,2.083)'" in filtro
    assert "eq=brightness=0.45:enable='between(t,2.083,2.125)'" in filtro
    assert "rgbashift" in filtro


def test_aura_usa_o_quadro_vermelho():
    assert ef.filtros_dos_golpes([{"t": 1.0, "forca": 1}], ef.receita("aura")).startswith("colorchannelmixer=")


def test_sem_golpe_nao_ha_filtro_de_golpe():
    assert ef.filtros_dos_golpes([], ef.receita("luta")) == ""


def test_a_tremida_para_no_fim_da_janela_e_nao_passa_da_folga():
    partes = ";".join(ef.filtro_de_zoom("v0", "vz", [], 1.0, 1080, 1920, tremidas=[(1.0, 1.35)], amplitude=26))
    assert "between(t,1.000,1.350)*(1-(t-1.000)/0.350)" in partes
    fator = float(partes.split("crop=iw/")[1].split(":")[0])
    assert 1080 * (1 - 1 / fator) / 2 >= 26                    # a folga do recorte cobre a amplitude


def test_brilho_soma_so_a_luminancia():
    """Somar as três componentes deixava uma coluna roxa na borda direita quando havia filtro de cor antes."""
    filtro = ed.filtro_de_composicao((1080, 607, 0, 566), [], 5.0, "0x0@1", brilho=True)
    assert "c0_mode=screen" in filtro and "c1_opacity=0" in filtro and "gbrp" not in filtro


def test_faixa_de_cinema_recorta_a_frente_e_mantem_ela_centralizada():
    filtro = ed.filtro_de_composicao((1080, 607, 0, 566), [], 5.0, "0x0@1", cinemascope=True)
    assert "crop=1080:452" in filtro and "overlay=0:643" in filtro


# --- câmera lenta ------------------------------------------------------------------------------------

def test_o_trecho_lento_fica_em_volta_do_golpe_mais_forte():
    golpes = [{"t": 1.0, "forca": 5}, {"t": 3.0, "forca": 9}]
    assert ef.trecho_lento(golpes, 10.0) == (2.5, 3.7)
    assert ef.trecho_lento([{"t": 0.1, "forca": 1}], 0.5) is None       # não cabe no clipe


def test_remapear_estica_o_meio_e_empurra_o_resto():
    lento = (2.0, 3.0)
    assert ef.remapear(1.0, lento) == 1.0
    assert ef.remapear(2.5, lento) == 3.0
    assert ef.remapear(5.0, lento) == 6.0


def test_legenda_e_palavras_acompanham_a_camera_lenta():
    bloco = {"texto": "oi", "inicio": 4.0, "fim": 5.0, "palavras": [{"texto": "oi", "inicio": 4.0, "fim": 4.5}]}
    novo = ef.remapear_legendas([bloco], (1.0, 2.0))[0]
    assert (novo["inicio"], novo["fim"], novo["palavras"][0]["inicio"]) == (5.0, 6.0, 5.0)


def test_luta_com_camera_lenta_de_verdade_alonga_o_video_e_o_srt(tmp_path):
    clipe = _clipe_com_golpes(tmp_path)
    legendas = [{"texto": "depois do golpe", "inicio": 3.0, "fim": 3.8}]
    dados = ed.montar_reels(clipe, tema=TEMA, titulo="", legendas=legendas, arte=ef.receita("luta"),
                            estilo_legenda=ed.IMPACTO, nome_arquivo="luta.mp4", pasta_saida=tmp_path / "saida")
    esticado = (ef.ANTES_DO_GOLPE + ef.DEPOIS_DO_GOLPE) * (1 / ef.FATOR_LENTO - 1)
    real = ed.sondar_clipe(dados["caminho"], localizar_ffmpeg())
    assert real["duracao"] == pytest.approx(4.0 + esticado, abs=0.2) and real["tem_audio"]
    srt = (tmp_path / "saida" / "luta.srt").read_text(encoding="utf-8")
    assert "00:00:03,000" not in srt                                  # a legenda foi empurrada junto


def test_previa_com_camera_lenta_funciona_e_cai_no_golpe(tmp_path):
    """A prévia não tem som; o áudio esticado ficava sem saída e o ffmpeg recusava o filtro inteiro."""
    clipe = _clipe_com_golpes(tmp_path)
    quadro = ed.previa(clipe, tema=TEMA, em=1.02, arte=ef.receita("luta"))
    assert quadro.size == (1080, 1920)


def test_separacao_rgb_nao_deixa_fio_colorido_na_borda(tmp_path):
    """Feita no quadro final, a separação RGB deixava um fio azul na borda direita; no ramo ampliado, não."""
    clipe = _clipe_com_golpes(tmp_path)
    props = ed.sondar_clipe(clipe, localizar_ffmpeg())
    plano = ed.planejar_golpes(clipe, localizar_ffmpeg(), props, ef.receita("luta"))
    quadro = np.asarray(ed.previa(clipe, tema=TEMA, em=ef.remapear(plano["golpes"][0]["t"], plano["lento"]) + 0.12,
                                  arte=ef.receita("luta"), plano=plano)).astype(int)
    borda, vizinha = quadro[300:1600, 1078].mean(axis=0), quadro[300:1600, 1060].mean(axis=0)
    assert np.abs(borda - vizinha).max() < 40


# --- legenda traduzida da fala --------------------------------------------------------------------

def test_lixo_em_coreano_no_meio_do_portugues_sai_da_tela():
    """A legenda automática da luta do Rengoku trazia '가사주 메시지ли' no meio da fala."""
    assert rg.limpar_para_tela("se tornar um ani. 가사주 메시지ли. Ali") == "se tornar um ani. ли. Ali"


def test_bloco_que_so_tinha_escrita_sem_fonte_nao_vira_estado():
    blocos = [{"texto": "この力は", "inicio": 0.0, "fim": 1.0}, {"texto": "oi", "inicio": 1.0, "fim": 2.0}]
    assert [e["texto"] for e in ed.estados_da_legenda(blocos)] == ["oi"]


@pytest.mark.parametrize("texto,esperado", [("この力は、お前からみんなを守るために", False), ("Olá, tudo bem?", True),
                                            ("Acabou. 가사주 메시지. Respiração das chamas técnica", True), ("", True)])
def test_escrita_desenhavel_pela_maior_parte_das_letras(texto, esperado):
    assert pub.escrita_desenhavel(texto) is esperado


@pytest.mark.parametrize("texto,esperado", [
    ("Não odeio ninguém. Você era membro do clã Zenin, né?", True),
    ("I will never forgive you for what you did to my friends", False),
    ("No puedo creer que hayas llegado tan lejos, ahora vas a pagar", False),
])
def test_palpite_de_portugues_para_nao_traduzir_a_toa(texto, esperado):
    assert pub.parece_portugues(texto) is esperado


def test_traduzir_para_portugues_quando_a_fala_e_de_outro_idioma(cliente_falso):
    cliente = cliente_falso(json.dumps({"textos": ["Só agora você mostra"]}))
    assert pub.traduzir(["ようやく見せるか"], "pt", cliente, origem="ja")["textos"] == ["Só agora você mostra"]
    assert pub.traduzir(["já em português"], "pt", cliente, origem="pt")["textos"] == ["já em português"]
    assert len(cliente.models.chamadas) == 1                          # português para português não chama


def test_video_em_portugues_de_fala_japonesa_traduz_so_a_legenda(cliente_falso):
    from ui_video_pronto import _traduzir_tudo

    cliente = cliente_falso(json.dumps({"textos": ["Só agora você mostra"]}))
    legendas = [{"texto": "ようやく見せるか", "inicio": 0.0, "fim": 2.0}]
    textos, novas, aviso = _traduzir_tudo({"titulo": "Título em português"}, legendas, "pt", cliente, "ja")
    assert textos == {"titulo": "Título em português"} and novas[0]["texto"] == "Só agora você mostra"
    assert "Título em português" not in cliente.models.chamadas[0]["contents"]    # o texto de tela não foi junto


def test_sem_traducao_a_fala_japonesa_nao_vira_quadradinho(cliente_falso, erro_api):
    from ui_video_pronto import _traduzir_tudo

    legendas = [{"texto": "ようやく見せるか", "inicio": 0.0, "fim": 2.0}]
    _, novas, aviso = _traduzir_tudo({"titulo": "t"}, legendas, "pt", cliente_falso(erro_api(500)), "ja")
    assert novas == [] and "sem legenda" in aviso


def test_legenda_no_idioma_da_fala_nao_e_traduzida(cliente_falso):
    from ui_video_pronto import _traduzir_tudo

    cliente = cliente_falso("nunca")
    legendas = [{"texto": "hello there", "inicio": 0.0, "fim": 2.0}]
    _, novas, _ = _traduzir_tudo({"titulo": "t"}, legendas, "pt", cliente, "en", legenda_acompanha=False)
    assert novas[0]["texto"] == "hello there" and cliente.models.chamadas == []


def test_edicao_traduz_os_trechos_numa_chamada_so(cliente_falso):
    import ui_ferramentas as uf

    cliente = cliente_falso(json.dumps({"textos": ["um", "dois", "três"]}))
    listas = [[{"texto": "one", "inicio": 0, "fim": 1}], [{"texto": "two", "inicio": 0, "fim": 1},
                                                           {"texto": "three", "inicio": 1, "fim": 2}]]
    traduzidas, aviso = uf.traduzir_varios(listas, "pt", cliente, "en")
    assert [[b["texto"] for b in l] for l in traduzidas] == [["um"], ["dois", "três"]] and aviso is None
    assert len(cliente.models.chamadas) == 1


# --- speed ramping, mangá P&B, motion blur, glitch, áudio estúdio e card Mercado Livre --------------

def test_quadro_manga_motion_blur_e_glitch_nos_golpes():
    arte = ef.DirecaoDeArte(golpes_por_minuto=12, quadro_de_impacto="manga", rastro_movimento=True, glitch=True)
    assert arte.usa_golpes
    filtro = ef.filtros_dos_golpes([{"t": 1.5, "forca": 10}], arte)
    assert "eq=saturation=0:contrast=3.0:brightness=0.05:enable='between(t,1.500,1.583)'" in filtro
    assert "tblend=all_mode=average:enable=" in filtro
    assert "rgbashift=rh=22:bh=-22:rv=10:bv=-10:edge=wrap:enable=" in filtro


def test_speed_ramping_multi_golpe_acelera_e_freia_remapeando_tempos():
    golpes = [{"t": 1.0, "forca": 20}, {"t": 2.8, "forca": 15}]
    segs = ef.trechos_velocity(golpes, 4.0)
    assert segs is not None and len(segs) == 4
    # Primeiro golpe: acelera (1.5x) de 0.65 a 1.0 e freia (0.5x) de 1.0 a 1.45
    assert segs[0] == (0.65, 1.0, ef.FATOR_RAPIDO)
    assert segs[1] == (1.0, 1.45, ef.FATOR_LENTO)
    filtro = ef.filtro_de_velocidade(segs, 4.0, tem_audio=True)
    assert "atempo=1.5" in filtro and "atempo=0.5" in filtro and filtro.endswith("[vel_v][vel_a]")
    # Remapeamento preserva monotonia
    t_antes = ef.remapear(0.5, segs)
    t_meio = ef.remapear(1.2, segs)
    t_fim = ef.remapear(4.0, segs)
    assert 0.5 == t_antes < t_meio < t_fim


def test_banco_de_sons_e_expressao_auto_ducking(tmp_path):
    import audio_estudio as ae

    sons = ae.garantir_banco_de_sons(tmp_path / "sons")
    assert {"bass_drop", "whoosh", "glitch", "luta", "aura", "emocao"} <= set(sons)
    assert all(p.exists() and p.stat().st_size > 1000 for p in sons.values())

    legendas = [{"texto": "fala um", "inicio": 1.0, "fim": 2.0}]
    expr = ae.expressao_ducking(legendas, 5.0, volume_cheio=0.30, auto_ducking=True)
    assert "between(t,0.880,2.120)" in expr and "0.090,0.300" in expr


def test_corte_de_silencios_remove_pausas_longas_e_remapeia_legenda():
    import audio_estudio as ae

    # 4s totais, com silêncio entre 1.0s e 2.5s
    db = np.full(int(4.0 / mo.PASSO), -14.0, dtype=np.float32)
    db[int(1.0 / mo.PASSO):int(2.5 / mo.PASSO)] = -45.0
    ativos = ae.detectar_intervalos_ativos(db, 4.0, limiar_db=-32.0, min_silencio=0.45)
    assert len(ativos) == 2
    assert ativos[0][0] == 0.0 and ativos[0][1] == pytest.approx(1.08, abs=0.05)
    assert ativos[1][0] == pytest.approx(2.42, abs=0.05) and ativos[1][1] == 4.0

    leg = [{"texto": "depois do silencio", "inicio": 2.6, "fim": 3.4}]
    remap = ae.remapear_legendas_cortes(leg, ativos)
    assert len(remap) == 1 and remap[0]["inicio"] < 1.5


@pytest.mark.skipif(not CATALOGO_ML.exists(), reason="catálogo do projeto à parte (corte_otakubr) não faz parte do portfólio público")
def test_card_flutuante_mercado_livre_corte_otakubr_e_mixagem_completa(tmp_path):
    import audio_estudio as ae

    produtos = ed.carregar_produtos_ml()
    assert len(produtos) >= 1
    card = ed.desenhar_card_produto_ml(produtos[0])
    assert card.size == (1080, 1920)
    assert card.crop((60, 1270, 1020, 1510)).getbbox() is not None

    clipe = _clipe_com_golpes(tmp_path)
    tema_otaku = PRESETS["@corte.otakubr (Tokyo Archive)"]
    arte = ef.DirecaoDeArte(
        look="sombrio", vinheta=True, golpes_por_minuto=18, quadro_de_impacto="manga",
        flash=True, tremida=20, glitch=True, rastro_movimento=True, speed_ramping=True,
    )
    cfg_audio = ae.ConfigAudio(trilha="luta", volume_trilha=0.30, auto_ducking=True, sfx_impacto=True)
    dados = ed.montar_reels(
        clipe, tema=tema_otaku, titulo="",
        legendas=[{"texto": "expansão de domínio", "inicio": 0.3, "fim": 1.2}],
        arte=arte, estilo_legenda=ed.IMPACTO, produto_ml=produtos[0], config_audio=cfg_audio,
        nome_arquivo="otaku_ml.mp4", pasta_saida=tmp_path / "saida",
    )
    info = ed.sondar_clipe(dados["caminho"], localizar_ffmpeg())
    assert (info["largura"], info["altura"]) == (1080, 1920) and info["tem_audio"]


def test_auto_reframe_por_tomada_rastreia_centro_de_acao_horizontal(tmp_path):
    # Simula 2 tomadas em miniatura (12 quadros a 12 fps = 1.0s):
    # Tomada 1 (0 a 0.5s): ação piscando no canto esquerdo (colunas 5..15)
    # Tomada 2 (0.5 a 1.0s): ação piscando no canto direito (colunas 78..90)
    quadros = np.zeros((12, 54, 96), dtype=np.float32)
    for k in range(6):
        quadros[k, 10:35, 5:15] = 220.0 if k % 2 == 0 else 20.0
    for k in range(6, 12):
        quadros[k, 10:35, 78:90] = 240.0 if k % 2 == 0 else 10.0

    tomadas = mo.centros_de_acao(quadros, [0.5], duracao=1.0)
    assert len(tomadas) == 2
    assert tomadas[0]["x_rel"] < 0.30
    assert tomadas[1]["x_rel"] > 0.70

    filtro = ed.filtro_de_composicao(None, [], 1.0, "0xFFFFFF@1.00", tomadas_acao=tomadas)
    assert "crop=1080:1920:x='(iw-ow)*(" in filtro
    assert "between(t,0.00,0.50)" in filtro

    # Teste de integração do enquadramento ACAO com ffmpeg real
    clipe = _clipe_com_golpes(tmp_path)
    dados = ed.montar_reels(
        clipe, tema=PRESETS["@corte.otakubr (Tokyo Archive)"], titulo="",
        enquadramento=ed.ACAO, nome_arquivo="acao_smart.mp4", pasta_saida=tmp_path / "saida_acao",
    )
    info = ed.sondar_clipe(dados["caminho"], localizar_ffmpeg())
    assert (info["largura"], info["altura"]) == (1080, 1920)


def test_score_viral_hibrido_pontua_gancho_ritmo_e_fechamento():
    from cortador_video import calcular_score_viral

    palavras = [
        {"texto": "Por", "inicio": 10.0, "fim": 10.2},
        {"texto": "que", "inicio": 10.2, "fim": 10.4},
        {"texto": "ninguém", "inicio": 10.4, "fim": 10.8},
        {"texto": "conta", "inicio": 10.8, "fim": 11.1},
        {"texto": "o", "inicio": 11.1, "fim": 11.2},
        {"texto": "segredo?", "inicio": 11.2, "fim": 11.6},
    ] + [
        {"texto": f"palavra{i}" + ("." if i == 99 else ""), "inicio": 12.0 + i * 0.35, "fim": 12.3 + i * 0.35}
        for i in range(100)
    ]
    corte_forte = {
        "titulo": "O segredo mais chocante da luta final!",
        "inicio_segundos": 10,
        "fim_segundos": 48,
        "motivo_viral": "Gancho direto com pergunta e revelação.",
    }
    forte = calcular_score_viral(corte_forte, palavras, duracao_video=300)
    assert forte["score_viral"] >= 88
    assert "🔥" in forte["selo_viral"]
    assert "Duração ideal (30–60s)" in forte["fatores_virais"]

    corte_fraco = {
        "titulo": "Corte #1: trecho...",
        "inicio_segundos": 10,
        "fim_segundos": 22,
        "motivo_viral": "Posição escolhida pela minutagem do vídeo (sem análise de conteúdo).",
    }
    fraco = calcular_score_viral(corte_fraco, [], duracao_video=300)
    assert fraco["score_viral"] < forte["score_viral"]


@pytest.mark.skipif(not CATALOGO_ML.exists(), reason="catálogo do projeto à parte (corte_otakubr) não faz parte do portfólio público")
def test_sugerir_produto_ml_casa_anime_e_personagem_com_catalogo():
    p_gojo = ed.sugerir_produto_ml("Nesse episódio Satoru Gojo usa o Vazio Roxo contra Sukuna em Jujutsu")
    assert p_gojo is not None and p_gojo["id"] == "fig-001"

    p_zoro = ed.sugerir_produto_ml("A espada Enma de Roronoa Zoro cortando tudo em Wano")
    assert p_zoro is not None and p_zoro["anime"] == "One Piece"

    p_berserk = ed.sugerir_produto_ml("O traço sombrio de Guts e Griffith no mangá de Berserk")
    assert p_berserk is not None and p_berserk["id"] == "man-001"

    assert ed.sugerir_produto_ml("Vídeo de culinária sem relação com anime", usar_destaque_padrao=False) is None
    padrao = ed.sugerir_produto_ml("Vídeo genérico sem match", usar_destaque_padrao=True)
    assert padrao is not None and padrao.get("destaque") is True


