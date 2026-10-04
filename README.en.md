Versão em português: [README.md](README.md)

# AI Projects

Applied AI projects built from the "7 AI Projects to Build in a Weekend" challenge, with a shared core (`core/`), automated tests, and two principles: **when the system does not use AI, it warns the user** (degraded mode), and **every project publishes a measured number**.

| # | Project | How to run | Measured number |
|---|---------|------------|-----------------|
| 01 | [RAG Chatbot](projeto_01_chatbot_rag/) over custom documents: section-aware chunks, reranker, "I don't know", verified citations, prompt injection defense, incremental synchronization | `streamlit run projeto_01_chatbot_rag/app.py` | 68 questions across 8 fictitious documents: recall@1 0.889 → 0.963 and MRR 0.941 → 0.981; "I don't know" rejects 71% of unanswerable questions (weak point). **AI responses: run `6_avaliar_resposta.py` with your key** |
| 02 | [Market monitor](projeto_02_analisador_acoes/): sentiment vs. price dashboard **and** monitoring service (event store, incremental scoring, change detection, competitor menu from photo, HTML Radar with review, noise measurement) | `streamlit run projeto_02_analisador_acoes/app_radar.py` | 80 real headlines hand-labeled: **58.8% noise**, 45% of it duplicates. Replacing deduplication with embeddings removed **11 of 21 repetitions** (the previous rule removed 0). 2nd cycle: 0 new, 0 sent to AI |
| 03 | [Video studio](projeto_03_resumidor_youtube/): creates videos on **any topic** from context (editable script, 5 layouts, 5 themes, voiceover), analyzes YouTube videos (map-reduce, quiz, clips) and maintains TACTO's Reels | `streamlit run projeto_03_resumidor_youtube/app_youtube.py` | 90 video generator tests, highlighted number only if present in context; script quality with Gemini: **run with your key**; no summary quality metric yet |
| 04 | [Resume screener](projeto_04_triador_curriculos/): filtering before scoring, experience duration calculated from date ranges, privacy (LGPD), CSV export for HR | `streamlit run projeto_04_triador_curriculos/app_triador.py` | NDCG@10 across 40 **fictitious** resumes: cosine-only 0.64, rules 1.00 (synthetic dataset: acts as regression test, not as real-world estimate; see README) |
| 05 | [Secure Text-to-SQL](projeto_05_gerador_sql/): AST validation + read-only SQLite | `streamlit run projeto_05_gerador_sql/app_sql.py` | execution accuracy across 50 questions: ground truth 100%, offline mode 0%, **Gemini: run with your key** |

Not yet built: 06 (multi-agent research) and 07 (personal finance).

**Windows shortcut:** double-click [iniciar_apps.bat](iniciar_apps.bat) to open a menu that launches each app (ports 8501 to 5, in the browser) and shows what is running. Or via terminal: `iniciar_apps.bat 1 3` starts 1 and 3, `iniciar_apps.bat parar` stops all.

## Setting up the environment

Create the virtual environment **outside synchronized folders** (OneDrive/Dropbox): a `.venv` contains tens of thousands of files.

```bash
python -m venv ~/.venvs/projetos-ia
source ~/.venvs/projetos-ia/Scripts/activate      # Windows PowerShell: ~\.venvs\projetos-ia\Scripts\Activate.ps1
pip install -r requirements-dev.txt               # dependencies + pytest + local package `core`
```

`requirements.lock.txt` stores the exact versions everything was tested with. The Gemini key is pasted in each app's sidebar; without it, apps run in offline mode and display a warning indicating what was not performed by AI.

## Structure

```
core/                    shared code
  llm.py                   Gemini client: retry only on transient errors (429/5xx), timeout, structured output
                           validated by Pydantic with one repair attempt, disk cache, latency and token logging
  degradacao.py            standard texts for degraded mode
  embeddings.py            multilingual embeddings (e5) with query/passage prefixes; text-to-text similarity
  midia.py                 ffmpeg location detection
projeto_0X_*/            one Streamlit app per project, each with a README and its measured number
tests/                   pytest: pure functions, security, indexing, simulated AI, and app smoke tests
.github/workflows/       CI (pytest on every push)
```

## Tests

```bash
pytest                   # unit + app smoke tests (no network and no API key)
pytest -m network        # includes tests that use the internet (RSS, Yahoo Finance)
```

