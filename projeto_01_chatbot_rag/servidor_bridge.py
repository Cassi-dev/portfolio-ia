"""
Servidor Bridge HTTP para Persona Digital.
Permite integração bidirecional de altíssima velocidade e baixa latência entre o
bot de WhatsApp (Node.js/Baileys) e o motor de RAG/Persona em Python.

Porta padrão: 8506 (PERSONA_BRIDGE_PORT)
Rotas:
- GET  /status           -> Retorna status do serviço, contagem de vetores e saúde
- POST /responder_foco   -> Gera resposta inteligente do clone para o Modo Foco
- POST /resumir_foco     -> Resume, por contato, o que aconteceu durante o foco
- POST /sincronizar      -> Sincroniza mensagens recentes do SQLite para o ChromaDB
                            (também roda sozinho a cada PERSONA_SYNC_MINUTOS, padrão 30)
"""
import json
import logging
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

# Garante importação do motor e dependências do projeto
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR.parent))

from core.embeddings import EmbeddingFunctionMultilingue
from motor_persona import MotorPersona
from loop_aprendizado import sincronizar_banco_wpp_summarizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("persona_bridge")

# 8506, não 8505: o iniciar_apps.bat sobe o "Projeto 5 - Gerador de SQL" na
# 8505, e aí o bridge não conseguia abrir a porta (ou o bot falava com o
# Streamlit). O bot lê o endereço de PERSONA_BRIDGE_URL.
PORTA_BRIDGE = int(os.getenv("PERSONA_BRIDGE_PORT", "8506"))
_inicio_servidor = time.time()
_motor = None


def obter_motor() -> MotorPersona:
    global _motor
    if _motor is None:
        log.info("Inicializando MotorPersona e conexões vetoriais...")
        _motor = MotorPersona()
    return _motor


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class BridgeRequestHandler(BaseHTTPRequestHandler):
    def _enviar_json(self, status_code: int, dados: dict):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(corpo)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status" or self.path == "/health":
            try:
                motor = obter_motor()
                total_docs = motor.colecao.count()
            except Exception as e:
                total_docs = -1

            self._enviar_json(200, {
                "status": "online",
                "servico": "Persona Digital - Bridge WhatsApp",
                "uptime_segundos": round(time.time() - _inicio_servidor, 1),
                "docs_indexados": total_docs,
                "persona": motor.perfil.get("nome", "Usuário")
            })
        elif self.path == "/relatorio_tone":
            try:
                motor = obter_motor()
                relatorio = motor.gerar_relatorio_tone_por_contato()
                self._enviar_json(200, relatorio)
            except Exception as e:
                log.exception("Erro ao gerar relatorio de tone: %s", e)
                self._enviar_json(500, {"erro": str(e)})
        else:
            self._enviar_json(404, {"erro": "Rota não encontrada"})

    def do_POST(self):
        try:
            comprimento = int(self.headers.get("Content-Length", 0))
            dados = self.rfile.read(comprimento) if comprimento > 0 else b"{}"
            try:
                corpo_raw = dados.decode("utf-8")
            except UnicodeDecodeError:
                corpo_raw = dados.decode("latin1", errors="replace")

            try:
                payload = json.loads(corpo_raw) if corpo_raw.strip() else {}
            except Exception:
                self._enviar_json(400, {"erro": "JSON inválido no corpo da requisição"})
                return

            if self.path == "/responder_foco":
                mensagem = (payload.get("mensagem") or "\n".join(payload.get("mensagens_novas") or [])).strip()
                remetente = payload.get("remetente", "").strip()
                historico = payload.get("historico", [])

                if not mensagem:
                    self._enviar_json(400, {"erro": "Campo 'mensagem' é obrigatório"})
                    return

                try:
                    motor = obter_motor()
                    resultado = motor.responder_mensagem_foco(
                        mensagem=mensagem,
                        remetente=remetente,
                        historico=historico,
                        mensagens_novas=payload.get("mensagens_novas") or [],
                        respostas_anteriores=payload.get("respostas_anteriores") or [],
                    )
                    log.info("Foco: %s | responder=%s | encerrar=%s | entendeu: %s",
                             remetente or "?", resultado.get("deve_responder"),
                             resultado.get("encerrar_conversa"), resultado.get("entendimento", "")[:120])
                    self._enviar_json(200, resultado)
                except Exception as e:
                    log.exception("Erro ao processar resposta do modo foco: %s", e)
                    # Fallback seguro
                    self._enviar_json(200, {
                        "resposta": f"Fala {remetente}! Cara, to no meio de um foco pesado aqui agora. Mais tarde quando sentar no PC eu vejo isso com calma e te dou um toque, all good?",
                        "precisa_acao": True,
                        "resumo_pendencia": f"Mensagem de {remetente}: {mensagem[:50]}",
                        "degradado": True,
                        "erro": str(e)
                    })

            elif self.path == "/resumir_foco":
                try:
                    resultado = obter_motor().resumir_sessao_foco(payload.get("conversas") or [])
                    self._enviar_json(200, resultado)
                except Exception as e:
                    log.exception("Erro ao resumir sessão de foco: %s", e)
                    self._enviar_json(200, {"contatos": [], "degradado": True, "erro": str(e)})

            elif self.path == "/sincronizar":
                try:
                    motor = obter_motor()
                    res = sincronizar_banco_wpp_summarizer(motor=motor)
                    self._enviar_json(200, res)
                except Exception as e:
                    log.exception("Erro ao sincronizar banco: %s", e)
                    self._enviar_json(500, {"sucesso": False, "erro": str(e)})

            else:
                self._enviar_json(404, {"erro": "Rota não encontrada"})
        except Exception as err:
            log.exception("Erro inesperado no servidor bridge: %s", err)
            self._enviar_json(500, {"erro": str(err)})

    def log_message(self, format, *args):
        # Redireciona logs para o logger do módulo
        log.info("%s - - [%s] %s", self.client_address[0], self.log_date_time_string(), format % args)


