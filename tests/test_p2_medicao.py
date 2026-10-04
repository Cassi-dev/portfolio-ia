import json

import pytest

import medir_monitor
from base_eventos import BaseEventos
from deduplicacao import LIMIAR_EMBEDDING, Deduplicador, escolher
from medicao import PISO_PARA_OPINAR, leitura, medir


@pytest.fixture
def base(tmp_path):
    with BaseEventos(tmp_path / "medicao.db") as b:
        yield b


class SemDeduplicacao:
    """Aqui o assunto é a medição, não a deduplicação: todo título semeado precisa entrar."""

    def e_duplicata(self, titulo, conhecidos):
        return False


def semear(base, titulos, alvo="alvo-a", fonte="Portal"):
    ciclo = base.abrir_ciclo("cli")
    base.registrar_eventos("cli", alvo, "noticia", [
        {"titulo": t, "data": "2026-09-19", "fonte": fonte, "link": "https://x"} for t in titulos
    ], ciclo, hoje=None, deduplicador=SemDeduplicacao())
    base.fechar_ciclo(ciclo, len(titulos), len(titulos), 0)
    return [e["id"] for e in base.eventos("cli", alvo_id=alvo)]


# --- rótulos ---------------------------------------------------------------------------------------------------

def test_descartar_na_revisao_ja_rotula_como_ruido(base):
    ids = semear(base, ["Manchete boa sobre o assunto", "Manchete que é puro ruído aqui"])
    base.excluir_eventos([ids[0]], "publieditorial")
    rotulos = base.rotulos("cli")
    assert len(rotulos) == 1 and rotulos[0]["relevante"] == 0
    assert rotulos[0]["motivo"] == "publieditorial" and rotulos[0]["origem"] == "revisao"


def test_aprovar_um_radar_rotula_o_que_sobrou_como_util(base):
    ids = semear(base, ["Primeira manchete do período", "Segunda manchete bem diferente"])
    base.excluir_eventos([ids[0]])
    relatorio = base.criar_relatorio("cli", "2026-09-13", "2026-09-20", None, 1)
    base.mudar_estado(relatorio, "aprovado")
    rotulos = {r["evento_id"]: r["relevante"] for r in base.rotulos("cli")}
    assert rotulos[ids[0]] == 0 and rotulos[ids[1]] == 1


def test_rotulo_manual_nao_e_apagado_pela_aprovacao(base):
    ids = semear(base, ["Uma manchete qualquer para rotular"])
    base.rotular([(ids[0], 0, "eu decidi que é ruído", "manual")])
    relatorio = base.criar_relatorio("cli", "a", "b", None, 1)
    base.mudar_estado(relatorio, "aprovado")
    rotulo = base.rotulos("cli")[0]
    assert rotulo["relevante"] == 0 and rotulo["origem"] == "manual"


def test_rotular_de_novo_sobrescreve_quando_pedido(base):
    ids = semear(base, ["Manchete para mudar de ideia depois"])
    base.rotular([(ids[0], 1, "útil", "manual")])
    base.rotular([(ids[0], 0, "mudei de ideia", "manual")])
    assert base.rotulos("cli")[0]["relevante"] == 0


def test_sem_rotulo_lista_so_o_que_falta(base):
    ids = semear(base, ["Manchete alfa sobre o tema", "Manchete beta sobre outro ponto"])
    base.rotular([(ids[0], 1, "", "manual")])
    assert [e["id"] for e in base.sem_rotulo("cli")] == [ids[1]]


# --- métricas ---------------------------------------------------------------------------------------------------

def test_sem_rotulo_nenhum_as_metricas_ficam_vazias_e_explicam(base):
    metricas = medir(base, "cli")
    assert metricas["rotulados"] == 0 and metricas["taxa_de_ruido"] is None and metricas["confiavel"] is False
    assert "Nenhum item rotulado" in leitura(metricas)[0]


def test_taxa_de_ruido_e_a_fracao_descartada(base):
    ids = semear(base, [f"Manchete número {n} de assunto bem distinto entre elas" for n in
                        ("alfa", "beta", "gama", "delta")])
    base.rotular([(ids[0], 0, "duplicata", "manual"), (ids[1], 0, "duplicata", "manual"),
                  (ids[2], 1, "util", "manual"), (ids[3], 1, "util", "manual")])
    metricas = medir(base, "cli")
    assert metricas["rotulados"] == 4 and metricas["ruido"] == 2 and metricas["taxa_de_ruido"] == 0.5
    assert metricas["cobertura_da_rotulagem"] == 1.0


def test_poucos_rotulos_nao_autorizam_opinar(base):
    ids = semear(base, ["Uma única manchete rotulada sozinha"])
    base.rotular([(ids[0], 0, "ruído", "manual")])
    metricas = medir(base, "cli")
    assert metricas["confiavel"] is False and metricas["piso_para_opinar"] == PISO_PARA_OPINAR
    assert any("pouco para uma taxa" in l for l in leitura(metricas))


def test_metricas_separam_por_alvo_fonte_e_motivo(base):
    bons = semear(base, ["Manchete útil do alvo bom para o cliente"], alvo="bom", fonte="Boa Fonte")
    ruins = semear(base, [f"Manchete de assunto {n} vinda do portal ruim" for n in ("alfa", "beta")],
                   alvo="ruim", fonte="Fonte Ruim")
    base.rotular([(bons[0], 1, "util", "manual"), (ruins[0], 0, "duplicata", "manual"),
                  (ruins[1], 0, "publieditorial", "manual")])
    metricas = medir(base, "cli")
    por_alvo = {a["alvo_id"]: a["taxa_de_ruido"] for a in metricas["por_alvo"]}
    assert por_alvo == {"ruim": 1.0, "bom": 0.0}
    assert metricas["por_fonte"][0]["fonte"] == "Fonte Ruim" and metricas["por_fonte"][0]["ruido"] == 2
    assert [m["motivo"] for m in metricas["por_motivo"]] == ["duplicata", "publieditorial"]
    assert metricas["por_motivo"][0]["fatia_do_ruido"] == 0.5


