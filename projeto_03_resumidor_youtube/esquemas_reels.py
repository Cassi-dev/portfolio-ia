"""
Schemas do gerador de vídeos de qualquer assunto: o LLM devolve um PlanoReel e o renderizador desenha cada cena.

Todos os campos são obrigatórios (sem valores padrão, que nem todo schema do Gemini aceita): o que não se aplica ao
layout vem como "" ou []. Regras estruturais (lista com 2 a 4 itens etc.) ficam em problemas_da_cena/corrigir_cena,
que servem tanto para consertar a saída da IA quanto para validar o que o usuário edita na tela.
"""
from typing import Literal

from pydantic import BaseModel, Field

LAYOUTS = ("titulo", "lista", "numero", "comparacao", "cta")
MAX_TAG, MAX_TITULO, MAX_ITEM, MAX_ROTULO, MAX_BOTAO = 28, 90, 90, 22, 40
ROTULOS_PADRAO = ("ANTES", "DEPOIS")


class CenaReel(BaseModel):
    layout: Literal["titulo", "lista", "numero", "comparacao", "cta"] = Field(
        description="titulo: frase de impacto; lista: 2 a 4 itens; numero: um número real do conteúdo com rótulo; "
                    "comparacao: exatamente 2 itens (antes/depois, mito/verdade); cta: chamada final com botão")
    tag: str = Field(description="Rótulo curto da cena, em maiúsculas (ex.: O PROBLEMA, COMO FUNCIONA)")
    titulo: str = Field(description="Frase que aparece na tela, curta (até 70 caracteres), sem emojis")
    fala: str = Field(description="O que a voz narra nesta cena: frases curtas e naturais, sem emojis")
    itens: list[str] = Field(max_length=4, description="Itens da lista, os 2 lados da comparação ou até 2 linhas de apoio; [] se não se aplica")
    rotulos: list[str] = Field(max_length=2, description="Só na comparação: os 2 rótulos (ex.: MITO, VERDADE); [] nos demais")
    destaque_valor: str = Field(description='Só em numero: o número como no conteúdo (ex.: "27%", "R$ 50.000"); "" nos demais')
    destaque_rotulo: str = Field(description='Só em numero: o que o número significa; "" nos demais')
    botao: str = Field(description='Só em cta: texto do botão (até 40 caracteres); "" nos demais')


class PlanoReel(BaseModel):
    titulo_video: str
    cenas: list[CenaReel] = Field(min_length=3, max_length=7)
    legenda_instagram: str = Field(description="Legenda da postagem, com quebras de linha; pode ter emojis")
    hashtags: str = Field(description="Hashtags separadas por espaço")


def cortar(texto: str, limite: int) -> str:
    """Corta em fronteira de palavra e marca com reticências; texto curto passa intacto."""
    texto = " ".join(str(texto).split())
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1].rsplit(" ", 1)[0] or texto[: limite - 1]
    return corte.rstrip(" ,;:.-") + "…"


def _itens_validos(cena: dict) -> list[str]:
    return [i.strip() for i in cena.get("itens", []) if str(i).strip()]


def problemas_da_cena(cena: dict) -> list[str]:
    """O que impede a cena de ser desenhada direito (vazio = pronta)."""
    problemas = []
    layout, itens = cena.get("layout"), _itens_validos(cena)
    if layout not in LAYOUTS:
        return [f"layout desconhecido: {layout!r}"]
    if not str(cena.get("titulo", "")).strip():
        problemas.append("falta o título")
    if not str(cena.get("fala", "")).strip():
        problemas.append("falta a fala (o que a voz narra)")
    if layout == "lista" and not 2 <= len(itens) <= 4:
        problemas.append("a lista precisa de 2 a 4 itens")
    if layout == "comparacao" and len(itens) != 2:
        problemas.append("a comparação precisa de exatamente 2 itens")
    if layout == "numero" and not (str(cena.get("destaque_valor", "")).strip() and str(cena.get("destaque_rotulo", "")).strip()):
        problemas.append("o destaque precisa de um número e de um rótulo")
    if layout == "cta" and not str(cena.get("botao", "")).strip():
        problemas.append("falta o texto do botão")
    return problemas


def corrigir_cena(cena: dict) -> list[str]:
    """
    Conserta no lugar o que a IA costuma errar (tamanhos e layout que pede campo que não veio). Devolve o que mudou,
    para o usuário saber. Nunca inventa conteúdo: na dúvida troca para um layout mais simples.
    """
    notas = []
    cena["tag"] = cortar(cena.get("tag", ""), MAX_TAG).upper()
    cena["titulo"] = cortar(cena.get("titulo", ""), MAX_TITULO)
    cena["itens"] = [cortar(i, MAX_ITEM) for i in _itens_validos(cena)][:4]
    cena["rotulos"] = [cortar(r, MAX_ROTULO).upper() for r in cena.get("rotulos", []) if str(r).strip()][:2]
    cena["botao"] = cortar(cena.get("botao", ""), MAX_BOTAO)
    for campo in ("destaque_valor", "destaque_rotulo"):
        cena[campo] = str(cena.get(campo, "")).strip()
    if not str(cena.get("fala", "")).strip():
        cena["fala"] = cena["titulo"]

    layout, n = cena["layout"], len(cena["itens"])
    novo = layout
    if layout == "lista" and not 2 <= n <= 4:
        novo = "titulo"
    elif layout == "comparacao" and n != 2:
        novo = "lista" if 2 <= n <= 4 else "titulo"
    elif layout == "numero" and not (cena["destaque_valor"] and cena["destaque_rotulo"]):
        novo = "titulo"
    if novo != layout:
        notas.append(f"o layout {layout} não tinha o que precisa; usei {novo}")
        cena["layout"] = novo
    if cena["layout"] == "cta" and not cena["botao"]:
        cena["botao"] = cortar(cena["titulo"], MAX_BOTAO)
        notas.append("a chamada final veio sem texto de botão; usei o título")
    if cena["layout"] == "comparacao":
        rotulos = list(cena["rotulos"]) + [r for r in ROTULOS_PADRAO if r not in cena["rotulos"]]
        cena["rotulos"] = rotulos[:2]
    return notas
