import re
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

import feedparser

# ==========================================================
# PROCESSO 1: COLETA DE MANCHETES & DEDUPLICAÇÃO
# ==========================================================

NOMES_EMPRESAS = {
    "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú", "BBAS3": "Banco do Brasil", "MGLU3": "Magazine Luiza",
    "AAPL": "Apple", "NVDA": "Nvidia", "TSLA": "Tesla",
}


def normalizar_ticker(ticker):
    t = ticker.upper().strip()
    return t[:-3] if t.endswith(".SA") else t


def _termo_de_busca(termo):
    """Nome próprio vai entre aspas (busca a expressão inteira); código de ativo, não ("PETR4" exato acha menos)."""
    return termo if re.fullmatch(r"[A-Z0-9.]+", termo) else f'"{termo}"'


def montar_url_termos(termos, tema="", limite_dias=30, regiao="BR"):
    """
    Consulta ao Google News RSS para qualquer conjunto de termos (um ticker, o nome de um restaurante...).
    Os termos são agrupados com parênteses: sem eles o operador OR pode soltar parte da busca.
    """
    grupo = " OR ".join(_termo_de_busca(t.strip()) for t in termos if str(t).strip())
    if not grupo:
        raise ValueError("é preciso ao menos um termo de busca")
    consulta = " ".join(p for p in (f"({grupo})", tema.strip(), f"when:{limite_dias}d") if p)
    idioma = "hl=pt-BR&gl=BR&ceid=BR:pt-419" if regiao == "BR" else "hl=en-US&gl=US&ceid=US:en"
    return f"https://news.google.com/rss/search?q={urllib.parse.quote(consulta)}&{idioma}"


def montar_url(ticker, limite_dias=30):
    """Consulta de uma ação: usa o nome da empresa além do código e um tema financeiro."""
    t = normalizar_ticker(ticker)
    brasileiro = t[-1:].isdigit()
    nome = NOMES_EMPRESAS.get(t)
    tema = "(ação OR ações OR dividendos OR resultado OR balanço)" if brasileiro else "(stock OR shares OR earnings OR analyst)"
    return montar_url_termos(([nome] if nome else []) + [t], tema, limite_dias, "BR" if brasileiro else "US")


def limpar_titulo(titulo):
    # Remove a fonte no final (ex: ' - InfoMoney', ' - Valor Econômico')
    titulo_limpo = re.sub(r'\s*-\s*[^-]+$', '', titulo)
    return titulo_limpo.strip()


def tokenizar(texto):
    palavras = re.findall(r'\w+', texto.lower())
    # Ignora palavras curtas / stopwords comuns
    return set(p for p in palavras if len(p) > 3)


def calcular_similaridade(t1, t2):
    # Similaridade de Jaccard entre as palavras dos títulos
    tokens1 = tokenizar(t1)
    tokens2 = tokenizar(t2)
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)


def deduplicar(noticias, limiar=0.60):
    """A mesma notícia costuma sair em 5 portais; mantém a primeira de cada grupo parecido."""
    unicas = []
    for n in noticias:
        if not any(calcular_similaridade(n["titulo"], u["titulo"]) >= limiar for u in unicas):
            unicas.append(n)
    return unicas


def filtrar_por_data(noticias, limite_dias, hoje=None):
    corte = (hoje or datetime.now(timezone.utc).date()) - timedelta(days=limite_dias)
    return [n for n in noticias if date.fromisoformat(n["data"]) >= corte]


def _item_para_noticia(item):
    titulo_original = item.title
    fonte = item.get("source", {}).get("title", "Portal de Notícias")
    if " - " in titulo_original:
        fonte = titulo_original.split(" - ")[-1].strip()

    if item.get("published_parsed"):
        publicado = datetime(*item.published_parsed[:6], tzinfo=timezone.utc)
    else:
        publicado = datetime.now(timezone.utc)

    return {
        "titulo": limpar_titulo(titulo_original),
        "data": publicado.date().isoformat(),
        "publicado_em": publicado.isoformat(),
        "fonte": fonte,
        "link": item.link,
    }


def coletar_de_url(url, limite_dias=30, rotulo=""):
    """Baixa o RSS, filtra pela janela e deduplica dentro do lote. Devolve a lista de manchetes."""
    feed = feedparser.parse(url)
    brutas = [_item_para_noticia(item) for item in feed.entries]
    recentes = filtrar_por_data(brutas, limite_dias)
    unicas = deduplicar(recentes)
    print(f"  -> {rotulo}brutas: {len(brutas)} | na janela: {len(recentes)} | únicas após deduplicação: {len(unicas)}")
    return unicas


def coletar_por_termos(termos, tema="", limite_dias=30, regiao="BR"):
    """Coleta por termos livres — é o que permite monitorar um restaurante, e não só um ticker."""
    return coletar_de_url(montar_url_termos(termos, tema, limite_dias, regiao), limite_dias,
                          rotulo=f"[{', '.join(termos)}] ")


def coletar_noticias(ticker="PETR4", limite_dias=30):
    print(f"Buscando notícias em tempo real para o ticker: '{ticker}' (últimos {limite_dias} dias)...")
    return coletar_de_url(montar_url(ticker, limite_dias), limite_dias, rotulo="Manchetes ")


if __name__ == "__main__":
    ticker_teste = "PETR4"
    noticias = coletar_noticias(ticker_teste)

    print("\n" + "=" * 60)
    print(f"EXEMPLO DAS 5 PRIMEIRAS MANCHETES DEDUPLICADAS ({ticker_teste}):")
    print("=" * 60)
    for i, n in enumerate(noticias[:5], 1):
        print(f"[{i}] {n['data']} | {n['fonte']}")
        print(f"    \"{n['titulo']}\"")
