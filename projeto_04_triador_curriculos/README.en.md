Versão em português: [README.md](README.md)

# Resume Screener and Scorer

Paste a job description and upload a batch of resumes in PDF format. The system rejects candidates who fail mandatory requirements before scoring, ranks the remainder from 0 to 100, explains each score, highlights candidate gaps, and exports rankings to CSV. Project 04 of the "7 AI Projects to Build in a Weekend" challenge.

```bash
python projeto_04_triador_curriculos/dados_ficticios.py            # (already generated) recreates 40 fictitious resumes
streamlit run projeto_04_triador_curriculos/app_triador.py
python projeto_04_triador_curriculos/avaliar_ranking.py            # reproduces figures below
```

> **Personal data.** Resumes contain personal data (LGPD). All resumes in this repository are **fictitious**, script-generated, with `@example.com` emails. Do not use real resumes in public demonstrations.

## How it works

1. **Extraction** ([texto.py](texto.py)): PyMuPDF in reading order. Scanned PDFs are rejected with a clear message (no OCR).
2. **Sections** ([secoes.py](secoes.py)): education, experience, skills, etc., in Portuguese or English. Scoring the entire document as a single block yields nonsensical scores. If no sections are recognized, entire text is parsed and candidate receives a warning flag.
3. **Filtering before scoring** ([pontuacao.py](pontuacao.py)): mandatory requirements, minimum experience years, and minimum education act as **hard filters, not weights**. Disqualified candidates display the exact reason and receive no score (preventing skewed rankings).
4. **Section scores, 0 to 100**: skills (requirement coverage, mandatory weighted 2x, plus semantic similarity), experience (duration calculated from date ranges plus similarity), and education. Cosine similarity is never displayed; nobody in HR knows how to interpret "0.78".
5. **Experience duration** ([experiencia.py](experiencia.py)): sums months across employment ranges without double-counting overlapping periods ("2 years" and "10 years of Python" produce nearly identical vectors; cosine similarity cannot tell the difference). Year-only dates are handled conservatively.
6. **Optional AI** ([analise_llm.py](analise_llm.py)): with an API key, the top 10 candidates are re-evaluated using explicit criteria (composite score: 60% rules + 40% AI), with justification, strengths, and gaps. Without a key, everything continues running via rules and the UI warns (degraded mode). AI never overturns hard filters.
7. **Gap analysis and feedback letter** for disqualified candidates, citing actual reasons and suggested study topics.
8. **CSV export for HR** ([exportacao.py](exportacao.py)): `;` delimiter, decimal comma, and UTF-8 BOM, allowing Brazilian Portuguese Excel to open without corrupted accents.

## Privacy and bias

- Everything runs locally. Only data sent to the LLM API passes through [privacidade.py](privacidade.py): email, phone, CPF, links, and candidate name are replaced with placeholders (`[CANDIDATO]`); dates and skills are preserved. Tests ensure none of these leak into prompts.
- Prompts instruct ignoring name, gender, age, photo, and location. **Anonymous mode** replaces names and filenames with "Candidate 01" on screen and in CSV.
- Acts as decision support, not automated decision-making: HR professionals must review (LGPD grants individuals the right to review automated decisions).

## The numbers (fictitious resumes, sample job post)

40 resumes generated across 7 archetypes with known fit: 8 ideal seniors (score 3), 10 solid mid-level (2), 6 basic mid-level (1), and 16 score-0 resumes engineered to deceive: 6 **keyword-stuffed juniors**, 5 **seniors in a different stack** (Java/Scala, no Python), 3 **without Git**, and 2 marketing candidates.

| Method | NDCG@10 | Precision@5 (score ≥ 2) | Score 0 in top 10 | Score 3 among top 8 |
|---|---|---|---|---|
| Cosine only (naive) | **0.64** | 0.80 | **2** | **2 of 8** |
| Rules, without mandatory filter | 1.00 | 1.00 | 0 | 8 of 8 |
| Full rules | 1.00 | 1.00 | 0 | 8 of 8 |

What cosine alone demonstrates, measured: the keyword-stuffed junior achieves the **highest** cosine similarity with the job description (0.945 average), while the ideal senior achieves 0.935. Similarity rewards vocabulary over years of experience.

Sub-tasks with dedicated ground truth: average error of **0.02 years** in extracted experience (maximum 0.5, on resumes providing only year), **40/40** sections recognized, **1.0 precision and recall** detecting 10 requirements. Robustness (accent-stripped, all caps, English headings, missing headings): NDCG@10 of 1.0 and zero approval changes.

### How to read these numbers (honestly)

- **1.00 is not proof of quality.** Resumes and ground-truth scores originate from the generator I wrote, with non-overlapping year ranges and formats the parser expects. It functions as a **regression test** and as a demonstration that cosine-only ranking fails on adversarial cases from the e-book (0.64), not as an estimate of real-world resume performance.
- That "without filter" also yields 1.00 proves that, in this dataset, the filter does not alter NDCG (section scores already eliminate score-0 candidates). The filter exists for another reason: providing HR with objective, auditable disqualification reasons.
- Parser generalization is tested independently with hand-crafted edge cases across diverse formats ([tests/test_p4_triador.py](../tests/test_p4_triador.py)). This already caught two personal bugs (a "3" in "3 years" stripped as list numbering, and "present" resetting the duration).
- What would give real validity to these metrics: anonymized real-world resumes with candidate fit labeled by HR professionals.

## Limitations

- No OCR (scanned PDFs are rejected). Two-column or heavily graphical documents can scramble text extraction order.
- Tech taxonomy contains ~55 skills; unlisted skills are matched as literal phrases (no synonyms). Language fluency levels are not evaluated.
- Does not distinguish "5 years of Python" from "5 years total experience": tallies total employment duration, not tenure per technology.
- The AI layer was tested with a mock client, **never against real Gemini**. Run the app with your key once to verify.
- Portuguese and English only.
