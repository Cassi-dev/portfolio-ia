Versão em português: [README.md](README.md)

# News Monitor: Sentiment, Change, and Stock Prices

Two ways to use the same foundation: the **on-demand dashboard** (news sentiment vs. stock price) and the **monitor**, which runs autonomously, remembers what it has already seen, and flags what changed since last time. Project 02 of the "7 AI Projects to Build in a Weekend" challenge. An NLP study, **not investment advice**.

```bash
streamlit run projeto_02_analisador_acoes/app_mercado.py            # single-stock dashboard, on demand
python projeto_02_analisador_acoes/rodar_monitor.py --criar-exemplo # creates target registry to edit
python projeto_02_analisador_acoes/rodar_monitor.py                 # one monitor cycle
```

## The monitor

The dashboard alone is not a monitor: it restarts from scratch on every run, so it cannot tell what changed. The monitor adds state.

1. **Target registry** ([monitorados.py](monitorados.py)): a client (a restaurant, a portfolio) and their targets — themselves, competitors, and market themes. Saved in `monitorados.json`, validated by Pydantic on load, so typos surface immediately instead of silently resulting in an empty collection. The template is [monitorados.exemplo.json](monitorados.exemplo.json); the real file contains client names and emails and remains outside git.
2. **Free-term collection** ([coleta_noticias.py](coleta_noticias.py)): search is no longer limited to tickers. Any set of search terms works, with an optional theme to disambiguate ("Bar do Zé" alone pulls results from across the entire country).
3. **Event store** ([base_eventos.py](base_eventos.py)): local SQLite. Each headline becomes a row with a stable identifier (target hash + normalized title). Two deduplication layers: exact, preventing the same headline from entering twice, and near-duplicate (Jaccard ≥ 0.60), clustering the same news story published across five portals.
4. **Incremental scoring** ([ciclo.py](ciclo.py)): only items lacking a score go to the AI, in batches of 60. Previously, the entire batch was resent on every run — cache operates on full calls, so a single new headline forced repurchasing the other hundred.
5. **Detectors** ([deteccao.py](deteccao.py)): new arrival, volume spike, sentiment reversal, and trigger keywords ("interdição", "recuperação judicial", "inaugura"). Pure functions over lists, tested without database or network.
6. **Command line** ([rodar_monitor.py](rodar_monitor.py)): `--listar`, `--cliente`, `--historico`, `--json`, `--sem-ia`. The command invoked by a task scheduler.

## The Radar: what the client receives

The product is neither the app nor the database — it is the file delivered. The Radar is a self-contained HTML document (printable to PDF via browser) summarizing what changed, each line citing source, date, and link.

```bash
streamlit run projeto_02_analisador_acoes/app_radar.py         # review, generate, and approve
python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze --itens
python projeto_02_analisador_acoes/gerar_radar.py --cliente bar-do-ze
python projeto_02_analisador_acoes/gerar_radar.py --aprovar 1
```

Three design decisions stemming from the nature of the service:

1. **Nothing is AI-generated in the report.** It only organizes facts already in the database. An opening paragraph written by a model would be the single place in the product where hallucination could slip in — right in the deliverable bearing our signature. The footer explicitly states this to readers.
2. **The timeframe is "since the last Radar you received"**, not "the last 7 days": nothing is counted twice or lost in the gap between two editions. A discarded draft does not move the cutoff, so items in it reappear in the next edition.
3. **No one receives anything without human review.** The Radar starts as `rascunho` (draft) and must transition to `aprovado` (approved). Dispatch itself is deliberate and manual.

During review you uncheck noise. Deleting an item removes it from the Radar **and from detectors**, permanently — and each deletion serves as a human label of "this is not signal", providing raw data to measure false alarms later. Items can be restored.

When there are no updates, the Radar states "quiet week" instead of arriving empty: this too is valuable information.

### Running autonomously and delivering

The monitor collects in the background; the Radar is still sent by your hand.

```bash
schtasks /create /tn "Radar - monitor semanal" /tr "caminho\monitor_agendado.bat" /sc weekly /d MON /st 07:00
python projeto_02_analisador_acoes/gerar_radar.py --simular-envio 7    # shows the email, does not send
python projeto_02_analisador_acoes/gerar_radar.py --enviar 7           # actually sends
```

