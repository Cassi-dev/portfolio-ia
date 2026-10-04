from datetime import date, timedelta
from pathlib import Path

import pytest

import gerar_radar
import relatorio as rel
from base_eventos import BaseEventos
from cardapio import preco_de
from ciclo import rodar_ciclo
from monitorados import Alvo, Cadastro, Cliente
import monitorados

HOJE = date(2026, 9, 20)


def cliente_de_teste():
    return Cliente(id="bar-do-ze", nome="Bar do Zé", perfil="negocio", gatilhos=["interdicao"], alvos=[
        Alvo(id="bar-do-ze", nome="Bar do Zé", papel="proprio", termos=["Bar do Zé"]),
        Alvo(id="boteco", nome="Boteco Central", papel="concorrente", termos=["Boteco Central"]),
        Alvo(id="setor", nome="Setor", papel="tema", termos=["bares e restaurantes"]),
    ])


@pytest.fixture
def base(tmp_path):
    with BaseEventos(tmp_path / "radar.db") as b:
        yield b


def noticia(titulo, dias=1, fonte="Portal", link="https://exemplo.com/n"):
    return {"titulo": titulo, "data": (HOJE - timedelta(days=dias)).isoformat(), "fonte": fonte, "link": link}


def semear(base, cliente, por_alvo, pontuar_como="gemini"):
    ciclo = base.abrir_ciclo(cliente.id)
    for alvo_id, itens in por_alvo.items():
        base.registrar_eventos(cliente.id, alvo_id, "noticia", itens, ciclo, hoje=HOJE)
    pendentes = base.sem_pontuacao(cliente.id)
    for e in pendentes:
        e.update(score=0.5, classificacao="Otimista", motivo="m", motor=pontuar_como)
    base.gravar_pontuacoes(pendentes)
    base.fechar_ciclo(ciclo, len(pendentes), len(pendentes), len(pendentes))
    return ciclo


def cardapios(base, cliente_id, alvo_id, datas=("2026-09-12", "2026-09-19")):
    import cardapio_ficticio as cf

    verdade = cf.gabarito(cf.SEMANA_1, cf.semana_2())
    preparar = lambda itens: [dict(i, preco=preco_de(i["preco_texto"])) for i in itens]
    for data, chave in zip(datas, ("semana_1", "semana_2")):
        base.guardar_cardapio(cliente_id, alvo_id, data, f"{chave}.jpg",
                              {"estabelecimento": "X", "observacoes": "", "itens": preparar(verdade[chave])})


# --- conteúdo do Radar -------------------------------------------------------------------------------------------

def test_primeiro_radar_cobre_sete_dias_e_se_apresenta_como_primeiro(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Bar do Zé ganha prêmio de melhor petisco")]})
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    assert radar["primeiro"] is True and radar["corte"] is None
    assert radar["periodo_de"] == "2026-09-13" and radar["periodo_ate"] == "2026-09-20"
    assert radar["total_itens"] == 1


def test_secoes_saem_na_ordem_negocio_concorrente_mercado(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("A")], "boteco": [noticia("B")], "setor": [noticia("C")]})
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    assert [s["papel"] for s in radar["secoes"]] == ["proprio", "concorrente", "tema"]
    assert [s["titulo"] for s in radar["secoes"]] == ["O seu negócio", "Concorrentes", "O mercado"]


def test_gatilho_vira_destaque_sem_repetir_o_nome_do_alvo(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"boteco": [noticia("Boteco Central sofre interdição da vigilância sanitária")]})
    destaques = rel.montar_radar(base, cliente, hoje=HOJE)["destaques"]
    assert len(destaques) == 1 and destaques[0]["tipo"] == "gatilho"
    assert destaques[0]["texto"] == "Boteco Central sofre interdição da vigilância sanitária"


def test_gatilho_em_manchete_que_nao_cita_o_alvo_ganha_o_prefixo(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"boteco": [noticia("Casa noturna da região sofre interdição")]})
    assert rel.montar_radar(base, cliente, hoje=HOJE)["destaques"][0]["texto"].startswith("Boteco Central: ")