def aquecer_motor(motor: MotorPersona):
    """
    Carrega o modelo de embeddings antes da primeira mensagem. Sem isso, a
    primeira busca levava ~18s (o SentenceTransformer só carrega no primeiro
    uso) e o bot desistia antes, mandando a resposta genérica de fallback.
    """
    inicio = time.time()
    try:
        motor.buscar_exemplos_estilo("aquecimento", k=1)
        log.info("Motor aquecido em %.1fs (%d exemplos na memória)", time.time() - inicio, motor.colecao.count())
    except Exception as e:
        log.warning("Aquecimento falhou (o servidor sobe mesmo assim): %s", e)


def conferir_vetores(motor: MotorPersona):
    """
    Confere se a memória foi gravada com o mesmo modelo que faz a busca.

    Em 2026-09-30 os exemplos estavam todos gravados pelo fallback de hash
    (core/embeddings.py, quando o Windows bloqueia o torch) e a busca rodava
    com o modelo real: nenhum erro, só exemplos aleatórios no prompt. Se isso
    voltar a acontecer, aparece aqui no log em vez de passar despercebido.
    """
    try:
        amostra = motor.colecao.get(limit=5, include=["documents", "embeddings"])
        if not amostra["ids"]:
            return
        recalculados = EmbeddingFunctionMultilingue()(amostra["documents"])
        sims = [sum(a * b for a, b in zip(g, r)) for g, r in zip(amostra["embeddings"], recalculados)]
        media = sum(sims) / len(sims)
        if media < 0.95:
            log.error(
                "MEMÓRIA INCOMPATÍVEL: vetores gravados com outro modelo (similaridade %.2f). "
                "O clone vai usar exemplos aleatórios. Pare o bot e rode reindexar_memoria.py.", media)
        else:
            log.info("Vetores da memória conferidos (similaridade %.2f)", media)
    except Exception as e:
        log.warning("Não consegui conferir os vetores da memória: %s", e)


# 30 min por padrão: mensagem nova só vira exemplo depois que o bot a grava, e
# cada rodada só calcula vetor do que é novo. 0 desliga.
INTERVALO_SYNC_MIN = float(os.getenv("PERSONA_SYNC_MINUTOS", "30"))


def loop_sincronizacao(motor: MotorPersona):
    """O loop de aprendizado: puxa as conversas novas do bot pra memória."""
    while True:
        try:
            res = sincronizar_banco_wpp_summarizer(motor=motor)
            if res.get("sucesso"):
                log.info("Sincronização: %d exemplos novos (memória: %d)",
                         res.get("pares_indexados", 0), res.get("total_memoria", 0))
            else:
                log.warning("Sincronização sem dados: %s", res.get("motivo"))
        except Exception as e:
            log.warning("Sincronização falhou (tenta de novo no próximo ciclo): %s", e)
        time.sleep(INTERVALO_SYNC_MIN * 60)


def iniciar_servidor():
    motor = obter_motor()
    aquecer_motor(motor)
    conferir_vetores(motor)
    if INTERVALO_SYNC_MIN > 0:
        threading.Thread(target=loop_sincronizacao, args=(motor,), daemon=True, name="sync").start()
    servidor = ThreadedHTTPServer(("127.0.0.1", PORTA_BRIDGE), BridgeRequestHandler)
    log.info("Servidor Bridge Persona Digital rodando em http://127.0.0.1:%d", PORTA_BRIDGE)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log.info("Encerrando Servidor Bridge...")
        servidor.server_close()


if __name__ == "__main__":
    iniciar_servidor()
