"""
Tela de revisão do Radar: ver o que entraria, tirar o que é ruído e aprovar antes de mandar ao cliente.

    streamlit run projeto_02_analisador_acoes/app_radar.py

Nada sai daqui para o cliente: a tela gera o HTML e marca o estado. O envio é feito por você, de propósito —
é essa passagem por uma pessoa que evita o erro que cancela contrato.
"""
import json
import os
import sys

import streamlit as st

DIRETORIO = os.path.dirname(os.path.abspath(__file__))
if DIRETORIO not in sys.path:
    sys.path.insert(0, DIRETORIO)

import monitorados
from base_eventos import BaseEventos
from relatorio import montar_radar, renderizar_html, salvar_html, sem_novidade

st.set_page_config(page_title="Radar - revisão", page_icon="📡", layout="wide")
ESTADOS = {"rascunho": "📝", "aprovado": "✅", "enviado": "📤", "descartado": "🗑️"}


@st.cache_resource
def abrir_base(caminho: str):
    return BaseEventos(caminho or None)


with st.sidebar:
    st.header("📡 Radar")
    st.caption("Revisar e aprovar antes de enviar")
    caminho_banco = st.text_input("Banco do monitor", value="", placeholder="padrão: monitor.db")
    caminho_cadastro = st.text_input("Cadastro", value="", placeholder="padrão: monitorados.json")

try:
    cadastro = monitorados.carregar(caminho_cadastro or None)
except FileNotFoundError as erro:
    st.title("📡 Radar")
    st.error(str(erro))
    st.stop()

base = abrir_base(caminho_banco)
ids = [c.id for c in cadastro.clientes]
with st.sidebar:
    escolhido = st.selectbox("Cliente", ids, format_func=lambda i: cadastro.por_id(i).nome)
cliente = cadastro.por_id(escolhido)

st.title(f"📡 Radar · {cliente.nome}")
corte = base.corte_do_proximo_relatorio(cliente.id)
st.caption(f"Cobrindo o que entrou desde {corte[:16].replace('T', ' ') if corte else 'sempre (primeira edição)'}.")

nomes_dos_alvos = {a.id: a.nome for a in cliente.alvos}
candidatos = base.eventos_desde(cliente.id, corte)

aba_revisar, aba_historico, aba_excluidos = st.tabs(["✍️ Revisar", "📚 Radares", "🗑️ Descartados"])

with aba_revisar:
    if not candidatos:
        st.info("Nada novo desde o último Radar entregue. Rode o monitor (`rodar_monitor.py`) para coletar.")
    else:
        st.write(f"**{len(candidatos)} item(ns)** entrariam no próximo Radar. Desmarque o que for ruído.")
        c1, c2 = st.columns(2)
        if c1.button("Marcar todos", use_container_width=True):
            for e in candidatos:
                st.session_state[f"inc_{e['id']}"] = True
        if c2.button("Desmarcar todos", use_container_width=True):
            for e in candidatos:
                st.session_state[f"inc_{e['id']}"] = False

        manter = []
        for alvo_id in [a.id for a in cliente.alvos]:
            do_alvo = [e for e in candidatos if e["alvo_id"] == alvo_id]
            if not do_alvo:
                continue
            with st.expander(f"{nomes_dos_alvos[alvo_id]} ({len(do_alvo)})", expanded=True):
                for evento in do_alvo:
                    tom = f" · {evento['classificacao']}" if evento.get("motor") == "gemini" and evento.get("classificacao") else ""
                    rotulo = f"[{evento['data']}] {evento['titulo']} — *{evento['fonte']}{tom}*"
                    if st.checkbox(rotulo, value=True, key=f"inc_{evento['id']}"):
                        manter.append(evento["id"])

        descartar = [e["id"] for e in candidatos if e["id"] not in manter]
        st.divider()
        st.write(f"Vão para o Radar: **{len(manter)}** · serão descartados: **{len(descartar)}**")
        if st.button("📄 Gerar Radar", type="primary", disabled=not manter):
            if descartar:
                base.excluir_eventos(descartar, "descartado na revisão")
            radar = montar_radar(base, cliente)
            arquivo = salvar_html(radar)
            identificador = base.criar_relatorio(cliente.id, radar["periodo_de"], radar["periodo_ate"],
                                                 radar["corte"], radar["total_itens"], str(arquivo),
                                                 json.dumps(radar["destaques"], ensure_ascii=False))
            st.session_state.radar_gerado = {"id": identificador, "html": renderizar_html(radar),
                                             "arquivo": str(arquivo), "vazio": sem_novidade(radar)}
            st.rerun()

    if "radar_gerado" in st.session_state:
        gerado = st.session_state.radar_gerado
        st.success(f"Radar #{gerado['id']} gerado em `{gerado['arquivo']}`.")
        st.download_button("📥 Baixar o HTML", gerado["html"], file_name=os.path.basename(gerado["arquivo"]),
                           mime="text/html")
        a1, a2 = st.columns(2)
        if a1.button("✅ Aprovar (pronto para enviar)", use_container_width=True):
            base.mudar_estado(gerado["id"], "aprovado", "aprovado na tela de revisão")
            st.session_state.pop("radar_gerado")
            st.rerun()
        if a2.button("🗑️ Descartar este rascunho", use_container_width=True):
            base.mudar_estado(gerado["id"], "descartado", "descartado na tela de revisão")
            st.session_state.pop("radar_gerado")
            st.rerun()
        st.components.v1.html(gerado["html"], height=700, scrolling=True)

with aba_historico:
    registros = base.relatorios(cliente.id)
    if not registros:
        st.info("Nenhum Radar gerado para este cliente ainda.")
    for r in registros:
        with st.container(border=True):
            colunas = st.columns([3, 1, 1])
            colunas[0].write(f"{ESTADOS.get(r['estado'], '')} **#{r['id']}** · {r['periodo_de']} a {r['periodo_ate']} "
                             f"· {r['itens']} itens · {r['estado']}" + (f" · _{r['notas']}_" if r["notas"] else ""))
            if r["estado"] == "rascunho" and colunas[1].button("Aprovar", key=f"ap_{r['id']}"):
                base.mudar_estado(r["id"], "aprovado")
                st.rerun()
            if r["estado"] == "aprovado" and colunas[1].button("Marcar enviado", key=f"en_{r['id']}"):
                base.mudar_estado(r["id"], "enviado")
                st.rerun()
            if r["arquivo"] and os.path.exists(r["arquivo"]):
                colunas[2].caption(os.path.basename(r["arquivo"]))

with aba_excluidos:
    todos = base.eventos(cliente.id, incluir_excluidos=True)
    excluidos = [e for e in todos if e.get("excluido")]
    st.caption("O que você descartou não volta ao Radar nem conta nos detectores. Cada descarte também é um rótulo "
               "de 'isto é ruído', útil para medir a taxa de alarme falso mais adiante.")
    if not excluidos:
        st.info("Nada foi descartado ainda.")
    for evento in excluidos:
        colunas = st.columns([5, 1])
        colunas[0].write(f"[{evento['data']}] {evento['titulo']} — *{nomes_dos_alvos.get(evento['alvo_id'], '')}*")
        if colunas[1].button("Restaurar", key=f"re_{evento['id']}"):
            base.restaurar_eventos([evento["id"]])
            st.rerun()