[monitor_agendado.bat](monitor_agendado.bat) is invoked by Windows Task Scheduler: runs all clients and logs daily to `logs/`, because scheduled tasks that fail fail silently. The scheduling command is commented inside the file itself.

Dispatch ([entrega.py](entrega.py)) has three safeguards, since it is the only component speaking to the world on the client's behalf:

1. **Only approved Radars are dispatched.** Drafts, discarded, and previously sent reports are rejected with an explicit reason. Human review cannot be bypassed.
2. **Passwords never enter the repository.** Everything is loaded from environment variables (`RADAR_SMTP_HOST`, `RADAR_SMTP_USUARIO`, `RADAR_SMTP_SENHA`, and optionally `RADAR_SMTP_PORTA` and `RADAR_REMETENTE`). On Gmail, use an App Password.
3. **`--simular-envio` previews exactly what would be sent** — sender, recipient, subject, body, and attachment — without credentials and without touching the network.

The email body displays highlights **frozen at the moment of generation**, not a fresh database query: clients receive what was reviewed and approved, even if the monitor gathered newer items since then. The complete Radar is attached as HTML; it is not embedded in the body because email clients strip CSS header styles, breaking layout.

No emails were sent during development: tests use a mock SMTP server, and all three rejection paths (draft, unconfigured, client without email) were verified.

### What visual inspection caught

Generating the Radar with 80 real events and a restaurant menu revealed two defects no unit test would have caught: prices formatted as `R$ 12.00` (Python default, rather than Brazilian standard) and highlights repeating target names ("Boteco Central: Boteco Central sofre interdição..."). Both have been fixed and covered by regression tests.

## Competitor menu from photo

News coverage for small restaurants is sparse. The data business owners actually care about — competitor pricing — is not available in free feeds, and marketplace scraping is out of bounds: iFood's terms of service prohibit automated scraping for competitive monitoring. The source here is a photo.

```bash
python projeto_02_analisador_acoes/cardapio_ficticio.py          # generates two test menus and ground truth
GEMINI_API_KEY=... python projeto_02_analisador_acoes/adicionar_cardapio.py \
    --cliente bar-do-ze --alvo concorrente-a --comparar foto.jpg
```

A photo (or PDF) is converted into a table of items and prices ([cardapio.py](cardapio.py)), and from the second capture onward the monitor tracks what increased, decreased, was added, or was removed. **The image itself is not stored**: only the extracted table and filename are kept.

Work is divided as usual across the repo: the model only **reads** and copies prices exactly as printed (`"R$ 48,90"`); Python handles numeric conversion, item matching across captures, and delta calculations, where it can be tested without incurring API costs.

Precautions enforced in code, because each would manifest as an error before the client:
- **Items are not identical just because their names look similar.** Matching uses normalized names ("X-Salada" = "X Salada"); loosely similar names must clear a high threshold and **numbers in the name must match**, preventing "Burger 180g" from ever matching "Burger 250g". Fuzzy matches are reported for inspection.
- **An illegible price is not a changed price.** An item without a legible price in either capture moves to `sem_comparacao`, not "increased".
- **A cropped photo is not a shrunken menu.** If over 40% of items "disappear", a warning flags that the photo may be incomplete.
- **There is no offline mode.** Without an API key, image reading cannot run, and the CLI states this clearly instead of feigning output.

### What is verified and what is not

Comparison logic is tested against a 15-item scenario with ground truth derived from prices ([cardapio_ficticio.py](cardapio_ficticio.py)): 4 increases, 1 decrease, 2 new items, 1 removed, 1 incomparable, 8 unchanged. When manually writing that ground truth, I mistakenly classified a soda price drop as an increase; deriving it programmatically from prices caught the bug, and a regression test now guards it.

**Image reading via Gemini was never executed.** Schema, prompt, request assembly, and error handling are verified with a mock client, but the quality of what the model extracts from a photo — especially a skewed, dimly lit shot of a laminated menu — only surfaces with an active API key. The fictitious menus are clean computer-generated images: passing them is a baseline, not definitive proof.

### What the first live execution showed

Running against Google News with two restaurant chains and an industry sector topic:

| | cycle 1 | cycle 2, minutes later |
|---|---|---|
| Collected | 80 | 80 |
| New | 80 | **0** |
| Sent to AI | 80 | **0** |

That zero is the core objective: cost tracks newly surfaced items, not the total monitoring window size.

