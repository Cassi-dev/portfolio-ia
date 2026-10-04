import pytest

from estrutura import classificar_linha, dividir_em_secoes, resumo_estrutural, titulo_do_documento


def test_titulo_vem_do_h1_da_primeira_linha_ou_do_nome_do_arquivo():
    assert titulo_do_documento("# Manual de RH\n\nTexto.", "x.md") == "Manual de RH"
    assert titulo_do_documento("MANUAL DE POLÍTICAS INTERNAS - FOCO TI\n\nSEÇÃO 1: X", "y.txt") == "MANUAL DE POLÍTICAS INTERNAS - FOCO TI"
    longa = "Esta é uma frase longa de abertura que termina com ponto e portanto não é um título do documento em si mesmo."
    assert titulo_do_documento(longa, "politica_de_compras.pdf") == "Politica de compras"


def test_secoes_markdown_e_titulo_do_documento_nao_e_secao():
    md = "# Título\n\nIntrodução do documento.\n\n## Férias\n\nTexto das férias.\n\n## Licenças\n\nTexto das licenças."
    assert dividir_em_secoes(md) == [
        ("", "Introdução do documento."), ("Férias", "Texto das férias."), ("Licenças", "Texto das licenças."),
    ]


def test_secoes_no_formato_secao_numero_e_caixa_alta():
    texto = "MANUAL\n\nSEÇÃO 1: POLÍTICA DE REEMBOLSO\n- O cliente tem 7 dias.\n\nSEÇÃO 2: SUPORTE\n- Atendimento 24h."
    secoes = dividir_em_secoes(texto)
    assert [s for s, _ in secoes] == ["", "Seção 1: política de reembolso", "Seção 2: suporte"] or \
           [s for s, _ in secoes][-2:] == ["Seção 1: política de reembolso", "Seção 2: suporte"]
    assert any("7 dias" in corpo for _, corpo in secoes)


def test_titulo_numerado_vira_secao_mas_lista_numerada_nao():
    texto = "1. Ingestão e chunking\nCarregue os arquivos.\n\nPassos\n\n1. Abra o portal\n2. Clique em novo\n3. Envie\n"
    nomes = [s for s, _ in dividir_em_secoes("Intro.\n\n" + texto)]
    assert "1. Ingestão e chunking" in nomes
    assert "1. Abra o portal" not in nomes


def test_linha_de_conteudo_nunca_vira_secao():
    for linha in ["O cliente tem prazo de até 7 dias corridos.", "Quantos dias?", "- item de lista", "a" * 120]:
        assert classificar_linha(linha, True) is None


def test_secao_continua_de_uma_pagina_para_a_outra():
    assert dividir_em_secoes("continuação do texto sem título", secao_inicial="Férias") == [("Férias", "continuação do texto sem título")]


def test_resumo_estrutural_traz_titulo_abertura_e_secoes_sem_repetir():
    r = resumo_estrutural("Manual X", "Este manual reúne as regras.", ["", "Férias", "Férias", "Licenças"])
    assert r == "Documento: Manual X. Este manual reúne as regras. Seções: Férias; Licenças."
