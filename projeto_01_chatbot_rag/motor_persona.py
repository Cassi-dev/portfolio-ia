"""
Motor de Persona RAG: Recupera conversas anteriores com base vetorial e gera
respostas incorporando o vocabulário, ritmo e raciocínio do autor.
"""
import os
import json
import logging
import hashlib
from pathlib import Path
import chromadb

from core import llm
from core.config import MODELO_GEMINI
from core.embeddings import EmbeddingFunctionMultilingue
from core.llm import FalhaLLM, criar_cliente, gerar_estruturado, gerar_texto
from pydantic import BaseModel
from ingestao_whatsapp import ParConversa, analisar_estilo_escrita
from persona_config import carregar_config_privada

BASE_DIR = Path(__file__).resolve().parent
PASTA_BANCO = BASE_DIR / "banco_vetorial"
ARQUIVO_ESTILO = BASE_DIR / "perfil_estilo_persona.json"
NOME_COLECAO_PERSONA = os.getenv("PERSONA_COLECAO", "persona_digital")
log = logging.getLogger("motor_persona")


class RespostaFoco(BaseModel):
    entendimento: str
    deve_responder: bool
    resposta: str
    precisa_acao: bool
    resumo_pendencia: str
    encerrar_conversa: bool


class ResumoContato(BaseModel):
    nome: str
    resumo: str
    pendencias: list[str]
    urgencia: str
    percebeu_ia: bool
    sugestao_resposta: str


class ResumoFoco(BaseModel):
    contatos: list[ResumoContato]


def obter_colecao_persona(pasta_banco=None):
    caminho = str(pasta_banco or PASTA_BANCO)
    cliente = chromadb.PersistentClient(path=caminho)
    return cliente.get_or_create_collection(
        name=NOME_COLECAO_PERSONA,
        embedding_function=EmbeddingFunctionMultilingue(),
        metadata={"hnsw:space": "cosine"}
    )


def salvar_perfil_estilo(perfil: dict, caminho=None):
    alvo = Path(caminho or ARQUIVO_ESTILO)
    alvo.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_perfil_estilo(caminho=None) -> dict:
    alvo = Path(caminho or ARQUIVO_ESTILO)
    if alvo.exists():
        try:
            return json.loads(alvo.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "nome": "Usuário",
        "media_palavras": 12,
        "media_chars": 65,
        "usa_pontuacao_final_pct": 35.0,
        "usa_maiuscula_inicial_pct": 50.0,
        "termos_frequentes": ["show", "faz sentido", "vamos ver", "fechou", "top"],
        "emojis_frequentes": ["👍", "🔥", "🚀", "👊"],
        "diretrizes_pensamento": [
            "Responde de forma direta, clara e sem enrolação.",
            "Usa tom profissional porém descontraído e próximo, típico de WhatsApp de trabalho/parceria.",
            "Não usa introduções robóticas como 'Olá! Como posso ajudar você hoje?' nem encerramentos corporativos.",
            "Pensa sempre em viabilidade prática, tecnologia e eficiência.",
            "Usa o nome da pessoa naturalmente na conversa — não deve ser obrigatório, mas quando faz sentido, usa.",
            "Retoma o que a pessoa acabou de falar — referencia a mensagem anterior, o contexto recente.",
            "Cada resposta é uma continuação da conversa, não uma resposta isolada. Mantém coerência com o que foi dito antes."
        ]
    }