def test_mudanca_de_cardapio_vira_destaque_e_secao(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"boteco": [noticia("Notícia qualquer do boteco")]})
    cardapios(base, cliente.id, "boteco")
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    destaque = next(d for d in radar["destaques"] if d["tipo"] == "cardapio")
    assert "4 subiram de preço" in destaque["texto"] and "1 baixaram" in destaque["texto"]
    concorrente = next(s for s in radar["secoes"] if s["papel"] == "concorrente")["alvos"][0]
    assert concorrente["cardapio"] is not None and len(concorrente["cardapio"]["subiram"]) == 4


def test_cardapio_sem_mudanca_nao_ocupa_espaco(base):
    cliente = cliente_de_teste()
    cardapios(base, cliente.id, "boteco", datas=("2026-09-12", "2026-09-19"))
    base.conn.execute("DELETE FROM itens_cardapio WHERE captura_id = 2")
    base.conn.execute("INSERT INTO itens_cardapio (captura_id, nome, chave, preco, preco_texto, categoria, descricao)"
                      " SELECT 2, nome, chave, preco, preco_texto, categoria, descricao FROM itens_cardapio WHERE captura_id = 1")
    base.conn.commit()
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    assert all(a["cardapio"] is None for s in radar["secoes"] for a in s["alvos"])
    assert not [d for d in radar["destaques"] if d["tipo"] == "cardapio"]


def test_sem_nada_novo_o_radar_diz_isso(base):
    radar = rel.montar_radar(base, cliente_de_teste(), hoje=HOJE)
    assert rel.sem_novidade(radar) is True
    assert "Semana sem novidade" in rel.renderizar_html(radar)


def test_tom_do_lexico_nao_aparece_como_se_fosse_analise(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Bar do Zé lança cardápio")]}, pontuar_como="lexico")
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    item = radar["secoes"][0]["alvos"][0]["novidades"][0]
    assert item["classificacao"] is None and item["score"] is None
    assert any("lista de palavras" in a for a in radar["avisos"])


# --- período: nada repetido, nada perdido ---------------------------------------------------------------------------

def test_o_segundo_radar_nao_repete_o_que_ja_foi_entregue(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Primeira notícia sobre o bar")]})
    primeiro = rel.montar_radar(base, cliente, hoje=HOJE)
    identificador = base.criar_relatorio(cliente.id, primeiro["periodo_de"], primeiro["periodo_ate"],
                                         primeiro["corte"], primeiro["total_itens"])
    base.mudar_estado(identificador, "enviado")

    semear(base, cliente, {"bar-do-ze": [noticia("Segunda notícia, bem diferente da anterior")]})
    segundo = rel.montar_radar(base, cliente, hoje=HOJE)
    assert segundo["primeiro"] is False and segundo["total_itens"] == 1
    assert "Segunda notícia" in segundo["secoes"][0]["alvos"][0]["novidades"][0]["titulo"]


def test_rascunho_descartado_nao_engole_a_semana(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Notícia que estava no rascunho descartado")]})
    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    identificador = base.criar_relatorio(cliente.id, radar["periodo_de"], radar["periodo_ate"], radar["corte"], 1)
    base.mudar_estado(identificador, "descartado")
    assert base.corte_do_proximo_relatorio(cliente.id) is None
    assert rel.montar_radar(base, cliente, hoje=HOJE)["total_itens"] == 1


# --- exclusão na revisão ---------------------------------------------------------------------------------------------

def test_item_excluido_some_do_radar_e_dos_detectores(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"boteco": [noticia("Boteco Central sofre interdição da vigilância sanitária"),
                                      noticia("Outra notícia qualquer que fica")]})
    ruim = next(e for e in base.eventos(cliente.id) if "interdição" in e["titulo"])
    assert base.excluir_eventos([ruim["id"]], "ruído") == 1

    radar = rel.montar_radar(base, cliente, hoje=HOJE)
    assert radar["total_itens"] == 1 and radar["destaques"] == []
    assert all("interdição" not in i["titulo"] for s in radar["secoes"] for a in s["alvos"] for i in a["novidades"])


def test_excluido_nao_volta_na_coleta_nem_gasta_ia(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"boteco": [noticia("Manchete de teste para excluir depois")]})
    alvo = base.eventos(cliente.id)[0]
    base.excluir_eventos([alvo["id"]])
    segundo = rodar_ciclo(cliente, base, coletor=lambda a, d: [noticia("Manchete de teste para excluir depois")]
                          if a.id == "boteco" else [], hoje=HOJE)
    assert segundo["novos"] == 0 and segundo["pontuados"] == 0
    assert base.sem_pontuacao(cliente.id) == []


def test_restaurar_traz_o_item_de_volta(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Manchete que volta atrás")]})
    alvo = base.eventos(cliente.id)[0]
    base.excluir_eventos([alvo["id"]])
    assert rel.montar_radar(base, cliente, hoje=HOJE)["total_itens"] == 0
    base.restaurar_eventos([alvo["id"]])
    assert rel.montar_radar(base, cliente, hoje=HOJE)["total_itens"] == 1


# --- estados do relatório ----------------------------------------------------------------------------------------------

def test_estados_e_historico(base):
    identificador = base.criar_relatorio("cli", "2026-09-13", "2026-09-20", None, 5, "x.html")
    assert base.relatorios("cli")[0]["estado"] == "rascunho"
    base.mudar_estado(identificador, "aprovado", "conferido por mim")
    registro = base.relatorios("cli")[0]
    assert registro["estado"] == "aprovado" and registro["notas"] == "conferido por mim"
    assert base.relatorios("cli", estado="rascunho") == []


def test_estado_invalido_e_recusado(base):
    identificador = base.criar_relatorio("cli", "a", "b", None, 0)
    with pytest.raises(ValueError, match="estado inválido"):
        base.mudar_estado(identificador, "publicado")


# --- HTML ----------------------------------------------------------------------------------------------------------------

def radar_completo(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("Bar do Zé ganha prêmio")],
                           "boteco": [noticia("Boteco Central sofre interdição da vigilância sanitária")]})
    cardapios(base, cliente.id, "boteco")
    return rel.montar_radar(base, cliente, hoje=HOJE)