The initial execution also uncovered an unforeseen flaw: **all three targets triggered a "volume spike"**. It was not a spike. RSS feeds return significantly more recent stories than older ones (in all three cases, over 60% of the month fell within the last 7 days, compared to ~23% under uniform distribution), so the snapshot from an initial fetch cannot serve as a baseline. The detector now receives the date since when the target has been actively tracked, calculates averages strictly over that period, and does not declare spikes until 14 days of observation have elapsed. The first collection is flagged accordingly and suppresses alerts — everything in it is new by definition.

## How much of this is noise? (measured)

A monitor that floods clients with junk gets canceled. This is the project's first measured number addressing that.

I hand-labeled **all 80 real headlines** from the collection above, one by one, recording the reason for every discard ([medir_monitor.py](medir_monitor.py) exports and imports these labels). The criterion: is this worth showing to a restaurant owner tracking Madero, Outback, and the broader industry?

```bash
python projeto_02_analisador_acoes/medir_monitor.py --cliente rede-exemplo
```

| | |
|---|---|
| **Noise rate** | **58.8%** (47 of 80) |
| Worst target | `setor-food-service`, 61% noise across 54 items |
| Top reason | **duplicate: 21 items, 45% of all discards** |
| Subsequent reasons | irrelevant regional news (19%), advertorials (19%), archive pages (8%) |

