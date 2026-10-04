import json

import pytest

import entrega
import gerar_radar
import monitorados
from base_eventos import BaseEventos
from monitorados import Alvo, Cadastro, Cliente

DESTAQUES = [
    {"texto": "Boteco Central sofre interdição da vigilância sanitária", "data": "2026-09-19", "fonte": "Portal Local"},
    {"texto": "Cardápio de Boteco Central: 4 subiram de preço", "data": "2026-09-19", "fonte": "cardápio enviado"},
]
AMBIENTE = {"RADAR_SMTP_HOST": "smtp.exemplo.com", "RADAR_SMTP_USUARIO": "eu@exemplo.com",
            "RADAR_SMTP_SENHA": "senha-de-aplicativo"}


def cliente_de_teste(email="dono@restaurante.com"):
    return Cliente(id="bar", nome="Bar do Zé", perfil="negocio", email=email,
                   alvos=[Alvo(id="bar", nome="Bar do Zé", papel="proprio", termos=["Bar do Zé"])])


def registro(estado="aprovado", resumo=DESTAQUES, arquivo=""):
    return {"id": 7, "cliente_id": "bar", "periodo_de": "2026-09-13", "periodo_ate": "2026-09-20",
            "estado": estado, "arquivo": str(arquivo), "itens": 5,
            "resumo": json.dumps(resumo, ensure_ascii=False) if resumo is not None else ""}


class SmtpFalso:
    def __init__(self):
        self.logins, self.enviadas, self.fechado = [], [], False

    def login(self, usuario, senha):
        self.logins.append((usuario, senha))

    def send_message(self, mensagem):
        self.enviadas.append(mensagem)

    def quit(self):
        self.fechado = True


# --- configuração --------------------------------------------------------------------------------------------------

def test_configuracao_diz_exatamente_o_que_falta():
    with pytest.raises(entrega.ConfiguracaoIncompleta) as erro:
        entrega.configuracao({})
    for variavel in ("RADAR_SMTP_HOST", "RADAR_SMTP_USUARIO", "RADAR_SMTP_SENHA"):
        assert variavel in str(erro.value)
    assert "nunca no repositório" in str(erro.value)


def test_configuracao_completa_com_padroes():
    config = entrega.configuracao(AMBIENTE)
    assert config["porta"] == 587 and config["remetente"] == "eu@exemplo.com"
    config = entrega.configuracao({**AMBIENTE, "RADAR_SMTP_PORTA": "465", "RADAR_REMETENTE": "radar@example.com"})
    assert config["porta"] == 465 and config["remetente"] == "radar@example.com"


# --- a mensagem ------------------------------------------------------------------------------------------------------

def test_email_traz_assunto_periodo_destaques_e_as_duas_versoes(tmp_path):
    anexo = tmp_path / "radar_bar_2026-09-20.html"
    anexo.write_text("<!doctype html><p>Radar completo</p>", encoding="utf-8")
    mensagem = entrega.montar_email(registro(arquivo=anexo), "Bar do Zé", "dono@restaurante.com", "radar@example.com")

    assert mensagem["Subject"] == "Radar Bar do Zé · 13/09/2026 a 20/09/2026"
    assert mensagem["To"] == "dono@restaurante.com" and mensagem["From"] == "radar@example.com"
    texto = mensagem.get_body(("plain",)).get_content()
    html = mensagem.get_body(("html",)).get_content()
    assert "interdição da vigilância sanitária" in texto and "4 subiram de preço" in texto
    assert "O que mudou" in html and "Portal Local" in html
    anexos = list(mensagem.iter_attachments())
    assert [a.get_filename() for a in anexos] == ["radar_bar_2026-09-20.html"]
    assert "Radar completo" in anexos[0].get_content()


def test_email_sem_novidade_diz_isso_em_vez_de_vir_vazio():
    mensagem = entrega.montar_email(registro(resumo=[]), "Bar do Zé", "dono@x.com", "radar@example.com")
    assert "Sem novidade no período" in mensagem.get_body(("plain",)).get_content()
    assert "Semana sem novidade" in mensagem.get_body(("html",)).get_content()


def test_resumo_corrompido_nao_derruba_o_email():
    mensagem = entrega.montar_email({**registro(), "resumo": "{isto não é json"}, "Bar", "d@x.com", "r@x.com")
    assert "Sem novidade" in mensagem.get_body(("plain",)).get_content()


def test_destaque_com_marcacao_e_escapado():
    perigoso = [{"texto": "<script>alert(1)</script> promoção", "data": "", "fonte": ""}]
    html = entrega.montar_email(registro(resumo=perigoso), "Bar", "d@x.com", "r@x.com").get_body(("html",)).get_content()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_cliente_sem_email_no_cadastro_e_erro_claro():
    with pytest.raises(ValueError, match="não tem e-mail no cadastro"):
        entrega.montar_email(registro(), "Bar", "  ", "r@x.com")