def test_html_traz_titulo_periodo_fonte_data_e_link(base):
    html = rel.renderizar_html(radar_completo(base))
    assert "<!doctype html>" in html and "Radar · Bar do Zé" in html
    assert "13/09/2026 a 20/09/2026" in html and "Jornal" not in html
    assert 'href="https://exemplo.com/n"' in html and "Portal" in html
    assert "O que mudou" in html and "O seu negócio" in html and "Concorrentes" in html


def test_html_mostra_preco_em_formato_brasileiro(base):
    html = rel.renderizar_html(radar_completo(base))
    assert "R$ 12,00" in html and "R$ 13,50" in html and "R$ 12.00" not in html
    assert "+12.5%" in html or "+12,5%" in html


def test_html_declara_que_nao_foi_escrito_por_ia_e_o_que_nao_cobre(base):
    html = rel.renderizar_html(radar_completo(base))
    assert "Nada aqui é escrito por inteligência artificial" in html
    assert "O que este Radar não cobre" in html and "Avaliações do Google" in html


def test_html_escapa_manchete_com_marcacao(base):
    cliente = cliente_de_teste()
    semear(base, cliente, {"bar-do-ze": [noticia("<script>alert(1)</script> promoção no bar",
                                                 link='https://x.com/a"onmouseover="alert(1)')]})
    html = rel.renderizar_html(rel.montar_radar(base, cliente, hoje=HOJE))
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert 'onmouseover="alert(1)"' not in html


def test_html_e_autocontido(base):
    html = rel.renderizar_html(radar_completo(base))
    assert "<style>" in html and 'rel="stylesheet"' not in html and "<script" not in html
    assert "fonts.googleapis" not in html and "http://" not in html.split("<style>")[0]


def test_salvar_html_usa_cliente_e_data_no_nome(base, tmp_path):
    caminho = rel.salvar_html(radar_completo(base), tmp_path)
    assert caminho.name == "radar_bar-do-ze_2026-09-20.html" and caminho.read_text(encoding="utf-8").startswith("<!doctype")


