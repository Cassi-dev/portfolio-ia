import csv
import io
import json
from datetime import date

import pytest

from analise_llm import gerar_carta, recomendacao_por_regras, reordenar_com_llm
from avaliar_ranking import avaliar, metricas, ndcg_em_k
from dados_ficticios import HOJE_REFERENCIA, criar_conjunto, gerar_curriculos
from exportacao import COLUNAS, ranking_para_csv
from experiencia import calcular_experiencia
from formacao import atende_formacao, nivel_formacao
from habilidades import avaliar_requisito, encontrar_habilidades
from pontuacao import Curriculo, avaliar_curriculo, ranquear
from privacidade import extrair_nome, redigir_pii
from secoes import dividir_secoes
from texto import PDFSemTexto, extrair_texto_pdf, sem_acentos
from vaga import Vaga, extrair_vaga, extrair_vaga_por_regras

HOJE = date(2026, 9, 19)
SIM_FIXA = lambda a, b: 0.90          # cosseno constante: isola a lógica das regras do modelo de embeddings

VAGA = Vaga(
    titulo="Backend Python", requisitos_obrigatorios=["Python", "SQL", "Git"], requisitos_desejaveis=["Docker", "AWS", "Kubernetes"],
    anos_experiencia_minimos=3, formacao_minima="graduacao", descricao="Backend com Python e SQL.",
)


def cv(anos_periodos="Jan/2019 - Dez/2024", habilidades="Python, SQL, Git", formacao="Bacharelado em Computação", nome="Ana Souza"):
    return Curriculo(
        nome=nome, arquivo=f"{nome}.pdf",
        texto=f"{nome}\n\nExperiência Profissional\nDesenvolvedora - Empresa X\n{anos_periodos}\n- Trabalho com {habilidades}\n\n"
              f"Formação\n{formacao}\n\nCompetências\n{habilidades}\n",
    )


# --- texto e PDF --------------------------------------------------------------------------

def test_pdf_ida_e_volta_preserva_acentos(tmp_path):
    from dados_ficticios import escrever_pdf
    caminho = tmp_path / "x.pdf"
    escrever_pdf("Experiência Profissional\nCoordenação de projetos em São Paulo\nMar/2019 - Dez/2022", caminho)
    texto = extrair_texto_pdf(str(caminho))
    assert "Coordenação" in texto and "São Paulo" in texto
    assert extrair_texto_pdf(caminho.read_bytes()) == texto


def test_pdf_sem_texto_levanta_erro_claro(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    caminho = tmp_path / "vazio.pdf"
    doc.save(str(caminho))
    with pytest.raises(PDFSemTexto):
        extrair_texto_pdf(str(caminho))


# --- seções ---------------------------------------------------------------------------------

def test_secoes_em_portugues_ingles_e_maiusculas():
    texto = "Ana Souza\nana@example.com\n\nEXPERIÊNCIA PROFISSIONAL\nDev - X\n2020 - atual\n\nEducation\nBSc Computer Science\n\nSkills: Python, SQL\n"
    s = dividir_secoes(texto)
    assert s.reconhecida
    assert "Dev - X" in s.textos["experiencia"] and "BSc" in s.textos["formacao"] and s.textos["competencias"] == "Python, SQL"
    assert "ana@example.com" in s.textos["cabecalho"]


def test_linha_de_conteudo_nao_vira_cabecalho():
    s = dividir_secoes("Experiência Profissional\n- Experiência com Python e SQL\nFormação\nGraduação\n")
    assert "Experiência com Python" in s.textos["experiencia"]


def test_sem_cabecalhos_cai_no_documento_inteiro():
    s = dividir_secoes("Ana Souza\nDesenvolvedora Python desde 2019 - atual\nBacharel em Computação\n")
    assert not s.reconhecida
    assert "Python" in s.obter("experiencia", "Ana Souza\nDesenvolvedora Python")


# --- experiência -----------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,meses", [
    ("Jan/2019 - Dez/2022", 48),
    ("03/2019 - 05/2022", 39),
    ("2018 - 2021", 36),                                        # só ano: conservador (jul a jun)
    ("Março de 2020 a atual", 79),                             # até set/2026
    ("Jan 2020 to Present", 81),
    ("Janeiro de 2019 a Dezembro de 2022", 48),
    ("jan/2019 – dez/2019", 12),                               # travessão
    ("de 2015 a 2018", 36),
    ("2019 - 2019", 6),
    ("Mar/2021 até o momento", 67),
])
def test_periodos_em_varios_formatos(texto, meses):
    assert calcular_experiencia(texto, HOJE).meses == meses


