"""
Quanto custa o que já foi gasto.

Os tokens de **pensamento** são cobrados como saída — a tabela do Google diz "Preço de saída (incluindo tokens
de pensamento)" — e a saída custa 5 vezes a entrada. Eles não apareciam em lugar nenhum aqui, e por isso a
estimativa de custo saía bem abaixo do que a fatura mostra.

Preços por 1 milhão de tokens, em dólar, do nível pago, consultados em
https://ai.google.dev/gemini-api/docs/pricing em 20/09/2026. Modelo fora desta tabela devolve None: melhor não
mostrar custo nenhum do que mostrar um número inventado.
"""
from core.config import MODELO_GEMINI

PRECOS_USD = {
    "gemini-3.6-flash": {"entrada": 0.75, "saida": 3.75},        # dobra em 01/01/2027: 1,50 e 7,50
    "gemini-3.5-flash-lite": {"entrada": 0.30, "saida": 2.50},
    "gemini-3.5-flash": {"entrada": 0.50, "saida": 2.00},
}


def custo_usd(tokens_entrada: int, tokens_saida: int, modelo: str = MODELO_GEMINI) -> float | None:
    """`tokens_saida` já deve incluir os de pensamento, que são cobrados na mesma tarifa."""
    preco = PRECOS_USD.get(modelo)
    if not preco:
        return None
    return tokens_entrada / 1e6 * preco["entrada"] + tokens_saida / 1e6 * preco["saida"]