class MotorPersona:
    def __init__(self, colecao=None, perfil=None, config_privada: dict | None = None):
        self.colecao = colecao or obter_colecao_persona()
        self.perfil = perfil or carregar_perfil_estilo()
        self.config_privada = config_privada

    def _obter_config_privada(self) -> dict:
        if self.config_privada is not None:
            return self.config_privada
        return carregar_config_privada()

    def indexar_pares(self, pares: list[ParConversa], atualizar_estilo: bool = True) -> int:
        """
        Salva pares de conversa no ChromaDB gerando IDs determinísticos.

        atualizar_estilo=False para lotes pequenos (uma correção, as mensagens
        novas desde a última sincronização): as médias do perfil são
        *substituídas* pelas do lote, e um lote de 1 resposta viraria a "média"
        de palavras da persona inteira.
        """
        if not pares:
            return 0
        docs, metas, ids = [], [], []
        respostas_usuario = []

        cfg = self._obter_config_privada()
        sensiveis = set(cfg.get("contatos_intimos", []) + cfg.get("termos_sensiveis", []))

        for p in pares:
            texto_doc = f"Mensagem recebida: {p.pergunta}\nResposta de {p.autor_resposta}: {p.resposta}"
            doc_id = hashlib.sha1(f"{p.pergunta}\x1f{p.resposta}".encode("utf-8")).hexdigest()[:20]
            docs.append(texto_doc)
            eh_sensivel = getattr(p, "sensivel", False) or (any(c in p.interlocutor.lower() for c in sensiveis) if sensiveis else False)
            metas.append({
                "pergunta": p.pergunta[:1000],
                "resposta": p.resposta[:1500],
                "interlocutor": p.interlocutor,
                "autor": p.autor_resposta,
                "tipo": "par_conversa",
                "sensivel": int(eh_sensivel)
            })
            ids.append(doc_id)
            respostas_usuario.append(p.resposta)

        self.colecao.upsert(documents=docs, metadatas=metas, ids=ids)

        if atualizar_estilo:
            self.atualizar_perfil_estilo(respostas_usuario)
        return len(ids)

    def atualizar_perfil_estilo(self, respostas_usuario: list[str]):
        """Recalcula as métricas de estilo a partir das respostas informadas."""
        analise = analisar_estilo_escrita(respostas_usuario)
        if analise["total_mensagens"] > 0:
            self.perfil.update({
                "media_palavras": analise["media_palavras"],
                "media_chars": analise["media_chars"],
                "termos_frequentes": list(set(self.perfil.get("termos_frequentes", []) + analise["termos_frequentes"]))[:15],
                "emojis_frequentes": list(set(self.perfil.get("emojis_frequentes", []) + analise["emojis_frequentes"]))[:8],
            })
            salvar_perfil_estilo(self.perfil)

    def buscar_exemplos_estilo(self, mensagem_recebida: str, k: int = 4, remetente: str = "",
                               where: dict | None = None) -> list[dict]:
        """
        Recupera as situações e respostas mais parecidas do histórico real.

        ESTRATÉGIA PER-CONTACT:
        1. Busca exemplos com o MESMO contato (same-contact tone)
        2. Se poucos, complementa com genéricos
        3. Prioriza: contato_mesmo + rating 👍 + distância

        Aplica filtro rígido para isolar conversas íntimas/confidenciais
        garantindo que assuntos pessoais nunca sejam expostos como referências para terceiros.
        """
        if self.colecao.count() == 0:
            return []
        try:
            consulta_base = dict(
                query_texts=[mensagem_recebida],
                n_results=min(k * 4, self.colecao.count()),
                include=["documents", "metadatas", "distances"]
            )
            if where:
                consulta_base["where"] = where

            resultados = self.colecao.query(**consulta_base)
            exemplos = []

            cfg = self._obter_config_privada()
            contatos_intimos = cfg.get("contatos_intimos", [])
            termos_sensiveis = cfg.get("termos_sensiveis", [])
            sensiveis = set(contatos_intimos + termos_sensiveis)

            eh_contato_intimo = any(c in remetente.lower() for c in contatos_intimos) if contatos_intimos else False

            # Processa candidatos com score de prioridade
            candidatos_mesmo_contato = []
            candidatos_generico = []

            if resultados and resultados.get("metadatas") and resultados["metadatas"][0]:
                for meta, dist, doc in zip(resultados["metadatas"][0], resultados["distances"][0], resultados["documents"][0]):
                    interlocutor = meta.get("interlocutor", "")
                    eh_sensivel = bool(meta.get("sensivel", False)) or (any(c in interlocutor.lower() for c in sensiveis) if sensiveis else False)

                    # Se o interlocutor da mensagem não for íntimo, descarta qualquer diálogo íntimo/familiar
                    if not eh_contato_intimo and eh_sensivel:
                        continue

                    # Filtro textual: se o exemplo menciona termos confidenciais ou desabafos, pula para evitar vazamento
                    texto_completo = f"{meta.get('pergunta', '')} {meta.get('resposta', '')}".lower()
                    if not eh_contato_intimo and termos_sensiveis and any(c in texto_completo for c in termos_sensiveis):
                        continue

                    # Rating: 1 = bom, None = neutro, -1 = ruim
                    rating = meta.get("rating")
                    prioridade_rating = 0 if rating == 1 else (1 if rating is None else 2)

                    candidato = (prioridade_rating, dist, {
                        "pergunta": meta.get("pergunta", ""),
                        "resposta": meta.get("resposta", ""),
                        "interlocutor": interlocutor,
                        "distancia": float(dist),
                        "documento": doc,
                        "rating": rating
                    })

                    # Classifica por contato
                    eh_mesmo_contato = any(c in interlocutor.lower() for c in remetente.lower().split())
                    if eh_mesmo_contato and remetente:
                        candidatos_mesmo_contato.append(candidato)
                    else:
                        candidatos_generico.append(candidato)

            # Ordena ambas listas por (rating, distancia)
            candidatos_mesmo_contato.sort(key=lambda x: (x[0], x[1]))
            candidatos_generico.sort(key=lambda x: (x[0], x[1]))

            # Prioriza: primeiro os do mesmo contato, depois genéricos
            todos = candidatos_mesmo_contato + candidatos_generico
            exemplos = [c[2] for c in todos[:k]]

            return exemplos
        except Exception:
            return []

    def montar_prompt_persona(self, mensagem: str, historico: list = None, exemplos: list = None) -> str:
        """Constrói o prompt de Few-Shot com o DNA de escrita do usuário."""
        nome = self.perfil.get("nome", "Usuário")
        diretrizes = "\n".join(f"- {d}" for d in self.perfil.get("diretrizes_pensamento", []))
        termos = ", ".join(f'"{t}"' for t in self.perfil.get("termos_frequentes", [])[:8])
        emojis = " ".join(self.perfil.get("emojis_frequentes", [])[:5])
        media_palavras = self.perfil.get("media_palavras", 14)

        bloco_exemplos = ""
        if exemplos:
            linhas_ex = []
            for i, ex in enumerate(exemplos, 1):
                linhas_ex.append(
                    f"[Exemplo Real {i}]\n"
                    f"Alguém disse: \"{ex['pergunta']}\"\n"
                    f"{nome} respondeu: \"{ex['resposta']}\"\n"
                )
            bloco_exemplos = (
                "EXEMPLOS REAIS DE COMO VOCÊ COSTUMA RESPONDER NO WHATSAPP:\n"
                + "\n".join(linhas_ex)
                + "\n---\n"
            )

        bloco_historico = ""
        if historico:
            linhas_hist = []
            for turno in historico[-6:]:
                linhas_hist.append(f"{turno.get('autor', 'Outro')}: {turno.get('texto', '')}")
            bloco_historico = "HISTÓRICO RECENTE DA CONVERSA:\n" + "\n".join(linhas_hist) + "\n\n"

        prompt = f"""Você é {nome} conversando no WhatsApp.
Sua missão é responder à mensagem recebida EXATAMENTE como {nome} pensaria e escreveria.

DNA DE ESTILO E VOZ:
- Média habitual de palavras: cerca de {media_palavras} palavras por mensagem (seja conciso, evite textões desnecessários).
- Expressões e termos que você usa com frequência: {termos}.
- Emojis que você costuma usar (sem exagerar): {emojis}.
- DIRETRIZES DE PENSAMENTO:
{diretrizes}

PROIBIÇÕES CRÍTICAS (ANTI-ROBÔ):
- NUNCA comece com saudações corporativas tipo "Olá! Como posso ajudar você hoje?" ou "Certamente!".
- NUNCA termine com "Espero ter ajudado!" ou "Qualquer dúvida estou à disposição.".
- Fale como uma pessoa real no WhatsApp: direto, natural, humano, resolvendo ou comentando a situação.

{bloco_exemplos}{bloco_historico}NOVA MENSAGEM RECEBIDA PARA RESPONDER:
"{mensagem}"

RESPONDA COMO {nome.upper()} (apenas o texto da mensagem, sem aspas e sem prefixo de nome):"""
        return prompt

    def montar_prompt_foco(self, mensagem: str, remetente: str = "", historico: list = None, exemplos: list = None,
                           mensagens_novas: list = None, respostas_anteriores: list = None) -> str:
        """
        Prompt do Modo Foco: o clone segura a conversa enquanto o usuário está focado.

        Recebe a conversa inteira recente (com quem disse o quê), as mensagens novas a
        responder (a pessoa costuma mandar várias seguidas) e o que o próprio clone já
        respondeu nesta sessão, pra não se repetir.
        """
        nome = self.perfil.get("nome", "Usuário")
        diretrizes = "\n".join(f"- {d}" for d in self.perfil.get("diretrizes_pensamento", []))
        termos = ", ".join(f'"{t}"' for t in self.perfil.get("termos_frequentes", [])[:10])
        emojis = " ".join(self.perfil.get("emojis_frequentes", [])[:6])
        remetente_label = remetente or "um contato"

        bloco_exemplos = ""
        if exemplos:
            linhas_ex = [
                f"[Exemplo {i}{' — com ' + ex['interlocutor'] if ex.get('interlocutor') else ''}]\n"
                f"Disseram: \"{ex['pergunta']}\"\n{nome} respondeu: \"{ex['resposta']}\"\n"
                for i, ex in enumerate(exemplos, 1)
            ]
            bloco_exemplos = (
                "COMO VOCÊ ESCREVE DE VERDADE (exemplos reais; copie o jeito, não o assunto):\n"
                + "\n".join(linhas_ex) + "\n"
            )

        bloco_conversa = ""
        if historico:
            linhas = []
            for t in historico[-20:]:
                if t.get("do_clone"):
                    autor = "Você (clone, neste foco)"
                elif t.get("de_mim"):
                    autor = f"Você ({nome})"
                else:
                    autor = t.get("autor") or remetente_label
                quando = f"[{t['quando']}] " if t.get("quando") else ""
                linhas.append(f"{quando}{autor}: {t.get('texto', '')}")
            bloco_conversa = ("CONVERSA RECENTE COM ESSA PESSOA (mais antiga em cima). "
                              "Use pra entender o assunto e o clima:\n" + "\n".join(linhas) + "\n\n")

        novas = mensagens_novas or [mensagem]
        bloco_novas = "\n".join(f"- {m}" for m in novas)

        bloco_anteriores = ""
        if respostas_anteriores:
            bloco_anteriores = (
                "O QUE VOCÊ JÁ RESPONDEU PRA ESSA PESSOA NESTE FOCO (não repita frase, emoji, "
                "estrutura nem desculpa — a pessoa percebe na hora):\n"
                + "\n".join(f"- \"{r}\"" for r in respostas_anteriores) + "\n\n"
            )
            situacao = "Você já respondeu antes e a conversa continuou. Responda ao que ela disse AGORA."
        else:
            situacao = "É a primeira resposta sua nesta conversa durante o foco."

        return f"""Você é {nome} respondendo no WhatsApp enquanto está concentrado no trabalho (Modo Foco).
Quem escreve: {remetente_label}. {situacao}

PASSO 1 — ENTENDA ANTES DE RESPONDER:
Leia a conversa recente e as mensagens novas. Descubra o que a pessoa quer de fato: pedir algo,
perguntar, avisar, puxar papo, matar saudade, reclamar, reagir ao que você disse. Se a intenção
não estiver clara, responda ao que foi dito literalmente — NÃO adivinhe um pedido específico.

PASSO 2 — DECIDA SE RESPONDE:
- deve_responder=false se a mensagem é só reação ou fechamento ("ok", "tá", "kkk", "👍", "blz")
  ou se nada nela pede resposta.
- Se a pessoa perceber que é automático (fala em IA, robô, bot, "não é você", "resposta pronta")
  ou ficar irritada com as respostas: deve_responder=false e encerrar_conversa=true. Nunca negue
  que é automático e nunca insista.

PASSO 3 — SE RESPONDER:
- Responda ao conteúdo do que ela disse, no tom da conversa (carinho com quem é íntimo, objetivo
  com trabalho, zoeira com amigo). Curto, como nos exemplos.
- Pode dizer que está no meio de um trabalho/foco, mas só se ainda não disse isso — e com outras palavras.
- NUNCA prometa prazo ("já já", "rapidinho", "5 min", "juro", "já fico livre") nem compromisso
  (pagar, mandar, ir, ligar). Quem decide isso é o {nome} depois.
- NUNCA invente fatos, valores, datas, links ou respostas que só o {nome} sabe. Se for algo
  assim, diga com naturalidade que vê com calma depois.

SIGILO: nunca exponha conversas, opiniões ou desabafos com outras pessoas, nem cite familiares
íntimos em conversa com terceiros. Se sondarem fofoca, desvie com leveza.

ESTILO DE {nome.upper()}:
- Termos frequentes: {termos}. Emojis (no máximo 1, e não o mesmo da resposta anterior): {emojis}.
{diretrizes}

{bloco_exemplos}{bloco_conversa}{bloco_anteriores}MENSAGENS NOVAS DE {remetente_label.upper()} (responda a estas, juntas):
{bloco_novas}

Preencha: entendimento (1 frase: o que a pessoa quer/sente agora), deve_responder, resposta
(vazia se não responder), precisa_acao (true se pediu/perguntou algo que o {nome} precisa
resolver depois), resumo_pendencia (1 frase, ou vazio), encerrar_conversa."""


    def gerar_resposta(self, mensagem: str, historico: list = None, client=None, api_key: str = "", remetente: str = "") -> dict:
        """Gera resposta imitando o estilo, devolvendo a resposta e os exemplos de referência usados."""
        exemplos = self.buscar_exemplos_estilo(mensagem, k=4, remetente=remetente)
        prompt = self.montar_prompt_persona(mensagem, historico, exemplos)

        c = client
        chave = api_key.strip() or os.getenv("GEMINI_API_KEY", "")
        if c is None and chave:
            try:
                c = criar_cliente(chave)
            except Exception:
                c = None

        if c is not None:
            try:
                texto_resposta = gerar_texto(c, prompt, temperatura=0.65)
                texto_seguro = self._sanitizar_resposta_segura(texto_resposta.strip().strip('"'), remetente=remetente)
                return {
                    "resposta": texto_seguro,
                    "exemplos_usados": exemplos,
                    "degradado": False,
                    "prompt_utilizado": prompt
                }
            except Exception:
                pass

        # Fallback offline usando o exemplo mais próximo se disponível
        if exemplos:
            resposta_fallback = f"{exemplos[0]['resposta']} (Adaptado do histórico real)"
        else:
            resposta_fallback = "Show, faz sentido! Vamos alinhar e tocar isso."

        return {
            "resposta": resposta_fallback,
            "exemplos_usados": exemplos,
            "degradado": True,
            "prompt_utilizado": prompt
        }

    def _sanitizar_resposta_segura(self, resposta: str, remetente: str = "") -> str:
        """Filtro de segurança pós-geração: evita vazamento acidental de termos confidenciais ou desabafos."""
        import re
        cfg = self._obter_config_privada()
        contatos_intimos = cfg.get("contatos_intimos", [])
        eh_intimo = any(c in remetente.lower() for c in contatos_intimos) if contatos_intimos else False
        if not eh_intimo:
            padroes_bloqueados = cfg.get("padroes_bloqueados", [])
            for p in padroes_bloqueados:
                try:
                    if re.search(p, resposta, re.IGNORECASE):
                        return "Fala cara! To num foco pesado aqui agora. Mais tarde quando sentar no PC a gente troca uma ideia com calma, all good? 👊"
                except re.error as e:
                    log.warning("Padrão regex inválido na config privada (%s): %s", p, e)
        return resposta

    def _cliente_llm(self, client=None, api_key: str = ""):
        if client is not None:
            return client
        chave = api_key.strip() or os.getenv("GEMINI_API_KEY", "")
        if not chave:
            return None
        try:
            return criar_cliente(chave)
        except Exception:
            return None

    def buscar_exemplos_conversa(self, consulta: str, remetente: str = "", k: int = 4) -> list[dict]:
        """
        Exemplos pro Modo Foco: primeiro conversas reais com a MESMA pessoa (é o que dá o tom
        certo — com contatos próximos não se fala como com um cliente), depois o histórico geral.
        """
        exemplos = []
        if remetente:
            exemplos = self.buscar_exemplos_estilo(consulta, k=2, remetente=remetente,
                                                   where={"interlocutor": remetente})
        vistos = {e["documento"] for e in exemplos}
        for e in self.buscar_exemplos_estilo(consulta, k=k, remetente=remetente):
            if len(exemplos) >= k:
                break
            if e["documento"] not in vistos:
                exemplos.append(e)
        return exemplos

    def responder_mensagem_foco(self, mensagem: str, remetente: str = "", historico: list = None, client=None,
                                api_key: str = "", mensagens_novas: list = None,
                                respostas_anteriores: list = None) -> dict:
        """
        Gera a resposta do clone no Modo Foco. Retorna:
          resposta, deve_responder, precisa_acao, resumo_pendencia, encerrar_conversa,
          entendimento, degradado, exemplos_usados
        """
        novas = [m for m in (mensagens_novas or []) if m and m.strip()] or [mensagem]
        # A busca usa as mensagens novas + o fim da conversa: "Credo" sozinho não diz nada,
        # "Credo" depois de "só tô com saudades" diz muito.
        contexto_busca = " ".join([t.get("texto", "") for t in (historico or [])[-5:]] + novas)[-1200:]
        exemplos = self.buscar_exemplos_conversa(contexto_busca, remetente=remetente, k=4)

        # Log de qual tone foi usado (per-contact)
        if exemplos:
            primeiro_ex = exemplos[0]
            mesmo_contato = primeiro_ex.get("interlocutor", "").lower() in remetente.lower() if remetente else False
            marcador = "✓" if mesmo_contato else "○"
            log.info("Tone[%s]: %s %s | rating=%s", remetente or "?", marcador,
                    primeiro_ex.get("interlocutor", "generico")[:20],
                    primeiro_ex.get("rating", "null"))

        prompt = self.montar_prompt_foco(mensagem, remetente, historico, exemplos,
                                         mensagens_novas=novas, respostas_anteriores=respostas_anteriores)

        c = self._cliente_llm(client, api_key)
        if c is not None:
            try:
                dados = gerar_estruturado(c, prompt, RespostaFoco, temperatura=0.7, usar_cache=False)
                resposta = self._sanitizar_resposta_segura(dados.resposta.strip().strip('"'), remetente=remetente)
                deve = bool(dados.deve_responder and resposta)
                return {
                    "resposta": resposta if deve else "",
                    "deve_responder": deve,
                    "precisa_acao": bool(dados.precisa_acao),
                    "resumo_pendencia": dados.resumo_pendencia.strip(),
                    "encerrar_conversa": bool(dados.encerrar_conversa),
                    "entendimento": dados.entendimento.strip(),
                    "degradado": False,
                    "exemplos_usados": exemplos,
                }
            except Exception as e:
                log.warning("Modo Foco: falha ao gerar resposta (%s)", e)

        # Sem IA: só vale como primeira resposta. Repetir a mesma frase pronta numa
        # conversa que continua é exatamente o que denuncia o robô.
        nome_remetente = f" {remetente.split()[0]}" if remetente else ""
        primeira = not respostas_anteriores
        return {
            "resposta": (f"Fala{nome_remetente}! To no meio de um trabalho aqui, "
                         "depois vejo com calma e te respondo." if primeira else ""),
            "deve_responder": primeira,
            "precisa_acao": True,
            "resumo_pendencia": f"Ver mensagem de {remetente or 'contato'}: {' / '.join(novas)[:80]}",
            "encerrar_conversa": False,
            "entendimento": "",
            "degradado": True,
            "exemplos_usados": exemplos,
        }

    def resumir_sessao_foco(self, conversas: list, client=None, api_key: str = "") -> dict:
        """
        Resumo pro usuário ao sair do foco: o que cada pessoa queria, o que ficou pendente e
        uma sugestão de resposta. `conversas` = [{nome, mensagens: [{de: contato|clone, texto, quando}]}]
        """
        conversas = [c for c in (conversas or []) if c.get("mensagens")]
        if not conversas:
            return {"contatos": [], "degradado": False}
        nome = self.perfil.get("nome", "Usuário")

        blocos = []
        for c in conversas:
            linhas = []
            for m in c["mensagens"][-40:]:
                autor = "Clone (respondendo por você)" if m.get("de") == "clone" else c.get("nome", "Contato")
                quando = f"[{m['quando']}] " if m.get("quando") else ""
                linhas.append(f"{quando}{autor}: {m.get('texto', '')}")
            blocos.append(f"### {c.get('nome', 'Contato')}\n" + "\n".join(linhas))

        prompt = f"""Você é o assistente pessoal de {nome}. Ele estava em Modo Foco e um clone automático
respondeu algumas pessoas por ele. Agora ele voltou e precisa saber, rápido, o que aconteceu.

Para CADA pessoa abaixo, preencha:
- nome: exatamente como aparece no título
- resumo: 1 ou 2 frases sobre o que a pessoa queria ou sentia (não descreva o clone, descreva a pessoa)
- pendencias: o que {nome} precisa fazer ou responder (lista vazia se nada)
- urgencia: "alta", "media" ou "baixa"
- percebeu_ia: true se a pessoa notou ou reclamou que a resposta era automática
- sugestao_resposta: uma mensagem curta que {nome} poderia mandar agora, no tom da conversa
  (se percebeu_ia, a sugestão reconhece isso com leveza)

Não invente nada que não esteja nas mensagens.

{chr(10).join(blocos)}"""

        c = self._cliente_llm(client, api_key)
        if c is not None:
            try:
                dados = gerar_estruturado(c, prompt, ResumoFoco, temperatura=0.3, usar_cache=False)
                return {"contatos": [x.model_dump() for x in dados.contatos], "degradado": False}
            except Exception as e:
                log.warning("Modo Foco: falha ao resumir a sessão (%s)", e)
        return {"contatos": [], "degradado": True}

    def gerar_relatorio_tone_por_contato(self) -> dict:
        """
        Analisa exemplos indexados e calcula qual tone/contato tem melhor resultado.

        Retorna: {
          "melhor_contato": "Contato A",
          "taxa_melhor": 0.75,
          "por_contato": {"Contato A": 0.75, "Contato B": 0.50, "generico": 0.60}
        }
        """
        try:
            todos_docs = self.colecao.get(include=["metadatas"])
            if not todos_docs or not todos_docs["metadatas"]:
                return {"melhor_contato": "generico", "por_contato": {}}

            ratings_por_interlocutor = {}
            for meta in todos_docs["metadatas"]:
                if not meta:
                    continue
                rating = meta.get("rating")
                if rating is None:
                    continue
                interlocutor = meta.get("interlocutor", "generico").lower()
                ratings_por_interlocutor.setdefault(interlocutor, []).append(rating)

            # Calcula taxa por contato (1 = aprovado, -1 = rejeitado)
            taxas = {}
            for interlocutor, ratings in ratings_por_interlocutor.items():
                aprovados = sum(1 for r in ratings if r == 1)
                taxa = aprovados / len(ratings) if ratings else 0
                taxas[interlocutor] = round(taxa, 2)

            melhor = max(taxas.items(), key=lambda x: x[1])[0] if taxas else "generico"
            return {
                "melhor_contato": melhor,
                "taxa_melhor": taxas.get(melhor, 0),
                "por_contato": taxas,
                "total_com_feedback": sum(len(r) for r in ratings_por_interlocutor.values())
            }
        except Exception as e:
            log.warning("Erro ao gerar relatorio de tone: %s", e)
            return {"melhor_contato": "generico", "por_contato": {}}

    def aprender_com_feedback(self, feedbacks: list[dict]) -> dict:
        """
        Atualiza metadados dos exemplos no ChromaDB com base em feedback (rating: 1 ou -1).

        feedbacks = [
          {"message_id": "...", "sender_name": "Contato A", "response_text": "...", "rating": 1},
          {"message_id": "...", "sender_name": "Contato B", "response_text": "...", "rating": -1}
        ]

        Retorna: {"atualizados": N, "media_rating": X.X, "por_contato": {...}}
        """
        if not feedbacks:
            return {"atualizados": 0, "media_rating": 0, "por_contato": {}}

        atualizados = 0
        ratings_por_contato = {}
        todos_ratings = []

        for fb in feedbacks:
            rating = fb.get("rating")
            if rating is None or rating not in [1, -1]:
                continue

            message_id = fb.get("message_id", "")
            sender_name = fb.get("sender_name", "?")
            response_text = fb.get("response_text", "")

            # Calcula ID determinístico pra buscar no ChromaDB
            doc_id = hashlib.sha256(response_text.encode()).hexdigest()[:16]

            # Lê metadados atuais
            try:
                docs = self.colecao.get(ids=[doc_id], include=["metadatas"])
                if docs and docs["metadatas"]:
                    meta = docs["metadatas"][0] or {}
                else:
                    meta = {}
            except Exception:
                meta = {}

            # Atualiza rating no metadado
            meta["rating"] = rating
            meta["last_feedback_ts"] = str(int(__import__("time").time()))

            # Atualiza no ChromaDB
            try:
                self.colecao.update(ids=[doc_id], metadatas=[meta])
                atualizados += 1
                todos_ratings.append(rating)
                ratings_por_contato.setdefault(sender_name, []).append(rating)
                log.info("Aprendizado: %s (%s) | rating=%+d", sender_name, message_id[:8], rating)
            except Exception as e:
                log.warning("Aprendizado falhou pra %s: %s", sender_name, e)

        # Calcula estatísticas
        media_rating = sum(todos_ratings) / len(todos_ratings) if todos_ratings else 0
        stats_contato = {}
        for nome, ratings in ratings_por_contato.items():
            media = sum(ratings) / len(ratings)
            stats_contato[nome] = {"media": round(media, 2), "total": len(ratings)}

        return {
            "atualizados": atualizados,
            "media_rating": round(media_rating, 2),
            "por_contato": stats_contato
        }
