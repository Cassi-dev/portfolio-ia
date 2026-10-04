"""Legenda legível pelo padrão profissional, e as falhas do YouTube explicadas em português."""
import inspect

import pytest

import editor_reels as ed
import legendas as lg
import renderizador_generico as rg
import transcricao_youtube as ty

FONTE = rg.fonte(True, 52)


# --- quebra de linha (guia da Netflix para português do Brasil) ------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Então agora, que tal remover os selos das minhas mãos", ["Então agora, que tal remover", "os selos das minhas mãos"]),
    ("Senhor Rengoku, tá na hora da gente ter uma última conversa.",
     ["Senhor Rengoku, tá na hora", "da gente ter uma última conversa."]),
    ("Entre o céu e a terra, sou o mais honrado.", ["Entre o céu e a terra,", "sou o mais honrado."]),
])
def test_quebra_depois_da_pontuacao_ou_antes_da_preposicao(texto, esperado):
    assert ed.quebrar_legenda(texto, FONTE, 900) == esperado


def test_nao_separa_nome_do_adjetivo_so_para_equilibrar():
    """Com o equilíbrio pesando mais que a gramática, "certeza / absoluta" foi partida ao meio."""
    linhas = ed.quebrar_legenda("Ah, mas eu tenho certeza absoluta que você consegue.", FONTE, 900)
    assert not linhas[0].endswith("certeza")


def test_linha_nunca_termina_em_artigo():
    for texto in ("Eu vou pegar o livro que você deixou na mesa da cozinha ontem",
                  "Ela disse que a resposta estava no fundo da gaveta de cima"):
        linhas = ed.quebrar_legenda(texto, FONTE, 900)
        assert linhas[0].split()[-1].lower() not in {"o", "a", "os", "as", "um", "uma", "da", "do"}


def test_texto_curto_fica_numa_linha_e_longo_demais_nao_cabe_em_duas():
    assert ed.quebrar_legenda("Tudo bem.", FONTE, 900) == ["Tudo bem."]
    assert ed.quebrar_legenda("palavra " * 40, FONTE, 900) is None


def test_no_maximo_duas_linhas_quando_cabe_em_fonte_menor():
    _, linhas = ed.ajustar_legenda("Aquelas coisas eram uma torrente de poder do Yhwach, e ninguém esperava.",
                                   (52, 48, 44, 40), 900)
    assert len(linhas) <= 2


# --- tempo na tela ----------------------------------------------------------------------------------

def test_bloco_esticado_pela_musica_sai_no_tempo_de_leitura():
    """Um pedaço da legenda automática atravessou 8 s de música e deixou o bloco 8,8 s na tela."""
    bloco = lg._fechar([{"texto": "Está me superestimando.", "inicio": 21.3, "fim": 29.6}], lg.CAUDA, lg.MINIMO)[0]
    assert bloco["fim"] - bloco["inicio"] < 4.5


def test_fala_lenta_de_verdade_nao_e_cortada():
    bloco = lg._fechar([{"texto": "fala curta.", "inicio": 0.0, "fim": 2.0}], lg.CAUDA, lg.MINIMO)[0]
    assert bloco["fim"] == pytest.approx(2.0 + lg.CAUDA)


def test_nunca_mais_que_sete_segundos():
    texto = "uma frase longa, falada devagar, que ocupa a tela por muito tempo mesmo"
    bloco = lg._fechar([{"texto": texto, "inicio": 0.0, "fim": 9.5}], lg.CAUDA, lg.MINIMO)[0]
    assert bloco["fim"] - bloco["inicio"] <= lg.MAX_NA_TELA


def test_bloco_curto_demais_ganha_o_minimo_se_houver_espaco():
    blocos = lg._fechar([{"texto": "Oi.", "inicio": 0.0, "fim": 0.2}, {"texto": "Tudo?", "inicio": 3.0, "fim": 3.5}],
                        0.0, lg.MINIMO)
    assert blocos[0]["fim"] - blocos[0]["inicio"] >= lg.MIN_NA_TELA - 0.01


def test_o_minimo_nao_invade_o_bloco_seguinte():
    blocos = lg._fechar([{"texto": "Oi.", "inicio": 0.0, "fim": 0.2}, {"texto": "Tudo?", "inicio": 0.5, "fim": 1.5}],
                        0.0, 0.1)
    assert blocos[0]["fim"] <= blocos[1]["inicio"]


def test_bloco_nao_passa_de_duas_linhas_de_texto():
    falas = [{"texto": "palavra comprida " * 12, "start": 0.0, "dur": 3.9}]
    blocos = lg.agrupar_palavras(lg.palavras_com_tempo(falas))
    assert len(blocos) > 1 and all(len(b["texto"]) <= lg.MAX_CARACTERES for b in blocos)


def test_marcacoes_da_legenda_automatica_nao_viram_fala():
    assert lg.sem_anotacoes("[Música] e então ♪ ele veio [Aplausos]") == "e então ele veio"
    palavras = lg.palavras_com_tempo([{"texto": "[Música] ele veio", "start": 0.0, "dur": 2.0}])
    assert [p["texto"] for p in palavras] == ["ele", "veio"]


# --- custo: quem não precisa de IA não chama ---------------------------------------------------------

def test_editor_local_nao_revisa_srt_nem_transcricao():
    """O .srt já é legenda pronta e a transcrição já vem pontuada: revisar seria pagar por nada."""
    import ui_local
    assert "client" not in inspect.signature(ui_local._legendas_do_trecho).parameters


# --- falhas do YouTube em português --------------------------------------------------------------------

def _erro(nome):
    return type(nome, (Exception,), {})("detalhe em inglês")


@pytest.mark.parametrize("nome,sem_legenda", [
    ("TranscriptsDisabled", True), ("NoTranscriptFound", True), ("StopIteration", True),
    ("VideoUnavailable", False), ("AgeRestricted", False), ("IpBlocked", False), ("RequestBlocked", False),
])
def test_cada_falha_do_youtube_tem_explicacao(nome, sem_legenda):
    mensagem, e_falta = ty.explicar_falha(_erro(nome))
    assert e_falta is sem_legenda and "detalhe em inglês" not in mensagem


def test_falha_desconhecida_ainda_diz_o_que_foi():
    mensagem, e_falta = ty.explicar_falha(_erro("AlgoNovo"))
    assert "AlgoNovo" in mensagem and not e_falta
