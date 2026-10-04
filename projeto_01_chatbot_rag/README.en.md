Versão em português: [README.md](README.md)

# RAG Chatbot on Custom Documents

Chatbot that answers questions about uploaded PDFs, `.txt`, and `.md` files, displaying which file, page, and **section** each answer came from, and admitting when it does not know. Project 01 of the "7 AI Projects to Build in a Weekend" challenge.

```bash
python projeto_01_chatbot_rag/1_processar_documentos.py     # synchronizes index with documentos/ (only reindexes changes)
streamlit run projeto_01_chatbot_rag/app.py
```

Without an API key, the app runs in **100% local mode** (shows the most relevant passage, with source). With a Google Gemini key, the answer is generated in natural language **with citations verified by the system** against the documents.

## How it works

1. **Indexing** ([indexacao.py](indexacao.py), [estrutura.py](estrutura.py)): full-sentence chunks (~500 characters, 15% overlap). Each chunk starts with **"Document > Section"** and stores the section in metadata (the e-book asks for file, page, and section). There is an overview chunk per document (title, opening, and list of sections). The ID is a content hash: reindexing is idempotent, re-uploading a file *replaces* its chunks, and synchronization **skips what hasn't changed** (file hash + indexing version).
2. **Search** ([recuperacao.py](recuperacao.py)): 5 modes. `vetorial` (multilingual embeddings), `bm25` (keyword search, custom implementation), `hibrido` (both, merged via RRF) and versions with cross-encoder **reranker** (`mmarco-mMiniLMv2`). Filter by document.
3. **"I don't know" mode**: with reranker, the decision uses its score (clearer separation); without, it uses distance to the top chunk. The threshold is adjustable in the UI.
4. **Answer with verifiable citations** ([resposta.py](resposta.py)): the AI responds in structured format and quotes the exact sentence supporting each assertion. The system verifies whether it exists in the cited passage; an altered number ("30 days" instead of "7 days") always fails verification. Answers whose citations do not match **are not shown**: the original passage appears along with a warning.
5. **Prompt injection defense** ([seguranca_rag.py](seguranca_rag.py)): a document may contain text crafted to deceive the model ("ignore previous rules..."). Passages enter the prompt as data, between numbered delimiters, with size and count limits, stripped of invisible characters, and with explicit instructions never to follow them. Typical injection patterns are detected and flagged on screen.
6. **Conversation**: follow-up questions ("and can I split the payment?") are rewritten as complete standalone questions based on chat history (with API key).
7. **Logging and feedback** ([registro.py](registro.py)): each query logs query, mode, decision, and latency per stage to `registros/consultas.jsonl` (locally only, outside git; `RAG_LOG=0` disables). The 👍/👎 votes become candidate test questions via [4_exportar_feedback.py](4_exportar_feedback.py), for your review.
8. **Documents**: UI panel to list, filter search, delete, and synchronize; scanned PDFs go through Gemini OCR upon upload.

## The numbers

[5_avaliar_recuperacao.py](5_avaliar_recuperacao.py) evaluates retrieval across **68 questions** on **8 fictitious documents** in Portuguese ([corpus_ficticio/](corpus_ficticio/)): 8 literal, 24 paraphrases, 16 with numbers or acronyms, 6 broad ("what is this document about?"), and 14 **unanswerable**, of which 6 are "borderline on-topic" (e.g., "what is the dental health plan coverage?", when the handbook only covers general health insurance). Each answerable question points to an evidence sentence, so ground truth remains valid even if chunk boundaries change. A passage is considered a match when it comes from the expected file and contains the evidence sentence.

```bash
python projeto_01_chatbot_rag/5_avaliar_recuperacao.py      # ~4 min, runs offline
```

| Indexing + search | recall@1 | recall@3 | MRR@5 | AUROC "I don't know" | AUROC "borderline on-topic" | average latency |
|---|---|---|---|---|---|---|
| old + vector (legacy system) | 0.889 | 1.000 | 0.941 | 0.824 | 0.599 | 22 ms |
| old + bm25 | 0.815 | 0.944 | 0.886 | 0.778 | 0.486 | 1 ms |
| old + hybrid | 0.907 | 0.981 | 0.942 | 0.824 | 0.599 | 23 ms |
| old + vector + reranker | 0.870 | 0.944 | 0.917 | 0.854 | 0.691 | 1016 ms |
| **contextual + vector** | **0.963** | 0.981 | 0.976 | 0.819 | 0.586 | 26 ms |
| contextual + bm25 | 0.852 | 0.926 | 0.896 | 0.767 | 0.457 | 1 ms |
| contextual + hybrid | 0.944 | 1.000 | 0.969 | 0.819 | 0.586 | 29 ms |
| **contextual + vector + reranker** (default) | **0.963** | 1.000 | **0.981** | **0.874** | **0.707** | 713 ms |

