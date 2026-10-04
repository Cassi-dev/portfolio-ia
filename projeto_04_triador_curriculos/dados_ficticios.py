"""
Currículos 100% FICTÍCIOS para o portfólio e para medir o ranking (LGPD: nunca use currículos reais aqui).

    python projeto_04_triador_curriculos/dados_ficticios.py      # recria dados/curriculos_ficticios + gabarito.json

Cada currículo nasce de um arquétipo com uma nota de aderência conhecida (0 a 3) para a vaga de exemplo:
    3  sênior ideal            7,5 a 11 anos, todos os obrigatórios e 4 a 6 desejáveis
    2  pleno sólido            4,5 a 6,8 anos, todos os obrigatórios e 2 a 3 desejáveis
    1  pleno básico            3,6 a 4,5 anos, todos os obrigatórios e 0 a 1 desejável
    0  júnior "recheado"      1 a 2,3 anos, lista TODAS as palavras-chave (o cosseno adora, o tempo de casa não)
    0  sênior de outra stack  7 a 10 anos em Java/Scala, sem Python (parece muito com a vaga, mas falta o requisito)
    0  sem um obrigatório      5 a 7 anos, Python/SQL/APIs REST, mas nada de Git
    0  área distante           marketing digital
A nota é a INTENÇÃO de quem gerou, não a saída do ranking: por isso serve de gabarito. Ela é circular em parte
(mais tempo e mais desejáveis = melhor), e o README diz isso; o valor está nos casos adversariais.
"""
import json
import random
import sys
import textwrap
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
PASTA_DADOS = BASE / "dados"
PASTA_CURRICULOS = PASTA_DADOS / "curriculos_ficticios"
HOJE_REFERENCIA = date(2026, 9, 19)
SEED = 7

VAGA_EXEMPLO = """Vaga: Pessoa Desenvolvedora Backend Python Pleno

Sobre a vaga:
Atuar na evolução de serviços backend de uma plataforma de pagamentos, com APIs usadas por aplicativos web e móveis.

Responsabilidades:
- Projetar, implementar e manter serviços backend
- Modelar e otimizar consultas em bancos relacionais
- Participar de revisões de código e da definição de arquitetura

Requisitos obrigatórios:
- Python
- SQL
- Git
- APIs REST
- 3 anos de experiência com desenvolvimento backend
- Ensino superior completo em Computação ou áreas afins

Desejável:
- Docker
- AWS
- PostgreSQL
- FastAPI
- Testes automatizados
- Kubernetes
"""

OBRIGATORIAS = ["Python", "SQL", "Git", "APIs REST"]
DESEJAVEIS = ["Docker", "AWS", "PostgreSQL", "FastAPI", "Testes automatizados", "Kubernetes"]
RUIDO = ["JavaScript", "React", "Linux", "Redis", "Kafka", "Airflow", "Pandas", "MongoDB", "Scrum", "Django", "Flask", "Terraform"]