Six out of every ten items would be discarded during review. This measures **precision** (what appears but shouldn't), not recall: what the monitor missed out in the wild is not captured here and cannot be estimated from this data.

Radar reviews feed this metric naturally: discarded items become "noise" labels, while survivors in approved Radars become "useful" labels. Hand-crafted labels are never overwritten by automated ones.

### The fix derived from the measurement

Because the largest slice of noise was repetition, deduplication was overhauled. There were 11 stories published across 2 to 5 portals, representing 21 repetitions to eliminate. Rules were tested against these clusters ([deduplicacao.py](deduplicacao.py) contains the full table):

| Rule | Duplicates removed | False mergers |
|---|---|---|
| jaccard ≥ 0.60 (previously deployed) | **0 of 21** | 0 |
| jaccard ≥ 0.35 | 5 of 21 | 1 |
| containment ≥ 0.50 | 6 of 21 | 9 |
| embedding, cosine ≥ 0.95 | 5 of 21 | 0 |
| **embedding, cosine ≥ 0.93** (adopted) | **11 of 21** | 1 |

Shared vocabulary alone is insufficient: portals rewrite titles entirely. "Mulher encontra aparelho dentário em prato do Outback" and "Cliente relata ter encontrado objeto estranho em prato de rede famosa" describe the same story while sharing almost no words. Lowering token overlap thresholds merges unrelated stories before catching duplicates.

The monitor transitioned to embeddings (the same `multilingual-e5-small` from Project 01) to decide "this is the same news item". Re-collecting from identical sources: **79 headlines, 68 retained — 11 duplicate repetitions blocked**, exactly as predicted. `--dedup tokens` toggles back to the legacy model-free mode.

A false merger costs one real story that never reaches the client. Across 80 headlines, one occurred (two distinct Outback promotions). Users preferring to err on the other side can use 0.95, sacrificing half the gain.

### The next fix, already written and not yet adopted

The remaining noise consists of non-repetitions: off-target news, archive pages, advertorials, and other regions' local news. None of these relate to sentiment — which is where AI calls had been spent up to this point.

[relevancia.py](relevancia.py) flips this: instead of scoring headline sentiment, it asks whether the story warrants inclusion in that specific client's briefing. It is cheaper (binary yes/no) and directly addresses 100% of the measured noise.

**It is deliberately not activated in the cycle.** First it must be measured against the same human labels:

```bash
GEMINI_API_KEY=... python projeto_02_analisador_acoes/avaliar_relevancia.py \
    --cliente rede-exemplo \
    --cadastro projeto_02_analisador_acoes/dados_medicao/cadastro.json \
    --banco projeto_02_analisador_acoes/dados_medicao/monitor.db
```

Measurement data lives in [dados_medicao/](dados_medicao/): 80 versioned labels serving as evidence for the figures above, alongside the database for immediate execution. Costs 4 API calls.

The result exposes what matters: how much noise the filter catches and **how much good news it accidentally throws away** — the costly mistake. If justified, it enters review by unchecking probable noise for human confirmation, never discarding autonomously. This matches how deduplication was evaluated, and how my initial hypothesis was overturned.

### Two ideas tested and rejected

The industry sector target accounts for 33 of 47 discards, making narrower terms seem like an obvious fix. It was not. Experiments and numbers are documented in [experimentos/](experimentos/):

| Idea | Result | Decision |
|---|---|---|
| Split sector into 4 subtopics | noise rate drops (60% → 36-43% in three of four), but volume expands from 54 to **213** headlines | rejected |
| Place-name heuristic for "out-of-region news" | catches 6 of 9 regional items, at the cost of **5 of 33 useful ones** | rejected |

Splitting improves the rate while worsening the workload: targeted searches dig deeper into the long tail, yielding four times as many items, almost all regional. Reviewing more items with a better percentage creates more work, not less. And `setor-eventos` ended up with 82% noise, worse than the single target: "feira OR congresso OR expo" retrieves local events from any city.

The location heuristic fails on the best items ("Outback chega ao Shopping Uberaba", "Papa Johns estreia em São Paulo", "Madero confirma restaurante no Paraná"): it cannot distinguish *news about a place* from *national news mentioning a place* — and on a monitor, missing a competitor opening a location is the most expensive mistake possible.

Together, both experiments show the same thing: **noise does not stem from broad queries or geographic terms in titles.** It stems from content type (advertorials, archive pages) and client relevance — which depends on who the client is, not title syntax. This is precisely the context fed into the relevance filter.

**How to read these numbers:** 80 headlines, a single annotator (myself), without second opinion. It measures obvious cases — duplicates, archive pages, advertorials — not nuanced relevance judgments, which are client-dependent. Value lies in the order of magnitude and indicating the next fix, not the third decimal place.

### Monitor limits

Detector thresholds (spike ≥ 2x mean, reversal ≥ 0.30, 3-event minimum) remain **heuristics, not measured figures** — what was measured above is item relevance, not alert accuracy. Measuring alerts requires observing multiple cycles and judging every interruption; a single run cannot measure this. The local lexicon was written for financial headlines and almost always returns 0.00 on restaurant news; in "business" profiles, sentiment without an API key offers little — the cycle warns about this in its output. News coverage for small restaurants is limited: chains and regulatory actions surface; neighborhood bars do not. There is only one event type (news); menus, reviews, and ingredient pricing are future steps.

## Single-stock dashboard

## How it works

1. **Collection** ([coleta_noticias.py](coleta_noticias.py)): Google News RSS with company name, asset ticker, and timeframe (`when:30d`); US market in English. Deduplication via Jaccard similarity.
2. **Sentiment** ([analise_sentimento.py](analise_sentimento.py)): validated structured output (`score` from -1 to +1, classification, reasoning). Without a key, or if AI fails or skips a headline, falls back to lexicon and **flags the headline** (`motor = lexico` + reason), with a UI warning. Lexicon matches full words and handles polarity inversion ("falls less than expected" is positive).
3. **Trading session alignment** ([cruzamento_precos.py](cruzamento_precos.py)): each story maps to the first trading session where price could reflect it, using the price series' actual trading calendar. News after market close (5 PM in São Paulo, 4 PM in New York) maps to the next day; weekends and holidays map to the next trading session; news after the most recent trading session lacks a price and is omitted.
4. **Smoothed series**: exponential moving average per trading session (adjustable half-life). Relative decay from "today", used in the first version, distorted historical series.
5. **Statistical rigor** ([analise_estatistica.py](analise_estatistica.py)): directional accuracy against the **baseline** (best constant guess) with binomial p-value, and lagged correlation from 0 to 5 trading sessions. With fewer than 30 days, verdict is "inconclusive".

## What changed in collection (measured)

The old query returned headlines from 2024 through 2026-09-02 and none from the last 16 days (the `limite_dias` parameter existed but was never utilized). The new query retrieves 98 headlines, all between 08/25 and 09/18 (87% mentioning company in title). The hypothesis that the old query was "dropping the ticker" was not confirmed: 98% mentioned Petrobras.

## General limitations

Without a hand-labeled headline dataset, classifier accuracy (lexicon vs. LLM vs. FinBERT) cannot yet be established. FinBERT was trained in English, so a fair comparison applies to US tickers. RSS returns ~100 items maximum, leaving a 6-month window sparse.