def test_anexo_ausente_nao_impede_o_email(tmp_path):
    mensagem = entrega.montar_email(registro(arquivo=tmp_path / "sumiu.html"), "Bar", "d@x.com", "r@x.com")
    assert list(mensagem.iter_attachments()) == [] and mensagem["Subject"]


# --- a trava: só aprovado sai --------------------------------------------------------------------------------------

@pytest.mark.parametrize("estado", ["rascunho", "descartado", "enviado"])
def test_radar_nao_aprovado_e_recusado(estado):
    with pytest.raises(entrega.NaoAprovado, match=estado):
        entrega.preparar(registro(estado), cliente_de_teste(), "r@x.com")


def test_radar_aprovado_passa():
    assert entrega.preparar(registro("aprovado"), cliente_de_teste(), "r@x.com")["To"] == "dono@restaurante.com"


# --- envio (sem rede) ------------------------------------------------------------------------------------------------

def test_enviar_faz_login_manda_e_fecha():
    smtp = SmtpFalso()
    mensagem = entrega.montar_email(registro(), "Bar", "d@x.com", "r@x.com")
    entrega.enviar(mensagem, entrega.configuracao(AMBIENTE), conectar=lambda s, p: smtp)
    assert smtp.logins == [("eu@exemplo.com", "senha-de-aplicativo")]
    assert len(smtp.enviadas) == 1 and smtp.fechado


def test_falha_no_envio_sobe_e_ainda_assim_fecha_a_conexao():
    class Quebrado(SmtpFalso):
        def send_message(self, mensagem):
            raise OSError("servidor recusou")

    smtp = Quebrado()
    with pytest.raises(OSError, match="servidor recusou"):
        entrega.enviar(entrega.montar_email(registro(), "B", "d@x.com", "r@x.com"),
                       entrega.configuracao(AMBIENTE), conectar=lambda s, p: smtp)
    assert smtp.fechado


# --- linha de comando --------------------------------------------------------------------------------------------------

@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    for variavel in list(entrega.VARIAVEIS.values()):
        monkeypatch.delenv(variavel, raising=False)
    monitorados.salvar(Cadastro(clientes=[cliente_de_teste()]), tmp_path / "m.json")
    anexo = tmp_path / "radar.html"
    anexo.write_text("<!doctype html><p>completo</p>", encoding="utf-8")
    with BaseEventos(tmp_path / "e.db") as base:
        base.criar_relatorio("bar", "2026-09-13", "2026-09-20", None, 5, str(anexo),
                             json.dumps(DESTAQUES, ensure_ascii=False))
    return {"cadastro": str(tmp_path / "m.json"), "banco": str(tmp_path / "e.db")}


def rodar(ambiente, *extras):
    return gerar_radar.main(["--cadastro", ambiente["cadastro"], "--banco", ambiente["banco"], "--sem-abrir", *extras])


def test_cli_simula_sem_senha_e_sem_rede(ambiente, capsys):
    assert rodar(ambiente, "--simular-envio", "1") == 0
    saida = capsys.readouterr().out
    assert "está como 'rascunho'" in saida and "seria recusado" in saida
    assert "interdição da vigilância sanitária" in saida and "radar.html" in saida
    assert "nada foi enviado" in saida
    assert "De: remetente-ainda-nao-configurado@exemplo.com" in saida       # não pode sair vazio


def test_cli_recusa_enviar_rascunho_mesmo_com_tudo_configurado(ambiente, capsys, monkeypatch):
    for variavel, valor in AMBIENTE.items():
        monkeypatch.setenv(variavel, valor)
    assert rodar(ambiente, "--enviar", "1") == 1
    assert "Só Radar aprovado é enviado" in capsys.readouterr().out


def test_cli_sem_configuracao_nao_tenta_enviar(ambiente, capsys):
    assert rodar(ambiente, "--enviar", "1") == 1
    assert "faltam variáveis de ambiente" in capsys.readouterr().out


def test_cli_envia_aprovado_e_marca_como_enviado(ambiente, capsys, monkeypatch):
    for variavel, valor in AMBIENTE.items():
        monkeypatch.setenv(variavel, valor)
    enviadas = []
    monkeypatch.setattr(entrega, "enviar", lambda mensagem, config, conectar=None: enviadas.append(mensagem))
    with BaseEventos(ambiente["banco"]) as base:
        base.mudar_estado(1, "aprovado")

    assert rodar(ambiente, "--enviar", "1") == 0
    assert "marcado como enviado" in capsys.readouterr().out
    assert len(enviadas) == 1 and enviadas[0]["To"] == "dono@restaurante.com"
    with BaseEventos(ambiente["banco"]) as base:
        registro_final = base.relatorio(1)
    assert registro_final["estado"] == "enviado" and "dono@restaurante.com" in registro_final["notas"]


def test_cli_relatorio_inexistente(ambiente, capsys):
    assert rodar(ambiente, "--simular-envio", "99") == 1
    assert "não existe" in capsys.readouterr().out