def test_periodos_sobrepostos_nao_contam_duas_vezes_e_adjacentes_se_unem():
    assert calcular_experiencia("Jan/2019 - Dez/2022\nJan/2020 - Dez/2021", HOJE).meses == 48
    assert calcular_experiencia("Jan/2015 - Dez/2016\nJan/2017 - Dez/2018", HOJE).meses == 48
    assert calcular_experiencia("Jan/2010 - Dez/2010\nJan/2015 - Dez/2015", HOJE).meses == 24


def test_periodos_impossiveis_sao_ignorados():
    assert calcular_experiencia("2030 - 2031", HOJE).meses == 0
    assert calcular_experiencia("Dez/2022 - Jan/2019", HOJE).meses == 0


def test_anos_declarados_so_valem_sem_periodos():
    r = calcular_experiencia("Mais de 8 anos de experiência com backend", HOJE)
    assert (r.anos, r.fonte) == (8.0, "declarado")
    assert calcular_experiencia("8 anos de experiência. Jan/2020 - Dez/2020", HOJE).fonte == "periodos"
    assert calcular_experiencia("sem datas", HOJE).fonte == "nenhuma"


def test_telefone_e_cep_nao_viram_periodo():
    assert calcular_experiencia("(11) 99999-2019\nCEP 01310-100\nMatrícula 12345", HOJE).meses == 0


def test_datas_da_formacao_nao_entram_na_experiencia():
    av = avaliar_curriculo(cv(formacao="Bacharelado em Computação\n2010 - 2014"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert av.anos == 6.0


# --- formação --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,nivel", [
    ("Bacharelado em Ciência da Computação", "graduacao"),
    ("Tecnólogo em Análise e Desenvolvimento de Sistemas", "graduacao"),
    ("Pós-graduação em Engenharia de Software", "pos"),
    ("MBA em Gestão de Projetos", "pos"),
    ("Mestrado em Computação", "mestrado"),
    ("Ph.D. in Computer Science", "doutorado"),
    ("Curso Técnico em Informática", "tecnico"),
    ("Ensino Médio completo", "medio"),
    ("Cursando graduação em Sistemas de Informação", "nenhuma"),
    ("Graduação em Direito (incompleto)", "nenhuma"),
    ("Bacharelado em Computação\nMestrado (em andamento)", "graduacao"),
])
def test_nivel_de_formacao(texto, nivel):
    assert nivel_formacao(texto) == nivel


def test_comparacao_de_niveis():
    assert atende_formacao("pos", "graduacao") and not atende_formacao("tecnico", "graduacao") and atende_formacao("nenhuma", "nenhuma")


# --- habilidades e requisitos -----------------------------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("Trabalho com Postgres e k8s", {"postgresql", "kubernetes"}),
    ("Node.js, C# e .NET", {"node.js", "c#", ".net"}),
    ("Java e JavaScript", {"java", "javascript"}),
    ("Apenas javascript", {"javascript"}),                    # "java" não pode casar dentro de "javascript"
    ("CI/CD com GitHub Actions", {"ci/cd", "git"}),
    ("Desenvolvo APIs RESTful", {"api rest"}),
    ("Sem tecnologia nenhuma", set()),
])
def test_deteccao_de_habilidades(texto, esperado):
    assert encontrar_habilidades(texto) == esperado


def test_java_nao_e_python_nem_vice_versa():
    assert "python" not in encontrar_habilidades("Java, Scala e Spark")
    assert "java" not in encontrar_habilidades("Python e pandas")