FRASES = {
    "Python": ["Desenvolvimento de serviços backend em Python para processamento de pedidos", "Automação de rotinas e integrações internas em Python"],
    "SQL": ["Modelagem de tabelas e otimização de consultas SQL de alto volume", "Criação de relatórios e rotinas de carga com SQL"],
    "Git": ["Versionamento com Git, fluxo de branches e revisão de código em pull requests"],
    "APIs REST": ["Projeto e implementação de APIs REST documentadas e versionadas", "Evolução de APIs REST consumidas por aplicativos móveis"],
    "Docker": ["Empacotamento dos serviços com Docker para ambientes de teste e produção"],
    "AWS": ["Deploy e operação de serviços na AWS (filas, armazenamento e funções serverless)"],
    "PostgreSQL": ["Administração e tuning de bancos PostgreSQL em produção"],
    "FastAPI": ["Construção de serviços de baixa latência com FastAPI"],
    "Testes automatizados": ["Cobertura de testes automatizados e integração contínua nos serviços"],
    "Kubernetes": ["Orquestração dos serviços em clusters Kubernetes"],
    "JavaScript": ["Manutenção de telas administrativas em JavaScript"], "React": ["Componentes de interface em React"],
    "Linux": ["Administração de servidores Linux"], "Redis": ["Uso de Redis para cache de consultas"],
    "Kafka": ["Processamento de eventos com Kafka"], "Airflow": ["Orquestração de pipelines de dados com Airflow"],
    "Pandas": ["Análises exploratórias com Pandas"], "MongoDB": ["Modelagem de coleções em MongoDB"],
    "Scrum": ["Trabalho em times ágeis com Scrum"], "Django": ["Aplicações web em Django"], "Flask": ["Serviços leves em Flask"],
    "Terraform": ["Infraestrutura como código com Terraform"],
    # outra stack e área distante
    "Java": ["Desenvolvimento de serviços em Java com Spring Boot"], "Scala": ["Pipelines de processamento em Scala"],
    "Spark": ["Processamento distribuído de grandes volumes com Spark"], "Microsserviços": ["Arquitetura de microsserviços com mensageria"],
    "SEO": ["Otimização de conteúdo e SEO para aquisição orgânica"], "Google Ads": ["Gestão de campanhas de Google Ads"],
    "Excel": ["Painéis e análises de desempenho em Excel"], "Power BI": ["Dashboards de resultados de campanha em Power BI"],
}
CARGOS = {"dev": ["Desenvolvedor(a) Backend", "Engenheiro(a) de Software", "Desenvolvedor(a) de Software"],
          "mkt": ["Analista de Marketing Digital", "Especialista em Performance"]}
EMPRESAS = ["Nimbus Tecnologia", "Orbita Sistemas", "Vertice Digital", "Atlas Pagamentos", "Lume Software", "Quartzo Dados",
            "Faisca Labs", "Aurora Comercio Digital", "Zenite Solucoes", "Prisma Varejo", "Boreal Logistica", "Cinza Estudio"]
NOMES = ["Alex", "Bianca", "Caio", "Daniela", "Eduardo", "Fernanda", "Gustavo", "Helena", "Igor", "Julia", "Kaique", "Larissa",
         "Marcos", "Natalia", "Otavio", "Paula", "Rafael", "Sabrina", "Tiago", "Vitoria"]
SOBRENOMES = ["Almeida", "Barros", "Cardoso", "Dias", "Esteves", "Fonseca", "Gomes", "Holanda", "Ibrahim", "Jardim", "Klein", "Lima",
              "Moraes", "Nogueira", "Oliveira", "Pacheco", "Queiroz", "Ramos", "Souza", "Teixeira"]
MESES_ABREV = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
MESES_EXTENSO = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
TITULOS = {
    "resumo": ["Resumo Profissional", "Perfil", "Resumo"],
    "experiencia": ["Experiência Profissional", "Experiência", "Histórico Profissional"],
    "formacao": ["Formação Acadêmica", "Formação", "Educação"],
    "competencias": ["Competências", "Habilidades Técnicas", "Skills"],
}

ARQUETIPOS = [
    # nome, nota, quantidade, (anos min, max)
    ("senior_ideal", 3, 8, (7.5, 11.0)),
    ("pleno_solido", 2, 10, (4.5, 6.8)),
    ("pleno_basico", 1, 6, (3.6, 4.5)),
    ("junior_recheado", 0, 6, (1.0, 2.3)),
    ("senior_outra_stack", 0, 5, (7.0, 10.0)),
    ("sem_git", 0, 3, (5.0, 7.0)),
    ("area_distante", 0, 2, (6.0, 9.0)),
]


def _indice(d: date) -> int:
    return d.year * 12 + d.month - 1


def _de_indice(i: int) -> tuple[int, int]:
    return i // 12, i % 12 + 1


def _formatar_data(ano: int, mes: int, formato: str) -> str:
    return {
        "abrev": f"{MESES_ABREV[mes - 1]}/{ano}", "numerico": f"{mes:02d}/{ano}",
        "extenso": f"{MESES_EXTENSO[mes - 1]} de {ano}", "so_ano": f"{ano}",
    }[formato]