AI is simulated in tests using a mock client, so the suite covers retries, schema mismatches, quota exhaustion, and caching without spending API calls. **What the tests do not prove**: behavior against real Gemini (the `response_schema` with Pydantic models was validated during SDK conversion, but no real calls were made in this environment). Run `avaliar_acuracia.py --modo gemini` once with your key to close this gap.

## Degraded mode convention

Every step that can fall back returns `degradado` (bool) and `motivo_degradado` (text), and the interface displays a yellow warning with the reason (no API key, API failure, output outside schema). No fallback returns generic text pretending to be a valid result.

## When the API quota runs out

Gemini's 429 arrives as a long string containing error JSON inside, and the two factors determining what action to take were buried inside it: **how long to wait** (`retryDelay`) and **which quota** was exceeded ([core/cota.py](core/cota.py)).

- **Per-minute limit**: resolved by waiting. Backoff used to be 2 s and 4 s, which was too short — now the wait time matches what the API itself suggested (tens of seconds), and **only once**: waiting three times would freeze the screen for minutes with no benefit.
- **Per-day limit**: waiting will not solve it. There is no retry at all, and the message instructs the user to switch keys, enable billing, or return tomorrow.

The explanation is written once, parsed from the full error, and travels flagged as ready to read (`FalhaLLM.amigavel`). Without this flag, it was re-wrapped in "AI call failure (...)" and truncated at 140 characters mid-word — which occurred during real usage.

In both cases, the key is **blocked** for the indicated duration ([core/llm.py](core/llm.py)): quota belongs to the key, not to an individual call. Without this, each subsequent step in a map-reduce pipeline repeated retries and wait times for nothing — causing four stages to fail slowly, one after another, with the exact same error. The first successful call clears the block.

## How much it costs, in money

Measured by running the entire pipeline against a mock client that records prompts, on an 18m30s video (17,141 transcript characters): **8 calls, 60,090 input characters and 9,509 output characters** — roughly 15,000 input tokens and 2,400 output tokens, counting ~4 characters per token.

At `gemini-3.6-flash` pricing ($0.75 per million input tokens and $3.75 per million output tokens, checked at [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing)):

| | per video | 100 videos |
|---|---|---|
| Full analysis + 1 assembled video | **US$ 0.020** | US$ 2.02 |
| Each additional language | US$ 0.001 | — |

By duration: 5 min ≈ US$ 0.013; 18 min ≈ US$ 0.020; 45 min ≈ US$ 0.034; 90 min ≈ US$ 0.057. Starting January 1, 2027, the model's price doubles; `gemini-3.5-flash-lite` costs about half the current price.

**These numbers are a lower bound and underestimate the bill.** They account only for prompt tokens and visible response tokens. The model also consumes **thinking tokens**, billed as output at the same $3.75 per million rate — and offline measurement cannot observe them. In a scenario with 12,000 thinking tokens, the cost rises from US$ 0.020 to US$ 0.065. Actual usage measured by those who ran with an API key was around R$ 0.16 per video.

For this reason, the app began counting `thoughts_token_count`, which was previously omitted from `estatisticas()`, and the sidebar displays the session's dollar cost based on tokens reported directly by the API ([core/preco.py](core/preco.py)). This is measurement, not an estimate.

**88% of the input comes from the transcript being sent three times** — in map, clips, and script. This is the obvious target if cost becomes an issue: the three stages could branch from partial summaries instead of the full text, or leverage the API's context caching ($0.075 per million, plus hourly storage).

The sidebar displays session expenditure, how much was served from disk cache (repeating the same analysis consumes neither quota nor money again), and how many seconds remain on key lockouts.

## Known backlog

- P1: "I don't know" based solely on relevance scores rejects 71% of unanswerable questions; sufficiency check via AI remains to be measured (`6_avaliar_resposta.py`, requires API key) along with a ground truth using real documents (the current one is fictitious and self-authored). Hybrid search is implemented, but did not help on this corpus.
- P2: the 10 duplicate instances that embedding deduplication still misses; measuring **alert** accuracy (requires multiple cycles, not just a single collection); labeling headlines to compare lexicon vs. LLM vs. FinBERT; sending Radar via email and scheduling; measuring menu extraction against ground truth with a real key; Google Reviews and ingredient prices as new event types; querying the event store in Portuguese reusing P5's SQL validator; 12-month backtest.
- P3: Whisper for videos without subtitles; automatic subtitle cleanup; word-level synchronized subtitles in video.
- P4: anonymized real resumes with fit labeled by HR (the synthetic set saturates); OCR; comparing the AI stage with rule-based screening using a real key.
- P5: running ground truth with Gemini and publishing the number; user-pasted schemas.
