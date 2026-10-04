import json
import pytest
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "projeto_01_chatbot_rag"))

import ingestao_whatsapp as iw
import motor_persona as mp
import loop_aprendizado as la
import persona_config as pc


@pytest.fixture(autouse=True)
def config_privada_teste(tmp_path):
    """Garante que nenhum teste leia a config privada real da máquina."""
    cfg_teste = {
        "contatos_intimos": ["contato_intimo_teste"],
        "termos_sensiveis": ["termo_sensivel_teste"],
        "padroes_bloqueados": [r"\bbloqueado_teste\b"]
    }
    arquivo_cfg = tmp_path / "persona_privado.json"
    arquivo_cfg.write_text(json.dumps(cfg_teste), encoding="utf-8")
    pc.definir_caminho_config_privada(arquivo_cfg)
    yield arquivo_cfg
    pc.definir_caminho_config_privada(None)


CONVERSA_TESTE_IOS = """
[14/08/2026, 10:14:02] Contato Teste: E aí Usuário Teste, beleza? Conseguiu ver aquele projeto de IA?
[14/08/2026, 10:15:10] Usuário Teste: Fala Contato! Cara, vi sim.
[14/08/2026, 10:15:45] Usuário Teste: Tá show de bola, já integrei com o banco vetorial e tá respondendo rápido.
[14/08/2026, 10:16:00] Contato Teste: Que top! E como ficou o custo das APIs?
[14/08/2026, 10:17:20] Usuário Teste: Ficou quase zero porque a gente usou cache e fallback local. Fechou demais 👍
"""

CONVERSA_TESTE_ANDROID = """
14/08/2026 10:14 - Contato Teste: Vamos marcar aquela reunião hoje?
14/08/2026 10:15 - Usuário Teste: Opa, fechou! Pode ser às 16h?
"""


def test_parsear_exportacao_whatsapp_ios_e_android():
    msgs_ios = iw.parsear_exportacao_whatsapp(CONVERSA_TESTE_IOS)
    assert len(msgs_ios) == 5
    assert msgs_ios[0].autor == "Contato Teste"
    assert msgs_ios[1].autor == "Usuário Teste"
    assert "Fala Contato!" in msgs_ios[1].texto

    msgs_android = iw.parsear_exportacao_whatsapp(CONVERSA_TESTE_ANDROID)
    assert len(msgs_android) == 2
    assert msgs_android[0].autor == "Contato Teste"
    assert msgs_android[1].autor == "Usuário Teste"


def test_extrair_pares_conversa_junta_mensagens_consecutivas():
    msgs = iw.parsear_exportacao_whatsapp(CONVERSA_TESTE_IOS)
    pares = iw.extrair_pares_conversa(msgs, nome_usuario="Usuário Teste")
    assert len(pares) == 2

    # Primeiro par: Contato perguntou do projeto, Usuário respondeu em 2 mensagens juntas
    p1 = pares[0]
    assert "projeto de IA" in p1.pergunta
    assert "Fala Contato!" in p1.resposta and "banco vetorial" in p1.resposta
    assert p1.autor_resposta == "Usuário Teste"

    # Segundo par: Contato perguntou do custo, Usuário respondeu sobre cache
    p2 = pares[1]
    assert "custo" in p2.pergunta
    assert "quase zero" in p2.resposta


def test_analisar_estilo_escrita():
    mensagens = [
        "Fala cara, fechou demais! Vamos tocar esse projeto com tudo.",
        "Tá show de bola 👍",
        "Beleza, vou ver isso agora e te aviso logo em seguida."
    ]
    analise = iw.analisar_estilo_escrita(mensagens)
    assert analise["total_mensagens"] == 3
    assert analise["media_palavras"] > 3
    assert "👍" in analise["emojis_frequentes"]


def test_avaliar_fidelidade_estilo_detecta_cliche_robotico():
    perfil = {"media_palavras": 12, "termos_frequentes": ["show", "fechou"]}
    
    # Resposta natural
    boa = la.avaliar_fidelidade_estilo("Fala meu amigo, fechou! Vamos tocar assim que tá show.", perfil)
    assert boa["score_estilo"] >= 80
    assert boa["aprovado"] is True

    # Resposta robótica artificial
    ruim = la.avaliar_fidelidade_estilo("Olá! Certamente! Como posso ajudar você hoje? Espero ter ajudado e qualquer dúvida estou à disposição.", perfil)
    assert ruim["score_estilo"] < 60
    assert ruim["aprovado"] is False
    assert len(ruim["alertas"]) >= 2


