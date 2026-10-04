"""
Entrega do Radar por e-mail.

Três travas, porque isto é a única parte do sistema que fala com o mundo em nome do cliente:

1. **Só Radar aprovado sai.** Rascunho e descartado são recusados. A revisão humana não é opcional.
2. **A senha nunca entra no repositório.** Toda a configuração vem de variáveis de ambiente.
3. **Dá para simular.** `montar_email` monta a mensagem sem rede nenhuma, e a linha de comando tem
   `--simular-envio`, que mostra exatamente o que sairia sem enviar nada.

O corpo é curto: os destaques que foram revisados e aprovados, congelados no momento da geração. O Radar
completo vai anexado como HTML, que o cliente abre no navegador e imprime em PDF. Não mando o HTML no corpo
porque cliente de e-mail corta CSS de cabeçalho, e o relatório chegaria torto.
"""
import json
import os
import smtplib
from email.message import EmailMessage
from html import escape
from pathlib import Path

VARIAVEIS = {"servidor": "RADAR_SMTP_HOST", "porta": "RADAR_SMTP_PORTA", "usuario": "RADAR_SMTP_USUARIO",
             "senha": "RADAR_SMTP_SENHA", "remetente": "RADAR_REMETENTE"}
PORTA_PADRAO = 587


class ConfiguracaoIncompleta(RuntimeError):
    """Falta alguma variável de ambiente do envio; a mensagem diz qual."""


class NaoAprovado(RuntimeError):
    """Tentativa de enviar um Radar que não passou pela revisão."""


def configuracao(ambiente=None) -> dict:
    ambiente = os.environ if ambiente is None else ambiente
    faltando = [nome for chave, nome in VARIAVEIS.items()
                if chave not in ("porta", "remetente") and not ambiente.get(nome, "").strip()]
    if faltando:
        raise ConfiguracaoIncompleta(
            "faltam variáveis de ambiente para enviar: " + ", ".join(faltando) +
            ". Defina-as no seu terminal (nunca no repositório). Para o Gmail, use uma senha de aplicativo."
        )
    usuario = ambiente[VARIAVEIS["usuario"]].strip()
    return {
        "servidor": ambiente[VARIAVEIS["servidor"]].strip(),
        "porta": int(ambiente.get(VARIAVEIS["porta"], "").strip() or PORTA_PADRAO),
        "usuario": usuario,
        "senha": ambiente[VARIAVEIS["senha"]],
        "remetente": ambiente.get(VARIAVEIS["remetente"], "").strip() or usuario,
    }


def _periodo(registro: dict) -> str:
    def br(iso):
        partes = (iso or "")[:10].split("-")
        return "/".join(reversed(partes)) if len(partes) == 3 else (iso or "")

    return f"{br(registro['periodo_de'])} a {br(registro['periodo_ate'])}"


def assunto(registro: dict, cliente_nome: str) -> str:
    return f"Radar {cliente_nome} · {_periodo(registro)}"


def corpo(registro: dict, cliente_nome: str) -> tuple:
    """Devolve (texto_simples, html). Usa o resumo congelado na geração, não uma nova leitura da base."""
    try:
        destaques = json.loads(registro.get("resumo") or "[]")
    except json.JSONDecodeError:
        destaques = []

    abertura = f"Radar de {cliente_nome}, período de {_periodo(registro)}."
    if destaques:
        miolo_texto = "\n".join(f"- {d['texto']}" for d in destaques)
        itens = []
        for destaque in destaques:
            origem = " · ".join(p for p in (destaque.get("data", "")[:10], destaque.get("fonte", "")) if p)
            rodape = f'<br><span style="color:#6b7480;font-size:13px">{escape(origem)}</span>' if origem else ""
            itens.append(f'<li style="margin:8px 0">{escape(destaque["texto"])}{rodape}</li>')
        miolo_html = f'<p><strong>O que mudou:</strong></p><ul>{"".join(itens)}</ul>'
    else:
        miolo_texto = "Sem novidade no período: não encontramos notícia nova nem mudança de cardápio."
        miolo_html = ("<p><strong>Semana sem novidade.</strong> Não encontramos notícia nova nem mudança de "
                      "cardápio no período. Isto também é informação.</p>")

    fecho = "O Radar completo, com todas as fontes e links, está no arquivo em anexo."
    texto = f"{abertura}\n\n{miolo_texto}\n\n{fecho}\n"
    html = (f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
            f'font-size:15px;line-height:1.55;color:#1c2024;max-width:620px">'
            f"<p>{escape(abertura)}</p>{miolo_html}<p>{escape(fecho)}</p></div>")
    return texto, html


def montar_email(registro: dict, cliente_nome: str, destinatario: str, remetente: str) -> EmailMessage:
    """Monta a mensagem inteira, com o HTML do Radar anexado. Não toca na rede."""
    if not destinatario.strip():
        raise ValueError("o cliente não tem e-mail no cadastro; preencha o campo 'email' em monitorados.json")
    texto, html = corpo(registro, cliente_nome)
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto(registro, cliente_nome)
    mensagem["From"] = remetente
    mensagem["To"] = destinatario.strip()
    mensagem.set_content(texto)
    mensagem.add_alternative(html, subtype="html")

    caminho = Path(registro.get("arquivo") or "")
    if caminho.is_file():
        mensagem.add_attachment(caminho.read_bytes(), maintype="text", subtype="html", filename=caminho.name)
    return mensagem


def enviar(mensagem: EmailMessage, config: dict, conectar=None) -> None:
    """`conectar` é injetável para testar sem rede; por padrão abre SMTP com STARTTLS."""
    if conectar is None:
        def conectar(servidor, porta):
            smtp = smtplib.SMTP(servidor, porta, timeout=30)
            smtp.starttls()
            return smtp

    smtp = conectar(config["servidor"], config["porta"])
    try:
        smtp.login(config["usuario"], config["senha"])
        smtp.send_message(mensagem)
    finally:
        try:
            smtp.quit()
        except Exception:                      # servidor que já fechou não pode mascarar o erro real do envio
            pass


def preparar(registro: dict, cliente, remetente: str) -> EmailMessage:
    """Valida o estado e devolve a mensagem pronta. Levanta NaoAprovado se a revisão não passou."""
    if registro["estado"] != "aprovado":
        raise NaoAprovado(
            f"o Radar #{registro['id']} está como '{registro['estado']}'. Só Radar aprovado é enviado: "
            "confira o conteúdo e rode --aprovar antes."
        )
    return montar_email(registro, cliente.nome, cliente.email, remetente)