@pytest.mark.parametrize("requisito,texto,atendido", [
    ("Python", "Backend em Python", True),
    ("Python", "Backend em Java", False),
    ("Docker e Kubernetes", "Docker em produção", False),          # "e": precisa dos dois
    ("Docker e Kubernetes", "Docker e k8s", True),
    ("AWS ou GCP", "Deploy na GCP", True),                         # "ou": basta um
    ("Experiência com Power BI", "Dashboards em Power BI", True),
    ("Inglês avançado", "Idiomas: inglês avançado", True),
    ("Gestão de projetos", "Coordenei a gestão de projetos de TI", True),
    ("Gestão de projetos", "Coordenei projetos", False),
    ("Conhecimento em Pacote Office", "Domínio de pacote office", True),
])
def test_avaliar_requisito(requisito, texto, atendido):
    assert avaliar_requisito(requisito, texto).atendido is atendido


def test_requisito_atendido_traz_evidencia():
    r = avaliar_requisito("Docker", "Empresa X\n- Empacotamento com Docker em produção\n- Outra coisa")
    assert r.atendido and "Docker" in r.evidencia


# --- a vaga -------------------------------------------------------------------------------------------------------

def test_vaga_de_exemplo_e_extraida_por_regras():
    v = extrair_vaga_por_regras(open("projeto_04_triador_curriculos/dados/vaga_exemplo.txt", encoding="utf-8").read())
    assert v.titulo == "Pessoa Desenvolvedora Backend Python Pleno"
    assert v.requisitos_obrigatorios == ["Python", "SQL", "Git", "APIs REST"]
    assert v.requisitos_desejaveis == ["Docker", "AWS", "PostgreSQL", "FastAPI", "Testes automatizados", "Kubernetes"]
    assert (v.anos_experiencia_minimos, v.formacao_minima) == (3, "graduacao")


def test_vaga_em_outros_formatos():
    texto = "Analista de Dados\n\nMust have:\n* SQL\n* Power BI\n* Mínimo de 5 anos de experiência\n* Pós-graduação\n\nNice to have:\n* Python\n\nBenefícios:\n- VR\n"
    v = extrair_vaga_por_regras(texto)
    assert v.requisitos_obrigatorios == ["SQL", "Power BI"]
    assert v.requisitos_desejaveis == ["Python"]
    assert (v.anos_experiencia_minimos, v.formacao_minima) == (5, "pos")


def test_vaga_com_requisitos_na_mesma_linha():
    v = extrair_vaga_por_regras("Dev\nRequisitos obrigatórios: Python, SQL; Git\nDiferenciais: Docker, AWS\n")
    assert v.requisitos_obrigatorios == ["Python", "SQL", "Git"] and v.requisitos_desejaveis == ["Docker", "AWS"]


def test_vaga_sem_estrutura_nao_quebra():
    v = extrair_vaga_por_regras("Procuramos alguém muito bom.")
    assert v.requisitos_obrigatorios == [] and v.anos_experiencia_minimos == 0


def test_vaga_pela_ia_e_fallback_para_regras(cliente_falso):
    ia = json.dumps({"titulo": "T", "requisitos_obrigatorios": ["Go"], "requisitos_desejaveis": [], "anos_experiencia_minimos": 2, "formacao_minima": "nenhuma"})
    v, degradado, _ = extrair_vaga("qualquer texto", cliente_falso(ia))
    assert v.requisitos_obrigatorios == ["Go"] and not degradado and v.descricao == "qualquer texto"
    v2, degradado2, motivo = extrair_vaga("Dev\nRequisitos obrigatórios: Python\n", cliente_falso(RuntimeError("cota")))
    assert v2.requisitos_obrigatorios == ["Python"] and degradado2 and "cota" in motivo


# --- privacidade -------------------------------------------------------------------------------------------------------------

def test_redigir_pii_mascara_contatos_e_nome_mas_preserva_datas_e_habilidades():
    texto = "Ana Souza\nana.souza@example.com | (11) 91234-5678 | linkedin.com/in/anasouza\nCPF 123.456.789-09\nPython - Empresa X\n2018-2021"
    saida = redigir_pii(texto, "Ana Souza")
    for vazou in ["Ana", "Souza", "@example.com", "91234", "linkedin.com", "123.456"]:
        assert vazou not in saida
    assert "Python" in saida and "2018-2021" in saida and "[CANDIDATO]" in saida