@pytest.mark.parametrize("iso,esperado", [("2026-09-20", "20/09/2026"), ("2026-09-20T10:30:00+00:00", "20/09/2026"),
                                          ("", ""), (None, "")])
def test_data_em_portugues(iso, esperado):
    assert rel._br(iso) == esperado


# --- linha de comando -----------------------------------------------------------------------------------------------------

@pytest.fixture
def ambiente(tmp_path, base):
    cliente = cliente_de_teste()
    monitorados.salvar(Cadastro(clientes=[cliente]), tmp_path / "m.json")
    semear(base, cliente, {"boteco": [noticia("Boteco Central sofre interdição da vigilância sanitária"),
                                      noticia("Outra manchete diferente sobre o boteco")]})
    base.fechar()
    return {"cadastro": str(tmp_path / "m.json"), "banco": str(tmp_path / "radar.db"), "pasta": str(tmp_path / "out")}


def rodar(ambiente, *extras):
    return gerar_radar.main(["--cadastro", ambiente["cadastro"], "--banco", ambiente["banco"],
                             "--pasta", ambiente["pasta"], "--sem-abrir", *extras])


def test_cli_gera_rascunho_e_grava_o_arquivo(ambiente, capsys):
    assert rodar(ambiente, "--cliente", "bar-do-ze") == 0
    saida = capsys.readouterr().out
    assert "Radar #1" in saida and "2 item(ns)" in saida and "--aprovar 1" in saida
    with BaseEventos(ambiente["banco"]) as b:
        registro = b.relatorios("bar-do-ze")[0]
    assert registro["estado"] == "rascunho" and registro["itens"] == 2
    assert Path(registro["arquivo"]).exists()


def test_cli_lista_itens_com_id_para_a_revisao(ambiente, capsys):
    assert rodar(ambiente, "--cliente", "bar-do-ze", "--itens") == 0
    saida = capsys.readouterr().out
    assert "2 item(ns) entrariam" in saida and "interdição" in saida and "--excluir" in saida


def test_cli_exclui_e_o_item_some_do_radar(ambiente, capsys):
    with BaseEventos(ambiente["banco"]) as b:
        ruim = next(e for e in b.eventos("bar-do-ze") if "interdição" in e["titulo"])
    assert rodar(ambiente, "--cliente", "bar-do-ze", "--excluir", ruim["id"]) == 0
    assert "1 item(ns) excluído(s)" in capsys.readouterr().out
    rodar(ambiente, "--cliente", "bar-do-ze")
    assert "1 item(ns)" in capsys.readouterr().out


def test_cli_aprova_e_o_proximo_radar_nao_repete(ambiente, capsys):
    rodar(ambiente, "--cliente", "bar-do-ze")
    capsys.readouterr()
    assert rodar(ambiente, "--aprovar", "1") == 0
    assert "agora está: aprovado" in capsys.readouterr().out
    rodar(ambiente, "--cliente", "bar-do-ze")
    assert "Sem novidade" in capsys.readouterr().out


def test_cli_descartar_devolve_os_itens(ambiente, capsys):
    rodar(ambiente, "--cliente", "bar-do-ze")
    rodar(ambiente, "--descartar", "1")
    assert "voltam a aparecer" in capsys.readouterr().out
    rodar(ambiente, "--cliente", "bar-do-ze")
    assert "2 item(ns)" in capsys.readouterr().out


def test_cli_historico_e_relatorio_inexistente(ambiente, capsys):
    rodar(ambiente, "--cliente", "bar-do-ze")
    capsys.readouterr()
    assert rodar(ambiente, "--historico") == 0
    assert "rascunho" in capsys.readouterr().out
    assert rodar(ambiente, "--aprovar", "99") == 1
    assert "não existe" in capsys.readouterr().out


def test_cli_cliente_desconhecido(ambiente, capsys):
    assert rodar(ambiente, "--cliente", "fantasma") == 1
    assert "não está no cadastro" in capsys.readouterr().out