("old" = chunks without headers; AUROC = probability that an answerable question receives a higher score than an unanswerable one, where 0.5 is random chance and 1.0 separates perfectly. Full results, covering all 10 combinations and recall per question type, are saved in `resultados/avaliacao_recuperacao.json`.)

### What the numbers say

- **Adopted: contextual headers** ("Document > Section" in chunk). Recall@1 rose from 0.889 to 0.963 and MRR from 0.941 to 0.976 in vector search, with improvements in BM25 and hybrid as well (not an artifact of a single configuration). This is the cheapest win: no noticeable latency cost.
- **Adopted as default, with caveat: reranker.** It does not improve ranking order in isolation (without headers it actually worsens: 0.870 vs. 0.889), but it improves **separation for "I don't know"**: AUROC increases from 0.819 to 0.874, and from 0.586 to 0.707 on "borderline on-topic" questions. The cost is ~0.7 s per query. Can be switched to "vector only" in the sidebar.
- **Not adopted: hybrid search (BM25 + vector).** On this corpus it did not help (0.944 vs. 0.963 on recall@1) and BM25 alone performs worst (0.852). Literature suggests hybrid helps with codes, IDs, and rare tokens; this corpus barely contains any, and the multilingual vector model already handles acronyms and numbers accurately. It remains implemented and available, but is not the default. With many error codes or proper nouns, it is worth measuring again.
- **Removed: keyword heuristics patch** ("summary", "context") that previously redirected broad questions. They now reach 100% recall@3 without it, thanks to the document overview chunk.

### "I don't know" is still weak

With the cutoff chosen on half the questions and measured on the other half, the top mode (contextual + reranker) answers 85% of answerable questions and rejects **71%** of unanswerable ones (without reranker: 82% and 64%). On "borderline on-topic" questions, AUROC is 0.71. A relevance score (distance or reranker) struggles to separate "the document mentions the topic" from "the document answers the question". The real next step is having the AI check whether the excerpt is sufficient (already implemented as the `suficiente` field in response) and **measuring this with an API key**: [6_avaliar_resposta.py](6_avaliar_resposta.py) runs all 68 questions end-to-end and measures correct answers, omissions, incorrect answers, and especially **hallucinated answers** on unanswerable questions.

```bash
GEMINI_API_KEY=... python projeto_01_chatbot_rag/6_avaliar_resposta.py      # ~70 API calls
```

Default UI cutoffs (reranker score −4.0; distance 0.16) remain close to cross-calibration findings on this corpus (around −4.2 and 0.135) and are slightly more permissive. On your documents, [3_calibrar_parametros.py](3_calibrar_parametros.py) calibrates thresholds using your own questions.

### How to read this (honestly)

Both corpus and questions were written by the author of the system, with a portion of questions intentionally paraphrased; with only 54 answerable questions, a difference of 2 questions shifts recall by ~0.04. It serves to **compare variations**, not as an absolute performance estimate on real-world documents.

## What has not yet been verified

The path using real Gemini (response with citations, query rewriting, OCR, context summary) and prompt injection defense against a live model were tested only with a simulated client. Tests prove the logic (a citation with an altered number is rejected, an excerpt containing instructions is flagged and delimited), not that any specific model will obey the rules. `6_avaliar_resposta.py` exists to close this gap.

## Limitations

No search inside PDF tables (text is linearized). Scanned PDFs depend on Gemini OCR. Reranker is multilingual (mMARCO) and medium-sized (downloaded on first run); larger models may separate "I don't know" more effectively at higher latency costs. Logging saves queries in plain text locally on your machine.

## Stack

Python 3.11+ · ChromaDB · sentence-transformers (`multilingual-e5-small` and reranker `mmarco-mMiniLMv2-L12-H384-v1`) · Streamlit · Google Gemini (optional)
