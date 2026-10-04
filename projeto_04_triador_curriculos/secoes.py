"""Divide o currículo em seções. Pontuar o documento como um bloco só produz nota sem sentido."""
import re
from dataclasses import dataclass, field

from texto import chave

CABECALHOS = {
    "formacao": ["formacao academica", "formacao", "educacao", "escolaridade", "academic background", "education"],
    "experiencia": [
        "experiencia profissional", "experiencia", "historico profissional", "trajetoria profissional",
        "professional experience", "work experience", "experience", "atuacao profissional",
    ],
    "competencias": [
        "competencias", "competencias tecnicas", "habilidades", "habilidades tecnicas", "conhecimentos",
        "skills", "technical skills", "tecnologias", "stack", "ferramentas",
    ],
    "idiomas": ["idiomas", "languages"],
    "resumo": ["resumo", "resumo profissional", "objetivo", "perfil", "perfil profissional", "sobre mim", "summary", "profile"],
    "certificacoes": ["certificacoes", "cursos", "certificados", "cursos e certificacoes", "certifications"],
}

_CABECALHO_PARA_SECAO = {c: secao for secao, cabs in CABECALHOS.items() for c in cabs}
_LINHA_CABECALHO = re.compile(r"^[\s\-–—•*#_=|]*(?P<titulo>[^:]{2,40}?)\s*(?::\s*(?P<resto>.*))?[\s\-–—_=|]*$")


@dataclass
class Secoes:
    textos: dict = field(default_factory=dict)
    reconhecida: bool = False

    def obter(self, nome: str, texto_completo: str = "") -> str:
        """Texto da seção; se a estrutura não foi reconhecida, cai no documento inteiro."""
        return self.textos.get(nome) or (texto_completo if not self.reconhecida else "")


def _classificar_linha(linha: str):
    """(seção, texto que veio na mesma linha depois de ':') se a linha é um cabeçalho conhecido."""
    if len(linha.strip()) > 90:
        return None
    m = _LINHA_CABECALHO.match(linha)
    if not m:
        return None
    secao = _CABECALHO_PARA_SECAO.get(chave(m.group("titulo")))
    return (secao, (m.group("resto") or "").strip()) if secao else None


def dividir_secoes(texto: str) -> Secoes:
    blocos: dict[str, list[str]] = {}
    atual = "cabecalho"
    blocos[atual] = []
    for linha in texto.splitlines():
        achado = _classificar_linha(linha)
        if achado:
            atual = achado[0]
            blocos.setdefault(atual, [])
            if achado[1]:
                blocos[atual].append(achado[1])
        elif linha.strip():
            blocos[atual].append(linha.strip())
    textos = {nome: "\n".join(linhas) for nome, linhas in blocos.items() if linhas}
    return Secoes(textos=textos, reconhecida=("experiencia" in textos or "competencias" in textos))
