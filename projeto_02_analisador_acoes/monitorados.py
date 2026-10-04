"""
Cadastro do que é monitorado: um cliente (um restaurante, uma carteira) e os seus alvos (ele mesmo,
os concorrentes, um tema). Fica num JSON editável à mão, validado por Pydantic na carga — assim um erro
de digitação aparece na hora, com o caminho do campo, e não vira coleta silenciosamente vazia.

O arquivo real tem nome e e-mail de cliente, então fica fora do git; `monitorados.exemplo.json` é o modelo.
"""
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from coleta_noticias import NOMES_EMPRESAS, normalizar_ticker
from deteccao import GATILHOS_ACAO, GATILHOS_NEGOCIO

BASE = Path(__file__).resolve().parent
CAMINHO_PADRAO = BASE / "monitorados.json"
CAMINHO_EXEMPLO = BASE / "monitorados.exemplo.json"
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")


def _validar_slug(valor: str) -> str:
    if not _SLUG.fullmatch(valor):
        raise ValueError("o id deve ser minúsculo, sem acento e sem espaço (ex.: bar-do-ze)")
    return valor


class Alvo(BaseModel):
    """Uma entidade vigiada. `tema` desambigua nome genérico ("Bar do Zé" sozinho traz o país inteiro)."""
    id: str
    nome: str
    papel: Literal["proprio", "concorrente", "tema"] = "concorrente"
    termos: list[str] = Field(min_length=1, description="Termos de busca; nome próprio entra entre aspas")
    tema: str = Field(default="", description='Termos extras, ex.: "(Porto Alegre)" ou "(restaurante OR bar)"')
    regiao: Literal["BR", "US"] = "BR"

    @field_validator("id")
    @classmethod
    def _formato_do_id(cls, v):
        return _validar_slug(v)

    @field_validator("termos")
    @classmethod
    def _sem_termo_vazio(cls, v):
        termos = [t.strip() for t in v if t and t.strip()]
        if not termos:
            raise ValueError("é preciso ao menos um termo de busca não vazio")
        return termos


class Cliente(BaseModel):
    id: str
    nome: str
    perfil: Literal["negocio", "acao"]
    email: str = ""
    descricao: str = Field(default="", description="O que o cliente é e onde atua; usado para julgar se uma "
                                                   'notícia interessa a ele (ex.: "hamburgueria em Curitiba")')
    janela_dias: int = Field(default=30, ge=7, le=90)
    alvos: list[Alvo] = Field(min_length=1)
    gatilhos: list[str] = Field(default_factory=list, description="Palavras que sozinhas geram alerta; vazio = padrão do perfil")

    @field_validator("id")
    @classmethod
    def _formato_do_id(cls, v):
        return _validar_slug(v)

    @model_validator(mode="after")
    def _coerencia(self):
        ids = [a.id for a in self.alvos]
        repetidos = {i for i in ids if ids.count(i) > 1}
        if repetidos:
            raise ValueError(f"alvos com id repetido: {', '.join(sorted(repetidos))}")
        if not self.gatilhos:
            self.gatilhos = list(GATILHOS_NEGOCIO if self.perfil == "negocio" else GATILHOS_ACAO)
        return self

    @property
    def proprio(self):
        """O alvo que é o próprio cliente (para separar "a sua reputação" de "os concorrentes" no relatório)."""
        return next((a for a in self.alvos if a.papel == "proprio"), None)


class Cadastro(BaseModel):
    clientes: list[Cliente] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_unicos(self):
        ids = [c.id for c in self.clientes]
        repetidos = {i for i in ids if ids.count(i) > 1}
        if repetidos:
            raise ValueError(f"clientes com id repetido: {', '.join(sorted(repetidos))}")
        return self

    def por_id(self, cliente_id: str) -> Cliente:
        cliente = next((c for c in self.clientes if c.id == cliente_id), None)
        if cliente is None:
            raise KeyError(f"cliente '{cliente_id}' não está no cadastro (há: {', '.join(c.id for c in self.clientes)})")
        return cliente


def alvo_de_ticker(ticker: str, papel: str = "proprio") -> Alvo:
    """Monta o alvo de uma ação a partir do ticker, reaproveitando o mapa de nomes já existente."""
    t = normalizar_ticker(ticker)
    brasileiro = t[-1:].isdigit()
    nome = NOMES_EMPRESAS.get(t)
    tema = "(ação OR ações OR dividendos OR resultado OR balanço)" if brasileiro else "(stock OR shares OR earnings OR analyst)"
    return Alvo(id=t.lower(), nome=nome or t, papel=papel, termos=([nome] if nome else []) + [t], tema=tema,
                regiao="BR" if brasileiro else "US")


def cadastro_de_exemplo() -> Cadastro:
    """Um cliente de cada perfil, para rodar o monitor sem ter cliente real ainda."""
    return Cadastro(clientes=[
        Cliente(
            id="restaurante-exemplo", nome="Restaurante Exemplo (fictício)", perfil="negocio", janela_dias=30,
            descricao="restaurante de comida contemporânea em Porto Alegre, com salão e delivery próprio",
            alvos=[
                Alvo(id="restaurante-exemplo", nome="Restaurante Exemplo", papel="proprio",
                     termos=["Restaurante Exemplo"], tema="(Porto Alegre)"),
                Alvo(id="concorrente-a", nome="Concorrente A", papel="concorrente",
                     termos=["Concorrente A"], tema="(Porto Alegre)"),
                Alvo(id="mercado-food-serv", nome="Mercado de food service", papel="tema",
                     termos=["food service", "bares e restaurantes"], tema="(Porto Alegre OR Rio Grande do Sul)"),
            ],
        ),
        Cliente(id="carteira-exemplo", nome="Carteira de ações (exemplo)", perfil="acao",
                alvos=[alvo_de_ticker("PETR4"), alvo_de_ticker("VALE3", papel="concorrente")]),
    ])


def carregar(caminho=None) -> Cadastro:
    caminho = Path(caminho or CAMINHO_PADRAO)
    if not caminho.exists():
        raise FileNotFoundError(
            f"cadastro não encontrado em {caminho}. Copie {CAMINHO_EXEMPLO.name} para {CAMINHO_PADRAO.name}, ou rode"
            " `python projeto_02_analisador_acoes/rodar_monitor.py --criar-exemplo`, e depois edite o arquivo."
        )
    return Cadastro.model_validate_json(caminho.read_text(encoding="utf-8"))


def salvar(cadastro: Cadastro, caminho=None) -> Path:
    caminho = Path(caminho or CAMINHO_PADRAO)
    caminho.write_text(json.dumps(cadastro.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho
