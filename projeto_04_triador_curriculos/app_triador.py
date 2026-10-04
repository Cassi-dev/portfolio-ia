import hashlib
import os
import sys
from datetime import date

import pandas as pd
import streamlit as st

diretorio_atual = os.path.dirname(os.path.abspath(__file__))
if diretorio_atual not in sys.path:
    sys.path.append(diretorio_atual)

from analise_llm import gerar_carta, reordenar_com_llm
from core.degradacao import MOTIVO_SEM_CHAVE
from core.llm import FalhaLLM, criar_cliente
from dados_ficticios import HOJE_REFERENCIA
from exportacao import ranking_para_csv, rotulo_anonimo
from formacao import NIVEIS
from pontuacao import PESOS_PADRAO, Curriculo, ranquear
from privacidade import extrair_nome
from texto import PDFSemTexto, extrair_texto_pdf
from vaga import Vaga, extrair_vaga

PASTA_EXEMPLO = os.path.join(diretorio_atual, "dados")

st.set_page_config(page_title="Triador de Currículos - Projeto 04", page_icon="🗂️", layout="wide")

# ==========================================
# BARRA LATERAL
# ==========================================
with st.sidebar:
    st.header("⚙️ Configurações")
    api_key = st.text_input("Chave Google Gemini API (opcional):", type="password", placeholder="Cole sua chave aqui")
    if not api_key.strip():
        st.caption("ℹ️ Sem chave: tudo roda local, por regras. A IA só reordena os melhores e escreve as análises.")

    st.subheader("Pesos da nota")
    p_comp = st.slider("Competências", 0, 100, int(PESOS_PADRAO["competencias"] * 100), 5)
    p_exp = st.slider("Experiência", 0, 100, int(PESOS_PADRAO["experiencia"] * 100), 5)
    p_form = st.slider("Formação", 0, 100, int(PESOS_PADRAO["formacao"] * 100), 5)
    top_n = st.number_input("Finalistas reavaliados pela IA:", min_value=3, max_value=30, value=10)
    anonimo = st.toggle("Modo anônimo (Candidato 01, 02...)", value=False,
                        help="Troca nome e arquivo por um rótulo na tela e no CSV, para reduzir viés na leitura.")

st.title("🗂️ Triador e Pontuador de Currículos")
st.warning(
    "🔒 **Currículo é dado pessoal (LGPD).** Tudo é analisado no seu computador; se você colar uma chave, só o texto com "
    "contatos e nome removidos vai para a API. Em demonstrações públicas use apenas dados fictícios (há 40 de exemplo)."
)

# ==========================================
# 1. A VAGA
# ==========================================
st.subheader("1. A vaga")
usar_exemplo_vaga = st.checkbox("Usar a vaga de exemplo", value=True)
texto_padrao = ""
if usar_exemplo_vaga:
    with open(os.path.join(PASTA_EXEMPLO, "vaga_exemplo.txt"), encoding="utf-8") as f:
        texto_padrao = f.read()
texto_vaga = st.text_area("Descrição da vaga:", value=texto_padrao, height=220, key="texto_vaga")

assinatura = hashlib.sha1(texto_vaga.encode("utf-8")).hexdigest()
if st.session_state.get("assinatura_vaga") != assinatura:
    client_vaga = None
    if api_key.strip():
        try:
            client_vaga = criar_cliente(api_key)
        except FalhaLLM:
            client_vaga = None
    vaga_extraida, degradado_vaga, motivo_vaga = extrair_vaga(texto_vaga, client_vaga) if texto_vaga.strip() else (Vaga(), False, None)
    st.session_state.update(
        assinatura_vaga=assinatura, campo_titulo=vaga_extraida.titulo,
        campo_obrig="\n".join(vaga_extraida.requisitos_obrigatorios), campo_desej="\n".join(vaga_extraida.requisitos_desejaveis),
        campo_anos=vaga_extraida.anos_experiencia_minimos, campo_formacao=vaga_extraida.formacao_minima,
        vaga_degradada=degradado_vaga, vaga_motivo=motivo_vaga,
    )

st.caption("Requisitos extraídos da vaga. **Revise**: obrigatório é filtro (quem não tem, é reprovado antes da nota); desejável é peso.")
if st.session_state.get("vaga_degradada"):
    st.info(f"Requisitos extraídos por regras simples ({st.session_state.get('vaga_motivo')}). Confira a lista.")
c1, c2 = st.columns(2)
with c1:
    titulo = st.text_input("Título da vaga", key="campo_titulo")
    obrigatorios = st.text_area("Requisitos obrigatórios (um por linha)", key="campo_obrig", height=140)
with c2:
    desejaveis = st.text_area("Requisitos desejáveis (um por linha)", key="campo_desej", height=140)
    c21, c22 = st.columns(2)
    anos_min = c21.number_input("Anos mínimos de experiência", min_value=0, max_value=40, key="campo_anos")
    formacao_min = c22.selectbox("Formação mínima", NIVEIS, key="campo_formacao")

vaga = Vaga(
    titulo=titulo or "Vaga", descricao=texto_vaga,
    requisitos_obrigatorios=[l.strip() for l in obrigatorios.splitlines() if l.strip()],
    requisitos_desejaveis=[l.strip() for l in desejaveis.splitlines() if l.strip()],
    anos_experiencia_minimos=int(anos_min), formacao_minima=formacao_min,
)

# ==========================================
# 2. OS CURRÍCULOS
# ==========================================
st.subheader("2. Os currículos")
usar_exemplo_cv = st.checkbox("Usar os 40 currículos fictícios de exemplo", value=True)
enviados = st.file_uploader("Ou envie PDFs:", type=["pdf"], accept_multiple_files=True, disabled=usar_exemplo_cv)

if st.button("⚡ Analisar currículos", type="primary"):
    curriculos, falhas = [], []
    if usar_exemplo_cv:
        pasta = os.path.join(PASTA_EXEMPLO, "curriculos_ficticios")
        fontes = [(nome, open(os.path.join(pasta, nome), "rb").read()) for nome in sorted(os.listdir(pasta)) if nome.endswith(".pdf")]
    else:
        fontes = [(f.name, f.getvalue()) for f in enviados or []]

    for nome_arquivo, dados in fontes:
        try:
            texto = extrair_texto_pdf(dados)
            curriculos.append(Curriculo(nome=extrair_nome(texto, os.path.splitext(nome_arquivo)[0]), arquivo=nome_arquivo, texto=texto))
        except PDFSemTexto:
            falhas.append(f"{nome_arquivo}: PDF escaneado (sem texto). Este projeto não faz OCR.")
        except Exception as e:
            falhas.append(f"{nome_arquivo}: não foi possível ler ({type(e).__name__}).")

    if not curriculos:
        st.error("Nenhum currículo legível para analisar.")
    elif not vaga.requisitos_obrigatorios and not vaga.requisitos_desejaveis:
        st.error("Informe ao menos um requisito da vaga para poder pontuar.")
    else:
        pesos = {"competencias": p_comp, "experiencia": p_exp, "formacao": p_form}
        client = None
        if api_key.strip():
            try:
                client = criar_cliente(api_key)
            except FalhaLLM as e:
                st.warning(f"Não foi possível iniciar o cliente do Gemini ({e}). Seguindo por regras.")
        with st.spinner(f"Analisando {len(curriculos)} currículo(s)..."):
            # Os fictícios têm empregos "atual" congelados na data em que foram gerados; sem isso a demo mudaria com o tempo
            data_referencia = HOJE_REFERENCIA if usar_exemplo_cv else date.today()
            ranking = ranquear(curriculos, vaga, pesos=pesos, hoje=data_referencia)
            ranking = reordenar_com_llm(ranking, {c.arquivo: c for c in curriculos}, vaga, client, top_n=int(top_n))
        st.session_state.resultado = {"ranking": ranking, "curriculos": {c.arquivo: c for c in curriculos}, "vaga": vaga,
                                      "falhas": falhas, "com_ia": client is not None, "cartas": {}}

# ==========================================
# 3. O RESULTADO
# ==========================================
res = st.session_state.get("resultado")
if res:
    ranking, vaga_res = res["ranking"], res["vaga"]
    aprovados = [a for a in ranking if a.aprovado]
    reprovados = [a for a in ranking if not a.aprovado]
    rotulos = {a.arquivo: (rotulo_anonimo(i) if anonimo else a.nome) for i, a in enumerate(ranking, 1)}

    st.divider()
    st.subheader("3. Ranking")
    for falha in res["falhas"]:
        st.warning(falha)
    if not res["com_ia"]:
        st.warning(f"⚠️ **Modo degradado:** {MOTIVO_SEM_CHAVE}. A nota e o ranking (regras + embeddings) são os mesmos; "
                   "as recomendações são montadas por regras e não há reordenação pela IA.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Analisados", len(ranking))
    m2.metric("Passaram no filtro", len(aprovados))
    m3.metric("Reprovados nos requisitos", len(reprovados))

    if aprovados:
        tabela = pd.DataFrame([{
            "#": a.posicao, "Candidato": rotulos[a.arquivo], "Nota": a.nota,
            "Competências": a.notas_secoes.get("competencias"), "Experiência": a.notas_secoes.get("experiencia"),
            "Formação": a.notas_secoes.get("formacao"), "Anos": a.anos,
            "Desejáveis ausentes": ", ".join(a.ausentes_desejaveis),
        } for a in aprovados])
        st.dataframe(
            tabela, hide_index=True, use_container_width=True,
            column_config={"Nota": st.column_config.ProgressColumn("Nota (0-100)", min_value=0, max_value=100, format="%.1f")},
        )
    else:
        st.info("Ninguém passou no filtro dos requisitos obrigatórios. Revise a lista de requisitos ou veja os motivos abaixo.")

    st.download_button("📥 Baixar ranking (CSV para o RH)", ranking_para_csv(ranking, anonimo=anonimo),
                       file_name="ranking_candidatos.csv", mime="text/csv")

    st.markdown("#### Por que cada nota")
    for a in aprovados:
        with st.expander(f"#{a.posicao} · {rotulos[a.arquivo]} · nota {a.nota:.1f}"):
            st.progress(min(1.0, a.nota / 100))
            s1, s2, s3 = st.columns(3)
            s1.metric("Competências", a.notas_secoes["competencias"])
            s2.metric("Experiência", f"{a.notas_secoes['experiencia']}", f"{a.anos:g} ano(s) ({a.fonte_anos})", delta_color="off")
            s3.metric("Formação", a.notas_secoes["formacao"], a.formacao, delta_color="off")
            st.markdown("**Atendidos:** " + (", ".join(a.atendidos) or "-"))
            if a.ausentes_desejaveis:
                st.markdown("**Desejáveis ausentes:** " + ", ".join(a.ausentes_desejaveis))
            if not a.estrutura_reconhecida:
                st.caption("⚠️ Não reconheci as seções deste currículo; analisei o texto inteiro, então a nota é menos precisa.")
            analise = a.analise or {}
            if analise.get("origem") == "llm":
                st.markdown(f"**Avaliação da IA ({analise['nota']}/100):** {analise['justificativa']}")
                if analise["pontos_fortes"]:
                    st.markdown("Pontos fortes: " + "; ".join(analise["pontos_fortes"]))
                if analise["lacunas"]:
                    st.markdown("Lacunas: " + "; ".join(analise["lacunas"]))
            st.info(f"**Recomendação:** {analise.get('recomendacao', '')}" + ("" if analise.get("origem") == "llm" else "  \n*(montada por regras, não pela IA)*"))
            if a.evidencias:
                with st.popover("Evidências no currículo"):
                    for req, trecho in a.evidencias.items():
                        st.markdown(f"**{req}:** {trecho}")

    if reprovados:
        st.markdown("#### Reprovados nos requisitos (não recebem nota)")
        for a in reprovados:
            with st.expander(f"{rotulos[a.arquivo]}: {a.motivos_reprovacao[0]}"):
                for motivo in a.motivos_reprovacao:
                    st.markdown(f"- {motivo}")
                if st.button("✉️ Gerar carta de retorno", key=f"carta_{a.arquivo}"):
                    client = None
                    if api_key.strip():
                        try:
                            client = criar_cliente(api_key)
                        except FalhaLLM:
                            client = None
                    carta, degradada, motivo = gerar_carta(a, res["curriculos"][a.arquivo], vaga_res, client)
                    if anonimo:
                        carta["corpo"] = carta["corpo"].replace(a.nome, rotulos[a.arquivo])
                    res["cartas"][a.arquivo] = (carta, degradada, motivo)
                if a.arquivo in res["cartas"]:
                    carta, degradada, motivo = res["cartas"][a.arquivo]
                    if degradada:
                        st.caption(f"Carta montada por regras ({motivo}).")
                    st.text_area("Carta", value=f"{carta['assunto']}\n\n{carta['corpo']}", height=260, key=f"txt_{a.arquivo}")