def _periodos(anos: float, hoje: date, rng: random.Random, formato: str):
    """Empregos do mais antigo ao mais recente, cobrindo `anos` de experiência, com folgas pequenas entre eles."""
    meses = round(anos * 12)
    n = 2 if meses < 60 else rng.choice([2, 3])
    partes = [max(12, meses // n)] * n
    partes[-1] = meses - sum(partes[:-1])
    fim_atual = _indice(hoje)
    periodos, fim = [], fim_atual
    for i, duracao in enumerate(reversed(partes)):
        inicio = fim - duracao + 1
        periodos.append((inicio, None if i == 0 else fim))
        fim = inicio - 1 - rng.choice([0, 0, 1])
    periodos.reverse()
    texto = []
    for inicio, fim_ in periodos:
        a, m = _de_indice(inicio)
        ini = _formatar_data(a, m, formato)
        if fim_ is None:
            texto.append(f"{ini} - atual" if formato != "extenso" else f"{ini} a atual")
        else:
            fa, fm = _de_indice(fim_)
            texto.append(f"{ini} - {_formatar_data(fa, fm, formato)}" if formato != "extenso" else f"{ini} a {_formatar_data(fa, fm, formato)}")
    meses_reais = sum((fim_ if fim_ is not None else fim_atual) - inicio + 1 for inicio, fim_ in periodos)
    return texto, meses_reais / 12


def _habilidades(arquetipo: str, rng: random.Random) -> list[str]:
    if arquetipo == "senior_ideal":
        return OBRIGATORIAS + rng.sample(DESEJAVEIS, rng.randint(4, 6)) + rng.sample(RUIDO, rng.randint(2, 4))
    if arquetipo == "pleno_solido":
        return OBRIGATORIAS + rng.sample(DESEJAVEIS, rng.randint(2, 3)) + rng.sample(RUIDO, rng.randint(2, 4))
    if arquetipo == "pleno_basico":
        return OBRIGATORIAS + rng.sample(DESEJAVEIS, rng.randint(0, 1)) + rng.sample(RUIDO, rng.randint(1, 3))
    if arquetipo == "junior_recheado":
        return OBRIGATORIAS + DESEJAVEIS + rng.sample(RUIDO, 5)
    if arquetipo == "senior_outra_stack":
        return ["Java", "Scala", "Spark", "Kafka", "SQL", "Git", "APIs REST", "Microsserviços", "Docker", "AWS"] + rng.sample(["Linux", "Redis", "MongoDB", "Scrum"], 2)
    if arquetipo == "sem_git":
        return ["Python", "SQL", "APIs REST"] + rng.sample(DESEJAVEIS[:4], 2) + rng.sample(["Django", "Flask", "Redis", "Pandas", "Scrum"], 2)
    return ["SEO", "Google Ads", "Excel", "Power BI"]


def _texto_curriculo(arquetipo: str, nome: str, anos: float, rng: random.Random) -> tuple[str, float, list]:
    formato = "so_ano" if rng.random() < 0.15 else rng.choice(["abrev", "numerico", "extenso"])
    periodos, anos_reais = _periodos(anos, HOJE_REFERENCIA, rng, formato)
    habilidades = _habilidades(arquetipo, rng)
    dev = arquetipo != "area_distante"
    cargos = CARGOS["dev" if dev else "mkt"]
    empresas = rng.sample(EMPRESAS, len(periodos))

    experiencia = []
    for i, (periodo, empresa) in enumerate(zip(periodos, empresas)):
        alvo = habilidades if arquetipo == "junior_recheado" else rng.sample(habilidades, min(len(habilidades), 3))
        experiencia.append(f"{rng.choice(cargos)} - {empresa}\n{periodo}\n" + "\n".join(f"- {rng.choice(FRASES[h])}" for h in alvo))

    if arquetipo == "junior_recheado":
        formacao = f"Graduação em Ciência da Computação - Centro Universitário Modelo ({rng.choice([2024, 2025])})"
    elif arquetipo == "senior_ideal" and rng.random() < 0.4:
        formacao = "Especialização em Engenharia de Software - Universidade Federal Exemplo (2019)\nBacharelado em Sistemas de Informação - Universidade Federal Exemplo (2014)"
    elif dev:
        formacao = f"Bacharelado em {rng.choice(['Ciência da Computação', 'Sistemas de Informação', 'Engenharia da Computação'])} - Universidade Federal Exemplo ({rng.randint(2008, 2021)})"
    else:
        formacao = "Graduação em Publicidade e Propaganda - Faculdade Exemplo (2015)"

    email = nome.lower().replace(" ", ".") + "@example.com"
    cabecalho = f"{nome}\n{rng.choice(cargos)}\nSão Paulo - SP - {email} - (11) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"
    resumo = f"Profissional com {int(anos)} anos de trajetória, foco em resultados e trabalho em equipe."
    partes = [
        cabecalho, "", rng.choice(TITULOS["resumo"]), resumo, "",
        rng.choice(TITULOS["experiencia"]), "\n\n".join(experiencia), "",
        rng.choice(TITULOS["formacao"]), formacao, "",
        rng.choice(TITULOS["competencias"]), ", ".join(habilidades), "", "Idiomas", "Inglês intermediário",
    ]
    return "\n".join(partes), anos_reais, habilidades


def gerar_curriculos(seed: int = SEED) -> list[dict]:
    """Lista de {arquivo, texto, nota, arquetipo, anos_reais} (sem escrever nada em disco)."""
    rng = random.Random(seed)
    nomes = [f"{n} {s}" for n in NOMES for s in SOBRENOMES]
    rng.shuffle(nomes)
    itens = []
    for arquetipo, nota, quantidade, (minimo, maximo) in ARQUETIPOS:
        for _ in range(quantidade):
            nome = nomes.pop()
            anos = round(rng.uniform(minimo, maximo), 1)
            texto, anos_reais, habilidades = _texto_curriculo(arquetipo, nome, anos, rng)
            itens.append({"texto": texto, "nota": nota, "arquetipo": arquetipo, "anos_reais": round(anos_reais, 1), "nome": nome, "habilidades": habilidades})
    rng.shuffle(itens)
    for i, item in enumerate(itens, 1):
        item["arquivo"] = f"curriculo_{i:02d}.pdf"
    return itens


def escrever_pdf(texto: str, caminho: Path) -> None:
    import pymupdf
    linhas = []
    for linha in texto.splitlines():
        linhas.extend(textwrap.wrap(linha, 92) or [""])
    doc = pymupdf.open()
    for inicio in range(0, len(linhas), 52):
        pagina = doc.new_page()
        for i, linha in enumerate(linhas[inicio:inicio + 52]):
            pagina.insert_text((50, 60 + i * 13.5), linha, fontsize=10, fontname="helv")
    doc.save(str(caminho))
    doc.close()


def criar_conjunto(pasta: Path = PASTA_DADOS, seed: int = SEED) -> list[dict]:
    pasta_pdfs = pasta / "curriculos_ficticios"
    pasta_pdfs.mkdir(parents=True, exist_ok=True)
    itens = gerar_curriculos(seed)
    for item in itens:
        escrever_pdf(item["texto"], pasta_pdfs / item["arquivo"])
    (pasta / "vaga_exemplo.txt").write_text(VAGA_EXEMPLO, encoding="utf-8")
    gabarito = {
        "aviso": "Todos os dados são fictícios e gerados por dados_ficticios.py.",
        "hoje": HOJE_REFERENCIA.isoformat(), "seed": seed,
        "curriculos": [{k: i[k] for k in ("arquivo", "nome", "nota", "arquetipo", "anos_reais", "habilidades")} for i in sorted(itens, key=lambda x: x["arquivo"])],
    }
    (pasta / "gabarito.json").write_text(json.dumps(gabarito, ensure_ascii=False, indent=2), encoding="utf-8")
    return itens


if __name__ == "__main__":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    itens = criar_conjunto()
    print(f"{len(itens)} currículos fictícios em {PASTA_CURRICULOS}")