def test_extrair_nome():
    assert extrair_nome("Maria de Souza Lima\nDesenvolvedora") == "Maria de Souza Lima"
    assert extrair_nome("CURRICULUM VITAE\nPython e SQL", "arquivo") == "arquivo"


# --- pontuação --------------------------------------------------------------------------------------------------------------------

def test_quem_nao_tem_requisito_obrigatorio_e_reprovado_antes_da_nota():
    av = avaliar_curriculo(cv(habilidades="Python, SQL, Docker, AWS, Kubernetes"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert not av.aprovado and av.nota is None and av.ausentes_obrigatorios == ["Git"]
    assert len(av.motivos_reprovacao) == 1 and "Git" in av.motivos_reprovacao[0]


def test_junior_recheado_de_palavras_chave_e_reprovado_por_tempo():
    av = avaliar_curriculo(cv("Jan/2025 - atual", "Python, SQL, Git, Docker, AWS, Kubernetes"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert not av.aprovado and "mínimo 3" in av.motivos_reprovacao[0]


def test_formacao_insuficiente_reprova():
    av = avaliar_curriculo(cv(formacao="Curso Técnico em Informática"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert not av.aprovado and "Formação" in av.motivos_reprovacao[0]


def test_mais_experiencia_e_mais_desejaveis_dao_nota_maior():
    pleno = avaliar_curriculo(cv("Jan/2022 - atual", "Python, SQL, Git"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    senior = avaliar_curriculo(cv("Jan/2014 - atual", "Python, SQL, Git, Docker, AWS"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert pleno.aprovado and senior.aprovado and senior.nota > pleno.nota
    assert senior.notas_secoes["experiencia"] > pleno.notas_secoes["experiencia"]


def test_notas_sao_de_0_a_100_e_o_cosseno_nunca_aparece():
    av = avaliar_curriculo(cv(), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert 0 <= av.nota <= 100 and all(0 <= v <= 100 for v in av.notas_secoes.values())
    assert "cosseno" not in json.dumps(av.para_dict()).lower()


def test_pesos_mudam_a_nota_final():
    a = avaliar_curriculo(cv("Jan/2022 - atual"), VAGA, hoje=HOJE, similaridade=SIM_FIXA, pesos={"competencias": 1, "experiencia": 0, "formacao": 0})
    b = avaliar_curriculo(cv("Jan/2022 - atual"), VAGA, hoje=HOJE, similaridade=SIM_FIXA, pesos={"competencias": 0, "experiencia": 1, "formacao": 0})
    assert a.nota == a.notas_secoes["competencias"] and b.nota == b.notas_secoes["experiencia"] and a.nota != b.nota


def test_filtrar_falso_pontua_mesmo_quem_seria_reprovado():
    av = avaliar_curriculo(cv(habilidades="Python, SQL"), VAGA, hoje=HOJE, similaridade=SIM_FIXA, filtrar=False)
    assert av.aprovado and av.nota is not None and av.motivos_reprovacao


def test_curriculo_sem_secoes_ainda_e_analisado_com_aviso():
    texto = "Ana Souza\nDesenvolvedora com Python, SQL e Git, de Jan/2018 - atual.\nBacharel em Computação."
    av = avaliar_curriculo(Curriculo("Ana", "a.pdf", texto), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert not av.estrutura_reconhecida and av.aprovado


def test_ranking_ordena_aprovados_por_nota_e_reprovados_ficam_sem_posicao():
    cvs = [cv("Jan/2022 - atual", nome="Pleno Um"), cv("Jan/2014 - atual", "Python, SQL, Git, Docker", nome="Senior Dois"), cv(habilidades="Python", nome="Sem Git")]
    ranking = ranquear(cvs, VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    assert [a.nome for a in ranking] == ["Senior Dois", "Pleno Um", "Sem Git"]
    assert [a.posicao for a in ranking] == [1, 2, None]


# --- camada de IA -----------------------------------------------------------------------------------------------------------------------

def avaliacao_json(nota):
    return json.dumps({"nota": nota, "justificativa": "Boa experiência.", "pontos_fortes": ["Python"], "lacunas": ["Kubernetes"],
                       "recomendacao": "Entrevistar. Aprofundar infraestrutura."})


def dois_finalistas():
    cvs = [cv("Jan/2014 - atual", "Python, SQL, Git, Docker", nome="Ana Souza"), cv("Jan/2016 - atual", "Python, SQL, Git", nome="Bruno Lima")]
    ranking = ranquear(cvs, VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    return ranking, {c.arquivo: c for c in cvs}


def test_ia_mistura_a_nota_e_reordena_so_os_finalistas(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    nota_regras = {a.nome: a.nota for a in ranking}
    assert ranking[0].nome == "Ana Souza"
    cliente = cliente_falso(avaliacao_json(20), avaliacao_json(100))     # a IA discorda das regras
    saida = reordenar_com_llm(ranking, por_arquivo, VAGA, cliente, top_n=2)
    ana = next(a for a in saida if a.nome == "Ana Souza")
    assert ana.analise["origem"] == "llm" and ana.nota == round(0.6 * nota_regras["Ana Souza"] + 0.4 * ana.analise["nota"], 1)
    assert len(cliente.models.chamadas) == 2


def test_so_top_n_vai_para_a_ia_e_o_resto_fica_com_analise_por_regras(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    cliente = cliente_falso(avaliacao_json(80))
    saida = reordenar_com_llm(ranking, por_arquivo, VAGA, cliente, top_n=1)
    assert len(cliente.models.chamadas) == 1
    assert saida[0].analise["origem"] == "llm" and saida[1].analise["origem"] == "regras" and saida[1].analise["degradado"]


def test_dados_pessoais_nao_vao_para_a_api(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    por_arquivo["Ana Souza.pdf"].texto += "\nana.souza@example.com (11) 91234-5678 CPF 123.456.789-09"
    cliente = cliente_falso(avaliacao_json(80))
    reordenar_com_llm(ranking, por_arquivo, VAGA, cliente, top_n=2)
    enviado = " ".join(c["contents"] for c in cliente.models.chamadas)
    assert "Ana Souza" not in enviado and "@example.com" not in enviado and "91234" not in enviado and "123.456" not in enviado
    assert "Python" in enviado and "[CANDIDATO]" in enviado


def test_falha_da_ia_vira_analise_por_regras_com_motivo(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    saida = reordenar_com_llm(ranking, por_arquivo, VAGA, cliente_falso(RuntimeError("cota esgotada")), top_n=2)
    assert all(a.analise["origem"] == "regras" and "cota esgotada" in a.analise["motivo_degradado"] for a in saida)
    assert [a.nome for a in saida] == ["Ana Souza", "Bruno Lima"]        # ordem das regras preservada


def test_nota_da_ia_fora_da_faixa_e_rejeitada(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    saida = reordenar_com_llm(ranking, por_arquivo, VAGA, cliente_falso(avaliacao_json(150)), top_n=2)
    assert all(a.analise["origem"] == "regras" and "formato" in a.analise["motivo_degradado"] for a in saida)


def test_sem_ia_todos_recebem_recomendacao_por_regras(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    saida = reordenar_com_llm(ranking, por_arquivo, VAGA, None)
    assert all(a.analise["origem"] == "regras" and a.analise["degradado"] for a in saida)
    assert "requisitos obrigatórios" in saida[0].analise["recomendacao"]


def test_recomendacao_por_regras_tem_duas_frases_e_cita_a_lacuna():
    ranking, _ = dois_finalistas()
    texto = recomendacao_por_regras(ranking[1], VAGA)
    assert texto.count(". ") >= 1 and "AWS" in texto or "Kubernetes" in texto


def test_carta_de_retorno_cita_os_motivos_reais(cliente_falso):
    av = avaliar_curriculo(cv(habilidades="Python, SQL", nome="Carla Dias"), VAGA, hoje=HOJE, similaridade=SIM_FIXA)
    carta, degradada, motivo = gerar_carta(av, cv(), VAGA, None)
    assert degradada and "Git" in carta["corpo"] and "Carla Dias" in carta["corpo"] and "estudar" in carta["corpo"]
    ia = json.dumps({"assunto": "Retorno", "corpo": "Texto da IA sobre Git."})
    carta2, degradada2, _ = gerar_carta(av, cv(), VAGA, cliente_falso(ia))
    assert not degradada2 and carta2["assunto"] == "Retorno"


# --- exportação ---------------------------------------------------------------------------------------------------------------------------

def test_csv_abre_no_excel_em_portugues_e_respeita_o_modo_anonimo(cliente_falso):
    ranking, por_arquivo = dois_finalistas()
    ranking = reordenar_com_llm(ranking, por_arquivo, VAGA, None)
    bruto = ranking_para_csv(ranking)
    assert bruto.startswith(b"\xef\xbb\xbf")                                    # BOM: acentos certos no Excel
    linhas = list(csv.reader(io.StringIO(bruto.decode("utf-8-sig")), delimiter=";"))
    assert linhas[0] == COLUNAS and len(linhas) == 3
    assert linhas[1][1] == "Ana Souza" and "," in linhas[1][4]                   # nota com vírgula decimal
    anonimo = ranking_para_csv(ranking, anonimo=True).decode("utf-8-sig")
    assert "Ana Souza" not in anonimo and "Bruno" not in anonimo and ".pdf" not in anonimo and "Candidato 01" in anonimo


# --- dados fictícios e avaliação ------------------------------------------------------------------------------------------------------------

def test_dados_fictícios_sao_deterministicos_e_nao_vazam_o_arquetipo_no_nome_do_arquivo():
    a, b = gerar_curriculos(), gerar_curriculos()
    assert [i["texto"] for i in a] == [i["texto"] for i in b] and len(a) == 40
    assert all("@example.com" in i["texto"] for i in a)
    assert not any(i["arquetipo"] in i["arquivo"] for i in a)
    assert {i["nota"] for i in a} == {0, 1, 2, 3} and sum(i["nota"] == 3 for i in a) == 8


def test_conjunto_gravado_confere_com_o_gabarito(tmp_path):
    itens = criar_conjunto(tmp_path)
    gabarito = json.loads((tmp_path / "gabarito.json").read_text(encoding="utf-8"))
    assert len(list((tmp_path / "curriculos_ficticios").glob("*.pdf"))) == len(itens) == len(gabarito["curriculos"]) == 40
    assert gabarito["hoje"] == HOJE_REFERENCIA.isoformat() and "fictícios" in gabarito["aviso"]


def test_ndcg_e_metricas():
    assert ndcg_em_k([3, 2, 1, 0]) == pytest.approx(1.0)
    assert ndcg_em_k([0, 1, 2, 3]) < 0.6 and ndcg_em_k([0, 0]) == 0.0
    m = metricas(["a", "b", "c", "d", "e", "f"], {"a": 3, "b": 0, "c": 2, "d": 0, "e": 3, "f": 1}, k=6)
    assert m["nota_0_no_top10"] == 2 and m["precisao@5 (nota>=2)"] == 0.6


def test_o_ranking_por_regras_supera_o_so_cosseno_no_conjunto_de_avaliacao():
    r = avaliar()
    assert r["metodos"]["regras_completas"]["ndcg@10"] >= 0.95
    assert r["metodos"]["so_cosseno"]["ndcg@10"] < r["metodos"]["regras_completas"]["ndcg@10"] - 0.2
    assert r["metodos"]["so_cosseno"]["nota_0_no_top10"] >= 1 and r["metodos"]["regras_completas"]["nota_0_no_top10"] == 0
    assert r["extracao"]["requisitos_revocacao"] >= 0.95 and r["extracao"]["erro_medio_absoluto_de_anos"] <= 0.3
    assert all(m["ndcg@10"] >= 0.9 for m in r["robustez"].values())
