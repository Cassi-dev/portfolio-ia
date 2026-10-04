Versão em português: [README.md](README.md)

# Secure Text-to-SQL

Ask in Portuguese, receive the SQL (displayed before results), the execution result, and the reasoning behind any blocked queries. Project 05 of the "7 AI Projects to Build in a Weekend" challenge.

```bash
streamlit run projeto_05_gerador_sql/app_sql.py
```

## How it works

1. **Prompt** ([motor_text_to_sql.py](motor_text_to_sql.py)): complete schema in every call, 4 few-shot examples, **today's date** (for "last month", "past 30 days"), and **categorical column candidate values** (without this the model guesses `'PWA'` instead of `'PWA TACTO'` and the query returns empty, with no error).
2. **Structured output**: the model returns an `{sql}` object validated by Pydantic. No markdown code fences to strip.
3. **1st guardrail, AST validator** ([validador_seguranca.py](validador_seguranca.py)): allows `SELECT`, `WITH` (including recursive), and `UNION/EXCEPT/INTERSECT`; blocks any other statement root, `PRAGMA`, `ATTACH`, nested writes, multiple statements, and dangerous functions like `load_extension`.
4. **2nd guardrail, SQLite itself** ([banco_dados.py](banco_dados.py)): connection `mode=ro` + `PRAGMA query_only` + `set_authorizer` (read-only), 1,000-row limit, and 5-second timeout (an infinite recursive query gets terminated). Guardrails are independent: tests attack the second **without** passing through the first.
5. **Correction loop**: if the database returns an error, it feeds back into the model (up to 2 retries). If the API fails, it falls back to offline mode **with a warning**.

## The sample database

40 customers, 14 products, 400 orders, and 1,024 order items, generated with fixed seed (deterministic data) and **consistent**: `pedidos.valor_total` always equals the sum of line items. (The previous version had 12 orders, 10 of which had totals differing from item sums, making accuracy measurement impossible.) `python projeto_05_gerador_sql/banco_dados.py --recriar` rebuilds the database.

## The measured number: execution accuracy

50 questions in Portuguese (filtering, aggregation, joins, ranking, dates, subqueries) with reference SQL hand-crafted in [perguntas_gabarito.json](perguntas_gabarito.json). A generated SQL query is correct when its **result** matches ground truth (row set, 2-decimal numbers; column names and row ordering do not matter unless marked as ordered questions).

```bash
python projeto_05_gerador_sql/avaliar_acuracia.py --modo gabarito      # sanity check of ground truth
python projeto_05_gerador_sql/avaliar_acuracia.py --modo offline       # baseline without AI
GEMINI_API_KEY=... python projeto_05_gerador_sql/avaliar_acuracia.py --modo gemini
```

| Mode | Execution accuracy |
|---|---|
| Ground truth against itself (sanity check, validates all 50 queries) | 50/50 (100%) |
| Offline, without AI (baseline) | 0/50 (0%) |
| Gemini | **run with your key and paste here**: results broken down by category, with latency and tokens, in `resultados/avaliacao_gemini.json` |

The 0% baseline is genuine: offline mode includes only 3 canned queries, none of which answer the benchmark questions. The ground truth was verified for ties: no ranking query contains ties at the top-N boundary.

## Known limitations

Comparing execution results is fairer than comparing raw SQL strings, but can still fail a valid SQL query that returns extra columns. The database is synthetic and small.