def test_leitura_aponta_o_motivo_dominante_e_o_alvo_barulhento(base):
    ids = semear(base, [f"Manchete de assunto {n} para compor a amostra" for n in
                        ("a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l")], alvo="barulhento")
    base.rotular([(i, 0, "duplicata", "manual") for i in ids[:8]] + [(i, 1, "util", "manual") for i in ids[8:]])
    texto = " ".join(leitura(medir(base, "cli")))
    assert "duplicata" in texto and "barulhento" in texto
    assert "não cobertura" in texto                       # o aviso de que recall não dá para medir


# --- deduplicação ------------------------------------------------------------------------------------------------

def test_modo_invalido_e_recusado():
    with pytest.raises(ValueError, match="modo de deduplicação inválido"):
        Deduplicador("magica")


def test_por_tokens_pega_titulo_quase_igual_e_ignora_assunto_diferente():
    dedup = Deduplicador("tokens")
    conhecidos = ["Petrobras anuncia dividendos extraordinários bilhões"]
    assert dedup.e_duplicata("Petrobras anuncia dividendos extraordinários bilhões hoje", conhecidos)
    assert not dedup.e_duplicata("Vale amplia produção de minério no trimestre", conhecidos)
    assert not dedup.e_duplicata("qualquer coisa", [])


def test_escolher_cai_para_tokens_quando_nao_ha_modelo(monkeypatch):
    import deduplicacao

    monkeypatch.setattr(deduplicacao, "_modelo_disponivel", lambda: False)
    assert escolher("embedding").modo == "tokens"


def test_limiar_padrao_por_modo():
    assert Deduplicador("tokens").limiar == 0.60
    assert Deduplicador("tokens", 0.4).limiar == 0.4


@pytest.mark.network
def test_por_embedding_reconhece_a_mesma_noticia_reescrita():
    """O caso real que motivou a troca: cinco portais, cinco títulos, uma história só."""
    dedup = Deduplicador("embedding")
    assert dedup.limiar == LIMIAR_EMBEDDING
    original = ["Mulher encontra aparelho dentário em prato do Outback"]
    assert dedup.e_duplicata("Cliente relata ter encontrado aparelho dentário em prato do Outback em SP", original)
    assert not dedup.e_duplicata("Outback cria clube com benefícios personalizados para clientes", original)


@pytest.mark.network
def test_base_usa_o_deduplicador_que_receber(base):
    dedup = Deduplicador("embedding")
    ciclo = base.abrir_ciclo("cli")
    itens = [{"titulo": "Mulher encontra aparelho dentário em prato do Outback", "data": "2026-09-19"},
             {"titulo": "Cliente relata ter encontrado aparelho dentário em prato do Outback em SP", "data": "2026-09-19"}]
    novos = base.registrar_eventos("cli", "a", "noticia", itens, ciclo, deduplicador=dedup)
    assert len(novos) == 1


# --- linha de comando ----------------------------------------------------------------------------------------------

def test_cli_exporta_importa_e_mede(tmp_path, base, capsys):
    ids = semear(base, ["Manchete alfa que vale mostrar", "Manchete beta que é só ruído aqui"])
    base.fechar()
    banco = str(tmp_path / "medicao.db")
    arquivo = tmp_path / "rotular.json"

    assert medir_monitor.main(["--banco", banco, "--cliente", "cli", "--exportar", str(arquivo)]) == 0
    conteudo = json.loads(arquivo.read_text(encoding="utf-8"))
    assert len(conteudo) == 2 and all(i["relevante"] is None for i in conteudo)

    conteudo[0]["relevante"], conteudo[0]["motivo"] = 1, "util"
    conteudo[1]["relevante"], conteudo[1]["motivo"] = 0, "duplicata"
    arquivo.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    assert medir_monitor.main(["--banco", banco, "--importar", str(arquivo)]) == 0
    assert "2 rótulo(s) gravado(s)" in capsys.readouterr().out

    assert medir_monitor.main(["--banco", banco, "--cliente", "cli"]) == 0
    saida = capsys.readouterr().out
    assert "TAXA DE RUÍDO: 50.0%" in saida and "duplicata" in saida
    assert ids                                                # os mesmos eventos semeados


def test_cli_ignora_linha_sem_relevante_preenchido(tmp_path, base, capsys):
    semear(base, ["Manchete que fica sem rótulo mesmo"])
    base.fechar()
    arquivo = tmp_path / "meio.json"
    arquivo.write_text(json.dumps([{"id": "x", "relevante": None}]), encoding="utf-8")
    assert medir_monitor.main(["--banco", str(tmp_path / "medicao.db"), "--importar", str(arquivo)]) == 0
    assert "1 sem 'relevante' preenchido" in capsys.readouterr().out


def test_cli_arquivo_ilegivel_avisa(tmp_path, capsys):
    ruim = tmp_path / "ruim.json"
    ruim.write_text("{isto não é json", encoding="utf-8")
    assert medir_monitor.main(["--banco", str(tmp_path / "m.db"), "--importar", str(ruim)]) == 1
    assert "não consegui ler" in capsys.readouterr().out


def test_cli_exportar_exige_cliente(tmp_path):
    with pytest.raises(SystemExit):
        medir_monitor.main(["--banco", str(tmp_path / "m.db"), "--exportar", str(tmp_path / "x.json")])
