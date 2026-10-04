"""
Avaliação de ponta a ponta COM a IA: busca -> decisão de responder -> resposta com citações -> conferência.
Roda as 68 perguntas do gabarito (corpus fictício) e mede o que importa para quem usa:

  - das perguntas que têm resposta: quantas foram respondidas corretamente (a resposta traz o fato certo e as
    citações conferem nos trechos)
  - das que NÃO têm resposta: quantas o sistema recusou (busca, IA ou citação não verificada) e quantas respondeu
    mesmo assim (resposta indevida = o pior erro de um RAG)

    GEMINI_API_KEY=... python projeto_01_chatbot_rag/6_avaliar_resposta.py [modo]     # modo padrão: vetorial_rerank

Gasta cerca de 70 chamadas da API. O resultado vai para resultados/avaliacao_resposta.json.
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

BASE = Path(__file__).resolve().parent
PASTA_TEMP = BASE / "banco_vetorial_resposta"
LIMIAR_RERANK = -4.0
LIMIAR_DISTANCIA = 0.16
_PALAVRAS_VAZIAS = set("de do da dos das em no na nos nas e ou a o as os um uma para por com que ao aos".split())


def resposta_contem_evidencia(resposta: str, evidencia: str) -> bool:
    """
    A resposta traz o fato? Todo número da evidência precisa estar na resposta, e pelo menos 60% das palavras
    relevantes dela também (a IA reformula, então não exigimos a frase idêntica).
    """
    from texto_util import chave
    r, e = chave(resposta), chave(evidencia)
    numeros = re.findall(r"\d+(?:[.,]\d+)?", e)
    if any(n not in re.findall(r"\d+(?:[.,]\d+)?", r) for n in numeros):
        return False
    palavras = [p for p in re.findall(r"[a-z0-9]+", e) if p not in _PALAVRAS_VAZIAS and not p.isdigit()]
    if not palavras:
        return True
    return sum(p in r for p in palavras) / len(palavras) >= 0.6


def classificar(item: dict, desfecho: str, resposta: str) -> str:
    """
    desfecho: recusou_busca | sem_base | nao_verificada | falhou | respondida.
    Devolve: acerto | resposta_errada | omissao (tinha resposta e não respondeu) | recusa_correta | resposta_indevida | falha_da_ia.
    """
    if desfecho == "falhou":
        return "falha_da_ia"
    tem_resposta = item["arquivo"] is not None
    if tem_resposta:
        if desfecho != "respondida":
            return "omissao"
        if item["evidencia"] is None or resposta_contem_evidencia(resposta, item["evidencia"]):
            return "acerto"
        return "resposta_errada"
    return "resposta_indevida" if desfecho == "respondida" else "recusa_correta"


def avaliar_ponta_a_ponta(client, recuperador, gabarito: list, limiar_rerank=LIMIAR_RERANK, limiar_distancia=LIMIAR_DISTANCIA,
                          k: int = 3) -> dict:
    from recuperacao import decidir
    from resposta import responder_com_citacoes

    linhas, contagem = [], {}
    verificadas = total = 0
    for item in gabarito:
        res = recuperador.buscar(item["pergunta"], k=k)
        decisao = decidir(res, limiar_distancia, limiar_rerank if recuperador.modo.endswith("_rerank") else None)
        if not decisao.responder:
            desfecho, texto = "recusou_busca", ""
        else:
            r = responder_com_citacoes(client, item["pergunta"], res.trechos)
            desfecho, texto = r.status, r.texto
            verificadas += r.citacoes_verificadas
            total += r.citacoes_total
        resultado = classificar(item, desfecho, texto)
        contagem[resultado] = contagem.get(resultado, 0) + 1
        linhas.append({"pergunta": item["pergunta"], "tipo": item["tipo"], "desfecho": desfecho, "resultado": resultado, "resposta": texto})

    respondiveis = sum(1 for i in gabarito if i["arquivo"] is not None)
    sem_resposta = len(gabarito) - respondiveis
    return {
        "modo": recuperador.modo,
        "acerto_nas_que_tem_resposta": round(contagem.get("acerto", 0) / respondiveis, 3),
        "omissao_nas_que_tem_resposta": round(contagem.get("omissao", 0) / respondiveis, 3),
        "resposta_errada_nas_que_tem_resposta": round(contagem.get("resposta_errada", 0) / respondiveis, 3),
        "recusa_correta_nas_que_nao_tem": round(contagem.get("recusa_correta", 0) / sem_resposta, 3),
        "resposta_indevida_nas_que_nao_tem": round(contagem.get("resposta_indevida", 0) / sem_resposta, 3),
        "citacoes_conferidas": f"{verificadas}/{total}",
        "falhas_da_ia": contagem.get("falha_da_ia", 0),
        "contagem": contagem,
        "linhas": linhas,
    }


def main(modo: str, chave_api: str) -> dict:
    import chromadb
    from core import llm
    from core.embeddings import EmbeddingFunctionMultilingue
    from recuperacao import MODOS, Recuperador

    if modo not in MODOS:
        sys.exit(f"Modo inválido. Use um destes: {', '.join(MODOS)}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("aval_recuperacao", BASE / "5_avaliar_recuperacao.py")
    aval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aval)

    shutil.rmtree(PASTA_TEMP, ignore_errors=True)
    colecao = aval.construir_colecao(chromadb.PersistentClient(path=str(PASTA_TEMP)), "resposta_contextual", "contextual",
                                     EmbeddingFunctionMultilingue())
    llm.historico.clear()
    resumo = avaliar_ponta_a_ponta(llm.criar_cliente(chave_api), Recuperador(colecao, modo), aval.carregar_gabarito())
    resumo["uso_llm"] = llm.estatisticas()
    destino = BASE / "resultados"
    destino.mkdir(exist_ok=True)
    (destino / "avaliacao_resposta.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(PASTA_TEMP, ignore_errors=True)
    return resumo


def imprimir(r: dict) -> None:
    print(f"\nModo de busca: {r['modo']}")
    print(f"Das que TÊM resposta: acerto {r['acerto_nas_que_tem_resposta']:.0%} | omissão {r['omissao_nas_que_tem_resposta']:.0%} | "
          f"resposta errada {r['resposta_errada_nas_que_tem_resposta']:.0%}")
    print(f"Das que NÃO têm: recusa correta {r['recusa_correta_nas_que_nao_tem']:.0%} | resposta indevida {r['resposta_indevida_nas_que_nao_tem']:.0%}")
    print(f"Citações que conferem nos trechos: {r['citacoes_conferidas']} | falhas da IA: {r['falhas_da_ia']}")
    uso = r.get("uso_llm", {})
    if uso:
        print(f"IA: {uso['chamadas_api']} chamadas, latência média {uso['latencia_media_ms']} ms, "
              f"{uso['tokens_entrada']} tokens de entrada / {uso['tokens_saida']} de saída")
    for linha in r["linhas"]:
        if linha["resultado"] in ("resposta_errada", "resposta_indevida", "omissao"):
            print(f"  [{linha['resultado']}] ({linha['tipo']}) {linha['pergunta']}\n      -> {linha['resposta'][:140]!r}")


if __name__ == "__main__":
    sys.path.insert(0, str(BASE))
    chave = os.environ.get("GEMINI_API_KEY", "")
    if not chave:
        sys.exit("Defina a variável de ambiente GEMINI_API_KEY para avaliar com o Gemini.")
    imprimir(main(sys.argv[1] if len(sys.argv) > 1 else "vetorial_rerank", chave))
