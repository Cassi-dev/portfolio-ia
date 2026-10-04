"""Habilidades: taxonomia com aliases e casamento de requisitos da vaga contra o texto do currículo."""
import re
from dataclasses import dataclass

from texto import chave

# canônico -> aliases (já em minúsculo e sem acento)
TAXONOMIA = {
    "python": ["python", "python3", "python 3", "py"],
    "java": ["java"],
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "c#": ["c#", "csharp"],
    ".net": [".net", "dotnet", "asp.net"],
    "go": ["golang"],
    "php": ["php"],
    "ruby": ["ruby", "ruby on rails", "rails"],
    "scala": ["scala"],
    "sql": ["sql", "t-sql", "pl/sql", "plsql"],
    "postgresql": ["postgresql", "postgres", "psql"],
    "mysql": ["mysql", "mariadb"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "nosql": ["nosql", "no-sql"],
    "docker": ["docker", "containers", "containerizacao", "conteineres"],
    "kubernetes": ["kubernetes", "k8s", "eks", "gke"],
    "aws": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "azure": ["azure"],
    "gcp": ["gcp", "google cloud"],
    "git": ["git", "github", "gitlab", "bitbucket"],
    "ci/cd": ["ci/cd", "cicd", "ci cd", "integracao continua", "github actions", "jenkins", "gitlab ci"],
    "linux": ["linux", "unix", "shell script", "bash"],
    "api rest": ["api rest", "apis rest", "rest", "restful", "api restful", "apis restful", "web api", "apis"],
    "graphql": ["graphql"],
    "fastapi": ["fastapi"],
    "django": ["django", "drf"],
    "flask": ["flask"],
    "spring": ["spring", "spring boot"],
    "node.js": ["node.js", "nodejs", "node"],
    "react": ["react", "reactjs", "react.js"],
    "angular": ["angular"],
    "vue": ["vue", "vuejs", "vue.js"],
    "html/css": ["html", "css", "html5", "css3"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "machine learning": ["machine learning", "aprendizado de maquina", "ml"],
    "pytorch": ["pytorch"],
    "tensorflow": ["tensorflow"],
    "spark": ["spark", "pyspark"],
    "airflow": ["airflow"],
    "kafka": ["kafka"],
    "rabbitmq": ["rabbitmq", "rabbit mq"],
    "terraform": ["terraform"],
    "testes automatizados": ["testes automatizados", "pytest", "unittest", "junit", "tdd", "testes unitarios", "testes de integracao"],
    "metodologias ageis": ["scrum", "kanban", "agile", "metodologias ageis", "agil"],
    "power bi": ["power bi", "powerbi"],
    "excel": ["excel"],
    "microsservicos": ["microsservicos", "microservicos", "microservices", "microsservico"],
    "seo": ["seo"],
    "google ads": ["google ads", "adwords"],
    "ingles": ["ingles", "english"],
}

_LIMITE = r"(?<![a-z0-9_+#.])%s(?![a-z0-9_+#])"
_REGEX_POR_HABILIDADE = {
    canonico: re.compile("|".join(_LIMITE % re.escape(a) for a in sorted(aliases, key=len, reverse=True)))
    for canonico, aliases in TAXONOMIA.items()
}

_PREFIXOS_DE_REQUISITO = re.compile(
    r"^(?:experiencia|experiencias|conhecimento|conhecimentos|dominio|solidos conhecimentos|vivencia|"
    r"atuacao|habilidade|dominio de|proficiencia)\s+(?:solido[s]?\s+|avancado[s]?\s+|comprovado[s]?\s+)?(?:com|em|de|na|no|do|da|das|dos)?\s*"
)
_QUALIFICADORES = re.compile(r"\b(?:basico|intermediario|avancado|fluente|pleno|senior|junior|solido|solidos)\b")


def encontrar_habilidades(texto: str) -> set:
    t = chave(texto)
    return {canonico for canonico, regex in _REGEX_POR_HABILIDADE.items() if regex.search(t)}


@dataclass
class ResultadoRequisito:
    requisito: str
    atendido: bool
    evidencia: str = ""


def _evidencia(texto: str, regex) -> str:
    for linha in texto.splitlines():
        if regex.search(chave(linha)):
            return linha.strip()[:140]
    return ""


def avaliar_requisito(requisito: str, texto: str) -> ResultadoRequisito:
    """
    Um requisito por linha. Se cita habilidades conhecidas, todas precisam aparecer (ou qualquer uma, se
    tem "ou"). Se não cita nenhuma, procura a frase literal (sem acento, sem prefixos como "experiência com").
    """
    req = chave(requisito)
    canonicas = [c for c, rx in _REGEX_POR_HABILIDADE.items() if rx.search(req)]
    alvo = chave(texto)

    if canonicas:
        achadas = [c for c in canonicas if _REGEX_POR_HABILIDADE[c].search(alvo)]
        ok = bool(achadas) if re.search(r"\bou\b|/", req) else len(achadas) == len(canonicas)
        evid = _evidencia(texto, _REGEX_POR_HABILIDADE[achadas[0]]) if achadas else ""
        return ResultadoRequisito(requisito, ok, evid)

    frase = _QUALIFICADORES.sub("", _PREFIXOS_DE_REQUISITO.sub("", req)).strip(" .,;:-")
    if len(frase) < 3:
        return ResultadoRequisito(requisito, False)
    regex = re.compile(_LIMITE % re.escape(frase))
    achou = bool(regex.search(alvo))
    return ResultadoRequisito(requisito, achou, _evidencia(texto, regex) if achou else "")