def test_motor_persona_indexacao_e_feedback_loop(tmp_path):
    import chromadb
    from core.embeddings import EmbeddingFunctionMultilingue

    cliente_chroma = chromadb.Client()
    colecao_teste = cliente_chroma.create_collection("teste_persona", embedding_function=EmbeddingFunctionMultilingue())
    
    motor = mp.MotorPersona(colecao=colecao_teste)
    
    msgs = iw.parsear_exportacao_whatsapp(CONVERSA_TESTE_IOS)
    pares = iw.extrair_pares_conversa(msgs, nome_usuario="Usuário Teste")
    salvos = motor.indexar_pares(pares)
    assert salvos == 2
    assert motor.colecao.count() == 2

    # RAG recupera o exemplo correto
    exemplos = motor.buscar_exemplos_estilo("Quanto custa a API?")
    assert len(exemplos) >= 1
    assert any("custo" in ex["pergunta"] or "zero" in ex["resposta"] for ex in exemplos)

    # Feedback Loop: adiciona uma nova correção
    res = la.aprender_com_correcao(motor, "Qual seu filme favorito?", "Gosto de Interestelar, com certeza!", autor="Usuário Teste")
    assert res["sucesso"] is True
    assert motor.colecao.count() == 3


def test_sincronizar_banco_wpp_summarizer(tmp_path):
    import sqlite3
    import chromadb
    from core.embeddings import EmbeddingFunctionMultilingue

    banco_teste = tmp_path / "teste_wpp.sqlite"
    conn = sqlite3.connect(str(banco_teste))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            remote_jid TEXT,
            sender TEXT,
            sender_name TEXT,
            text TEXT,
            timestamp INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE clone_responses_feedback (
            message_id TEXT,
            sender_name TEXT,
            response_text TEXT,
            rating INTEGER,
            timestamp INTEGER
        )
    """)
    cur.execute("INSERT INTO messages VALUES ('1', 'chat1', 'contato@s.wpp', 'Contato Teste', 'Você viu o relatório?', 1000)")
    cur.execute("INSERT INTO messages VALUES ('2', 'chat1', 'usuario@s.wpp', 'Usuário Teste', 'Sim, tá aprovado!', 1001)")
    cur.execute("INSERT INTO clone_responses_feedback VALUES ('1', 'Contato Teste', 'Sim, tá aprovado!', 1, 1002)")
    conn.commit()
    conn.close()

    cliente_chroma = chromadb.Client()
    colecao = cliente_chroma.create_collection("teste_sync_ficticio", embedding_function=EmbeddingFunctionMultilingue())
    motor = mp.MotorPersona(colecao=colecao)

    res = la.sincronizar_banco_wpp_summarizer(motor, banco_teste, nome_usuario="Usuário Teste")
    assert res["sucesso"] is True
    assert res["total_mensagens_banco"] == 2
    assert res["mensagens_usuario"] == 1
    assert res["pares_indexados"] == 1
    assert res["total_memoria"] == 1

    # Banco inexistente trata com fallback gracioso
    res_inexistente = la.sincronizar_banco_wpp_summarizer(motor, tmp_path / "inexistente.sqlite", nome_usuario="Usuário Teste")
    assert res_inexistente["sucesso"] is False


def test_modo_foco_resposta_e_pendencia():
    motor = mp.MotorPersona()
    # Teste de resposta em modo foco
    res = motor.responder_mensagem_foco(
        "Você tem a chave de acesso do servidor de homologação?",
        remetente="Contato Teste"
    )
    assert isinstance(res, dict)
    assert "resposta" in res
    assert len(res["resposta"]) > 5
    assert "precisa_acao" in res
    # A pergunta exige ação posterior, então precisa_acao deve ser True
    assert res["precisa_acao"] is True


def test_config_privada_isolamento_e_filtro():
    cfg = pc.carregar_config_privada()
    assert "contato_intimo_teste" in cfg["contatos_intimos"]
    assert "termo_sensivel_teste" in cfg["termos_sensiveis"]

    motor = mp.MotorPersona()
    # Bloqueia padrão da config temporária para terceiros
    res_bloqueada = motor._sanitizar_resposta_segura("Aqui tem um segredo bloqueado_teste", remetente="Outro")
    assert "bloqueado_teste" not in res_bloqueada
    assert "foco pesado" in res_bloqueada

    # Permite para contato íntimo da config temporária
    res_permitida = motor._sanitizar_resposta_segura("Aqui tem um segredo bloqueado_teste", remetente="contato_intimo_teste")
    assert res_permitida == "Aqui tem um segredo bloqueado_teste"
